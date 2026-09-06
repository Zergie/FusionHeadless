"""The bidirectional child/Fusion process conversation.

It owns the framing protocol after a connection is established.  Adapters only
provide the work for inbound commands and decide what a closed conversation
means for their own lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
import threading
from typing import Any, Callable

from bridge import FramedConnection


class ConversationError(RuntimeError):
    """Base error raised for a remote or malformed conversation result."""


class NestedFusionCallError(ConversationError):
    """A server callback attempted to reenter its waiting Fusion caller."""


class RemoteConversationError(ConversationError):
    """The other process rejected a command."""

    def __init__(self, message: str, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class ConversationResult:
    """Result of handling one inbound command."""

    value: Any = None
    binary: bool = False
    close: bool = False
    error: str | None = None
    error_type: str | None = None


CommandHandler = Callable[[dict[str, Any]], ConversationResult | Any]


class ProcessConversation:
    """A serialized, bidirectional request/reply conversation over frames."""

    def __init__(self, connection: FramedConnection) -> None:
        self._connection = connection
        self._write_lock = threading.RLock()
        self._invoke_lock = threading.RLock()
        self._replies: Queue[Any] = Queue()
        self._commands: Queue[Any] = Queue()
        self._closed = threading.Event()
        self._execution = threading.local()
        self._failure_lock = threading.Lock()
        self._failure: BaseException | None = None

    def execute_fusion(self, code: str) -> Any:
        return self._invoke({"command": "exec", "code": code, "reply": True})

    def restart(self, kind: str, *, show_terminal: bool = False) -> Any:
        return self._invoke({
            "command": "restart",
            "kind": kind,
            "show_terminal": show_terminal,
            "reply": True,
        })

    def call_server(
        self, name: str, args: list[Any], kwargs: dict[str, Any],
    ) -> Any:
        """Call the child while the dedicated reader delivers its reply."""
        return self._invoke({
            "command": "call", "name": name, "args": args, "kwargs": kwargs, "reply": True,
        })

    def close(self, reason: str | None = None) -> None:
        message: dict[str, Any] = {"command": "quit"}
        if reason is not None:
            message["reason"] = reason
        try:
            self._write(message)
        finally:
            self._fail(ConversationError(reason or "conversation closed locally"))

    def serve_forever(self, handler: CommandHandler) -> bool:
        """Execute commands serially while a dedicated thread reads frames.

        Handlers may synchronously dispatch to Fusion's UI thread or wait for
        a server callback. Neither wait prevents the reader delivering replies.

        Returns ``True`` for EOF (an unexpected peer exit) and ``False`` for a
        deliberate close command.
        """
        reader = threading.Thread(
            target=self._read_messages, name="fusionheadless-bridge-reader", daemon=True,
        )
        reader.start()
        try:
            while True:
                message = self._commands.get()
                if isinstance(message, EOFError):
                    return True
                elif isinstance(message, BaseException):
                    raise message
                else:
                    # Reject callback reentry before it takes the lock held by
                    # the original Fusion call. Independent request threads
                    # still wait normally for their turn.
                    self._execution.server_callback = message.get("command") == "call"
                    try:
                        finished = self._dispatch(message, handler)
                    finally:
                        self._execution.server_callback = False
                    if finished:
                        return False
        finally:
            self._closed.set()
            self._fail(ConversationError("conversation closed"))
            reader.join(timeout=1)

    def _read_messages(self) -> None:
        """Own every read, including replies to callbacks on other threads."""
        try:
            while not self._closed.is_set():
                message = self._connection.read()
                if isinstance(message, dict) and message.get("command"):
                    self._commands.put(message)
                    if message["command"] == "quit":
                        self._fail(ConversationError("conversation closed by peer"))
                        return
                elif isinstance(message, dict) and message.get("reply") is True:
                    self._replies.put(message)
                elif isinstance(message, bytes):
                    self._replies.put(message)
                else:
                    raise ConversationError(f"unexpected conversation message: {message!r}")
        except EOFError as error:
            self._fail(ConversationError("conversation closed by peer"))
            self._commands.put(error)
        except Exception as error:
            self._fail(error)
            self._commands.put(error)

    def _invoke(self, message: dict[str, Any]) -> Any:
        if message["command"] in ("exec", "restart") and getattr(self._execution, "server_callback", False):
            raise NestedFusionCallError(
                "Nested Fusion calls are not supported: a server callback cannot "
                "invoke Fusion or restart while Fusion is waiting for its result"
            )
        with self._invoke_lock:
            if self._failure is not None:
                raise self._failure
            self._write(message)
            return self._result(self._read_reply())

    def _read_reply(self) -> Any:
        """Wait for the reader, propagating closure even during a binary reply."""
        response = self._replies.get()
        if isinstance(response, BaseException):
            raise response
        return response

    def _result(self, response: Any) -> Any:
        if not isinstance(response, dict) or response.get("reply") is not True:
            raise ConversationError(f"invalid conversation reply: {response!r}")
        if not response.get("ok"):
            raise RemoteConversationError(
                response.get("error", "remote command failed"), response.get("error_type")
            )
        if response.get("binary"):
            payload = self._read_reply()
            if not isinstance(payload, bytes):
                raise ConversationError("binary command returned an invalid payload")
            return payload
        return response.get("value")

    def _dispatch(self, message: dict[str, Any], handler: CommandHandler) -> bool:
        try:
            result = handler(message)
            result = result if isinstance(result, ConversationResult) else ConversationResult(result)
            if message.get("reply") and self._failure is None:
                if result.error is not None:
                    self._write({
                        "reply": True,
                        "ok": False,
                        "error": result.error,
                        "error_type": result.error_type or "ConversationError",
                    })
                    return result.close
                reply: dict[str, Any] = {"reply": True, "ok": True, "value": result.value}
                if result.binary:
                    if not isinstance(result.value, (bytes, bytearray, memoryview)):
                        raise ConversationError("binary command must return bytes")
                    reply = {"reply": True, "ok": True, "binary": True, "length": len(result.value)}
                # A close or outbound callback must not split a binary reply.
                with self._write_lock:
                    self._write(reply)
                    if result.binary:
                        self._write(bytes(result.value))
            return result.close
        except Exception as error:
            if message.get("reply"):
                if self._failure is None:
                    self._write({"reply": True, "ok": False, "error": str(error),
                                 "error_type": type(error).__name__})
                return False
            raise

    def _write(self, value: Any) -> None:
        with self._write_lock:
            self._connection.write(value)

    def _fail(self, error: BaseException) -> None:
        with self._failure_lock:
            if self._failure is None:
                self._failure = error
                self._replies.put(error)
