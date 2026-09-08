"""Small Fusion-side process adapter for the FastAPI child."""

from __future__ import annotations

from concurrent.futures import Future
from enum import Enum, auto
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from bridge import FramedConnection
from context import (FusionContext, generated_function, registry,
                     server_callback_scope)
from extension_state import close_startup_ui, extension_fingerprint, reset_extensions
from process_conversation import ConversationResult, ProcessConversation


_LOG = logging.getLogger(__name__)


class _Phase(Enum):
    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    REPLACING = auto()
    RESET_REQUIRED = auto()
    MISMATCH = auto()
    RECOVERING = auto()


class _ChildProcess:
    """Keep a launched child, its conversation, and their cleanup together."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        assert process.stdin is not None and process.stdout is not None
        self.conversation = ProcessConversation(FramedConnection(process.stdout, process.stdin))
        self._cleanup_lock = threading.Lock()
        self.startup_complete = threading.Event()
        self.startup_error: BaseException | None = None
        self.fingerprint: str | None = None
        self.owns_startup = False
        self.unexpected_exit = True
        self.serve_thread: threading.Thread | None = None

    def start_serving(self, handler: Any) -> None:
        def serve() -> None:
            try:
                self.unexpected_exit = self.conversation.serve_forever(handler)
            except BaseException as error:
                self.startup_error = self.startup_error or error
                self.unexpected_exit = True
            finally:
                if not self.startup_complete.is_set():
                    self.startup_error = self.startup_error or RuntimeError(
                        "child exited before reporting startup readiness"
                    )
                self.startup_complete.set()

        self.serve_thread = threading.Thread(target=serve, daemon=True)
        self.serve_thread.start()

    def terminate(self) -> None:
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def close(self, timeout: float = 1.0) -> None:
        """Release this child only; never touch a subsequently launched child."""
        with self._cleanup_lock:
            if self.process.poll() is None:
                try:
                    self.conversation.close()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    self.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self.terminate()
            if self.process.poll() is not None:
                for name in ("stdin", "stdout", "stderr"):
                    stream = getattr(self.process, name, None)
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass


class FusionAdapter:
    """Launch and stop the child; HTTP is deliberately not implemented here."""

    MAX_RESTART_ATTEMPTS = 3
    RESTART_DELAY = 1.0

    def __init__(
        self,
        *,
        host: Any | None = None,
        project_root: str | Path | None = None,
        port: int = 5000,
    ) -> None:
        self.host = host
        self.project_root = Path(project_root or __file__).resolve().parent
        self.port = port
        self._child: _ChildProcess | None = None
        self._replacement: _ChildProcess | None = None
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._startup: Future[bool] = Future()
        self._phase = _Phase.STOPPED
        self._shutdown_requested = threading.Event()
        self._restart_attempts = 0
        self._show_child_terminal = False
        self._extension_fingerprint = extension_fingerprint()

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        child = self._child
        return child.process if child is not None else None

    @property
    def intentional_shutdown(self) -> bool:
        return self._shutdown_requested.is_set()

    def register_fusion(self, *definitions: Any) -> None:
        """Register explicitly decorated Fusion definitions for this adapter."""
        registry.register_decorated("fusion", *definitions)

    def register_server(self, *definitions: Any) -> None:
        """Register explicitly decorated server exports used by Fusion code."""
        registry.register_decorated("server", *definitions)

    def start(self, timeout: float = 10.0) -> bool:
        with self._lifecycle_lock:
            if self._thread is None or not self._thread.is_alive():
                self._shutdown_requested.clear()
                self._restart_attempts = 0
                self._startup = Future()
                self._phase = _Phase.STARTING
                self._show_child_terminal = False
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
            startup = self._startup
        try:
            return startup.result(timeout=timeout)
        except TimeoutError:
            if startup.done():
                raise
            self.stop(timeout=0)
            raise TimeoutError("timed out while launching the server child") from None

    @property
    def child_interpreter(self) -> str:
        """Return the project's venv interpreter, with a useful local fallback."""
        candidates = (
            self.project_root / ".venv" / "Scripts" / "python.exe",
            self.project_root / ".venv" / "bin" / "python",
        )
        for path in candidates:
            try:
                # A POSIX venv may be present in a Windows checkout but its
                # ``bin/python`` launcher is not executable on this host.
                if path.exists() and os.access(path, os.X_OK) and not (
                    os.name == "nt" and path.parent.name == "bin"
                ):
                    return str(path)
            except OSError:
                # A venv copied from another OS can contain an inaccessible
                # symlink; the host interpreter remains a valid local fallback.
                continue
        return sys.executable

    def _run(self) -> None:
        try:
            self._supervise()
        finally:
            self._phase = _Phase.STOPPED
            if not self._startup.done():
                self._startup.set_result(False)

    def _supervise(self) -> None:
        """Supervise the child until shutdown is requested or Fusion aborts it."""
        while not self._shutdown_requested.is_set():
            if self._restart_attempts > 1:
                # Restart number one is immediate; every later retry is delayed.
                if self._shutdown_requested.wait(self.RESTART_DELAY):
                    return
            if self._phase in (_Phase.RESET_REQUIRED, _Phase.MISMATCH):
                try:
                    self._reset_extensions_on_ui_thread()
                except Exception:
                    _LOG.exception("Fusion extension recovery reset failed")
                    if not self._continue_recovery():
                        return
                    continue
                self._phase = _Phase.RECOVERING
            child: _ChildProcess | None = None
            try:
                child = self._launch_child(standby=False)
                with self._lifecycle_lock:
                    self._child = child
                # ``stop`` may have won the race while Popen was creating the
                # child.  Do not hand that child to the supervisor loop.
                if self._shutdown_requested.is_set():
                    return
                child.start_serving(
                    lambda message, current=child: self._handle_child_command(
                        current, message, standby=False
                    )
                )
                while child is not None:
                    assert child.serve_thread is not None
                    child.serve_thread.join()
                    unexpected_exit = child.unexpected_exit or self._phase is _Phase.MISMATCH
                    child.close()
                    with self._lifecycle_lock:
                        next_child = self._child if self._child is not child else None
                        if self._child is child:
                            self._child = None
                    if next_child is None:
                        break
                    child = next_child
            except BaseException as error:
                if not self._startup.done():
                    self._startup.set_exception(error)
                    return
                unexpected_exit = True
            finally:
                if child is not None:
                    child.close()
                    with self._lifecycle_lock:
                        if self._child is child:
                            self._child = None
                replacement = self._replacement
                if replacement is not None and replacement is not self._child:
                    replacement.close()
                    with self._lifecycle_lock:
                        if self._replacement is replacement:
                            self._replacement = None

            if self._shutdown_requested.is_set():
                return
            # A child which deliberately sends quit (including a port/lock
            # ownership conflict) is not a crash and must not be retried.
            if not unexpected_exit:
                if self._phase in (_Phase.REPLACING, _Phase.RESET_REQUIRED):
                    continue
                return
            # The initial child must report ready before it enters the
            # restartable supervision state.
            if not self._startup.done():
                return
            if not self._continue_recovery():
                return

    def _launch_child(self, *, standby: bool) -> _ChildProcess:
        popen_options: dict[str, Any] = {
            "cwd": self.project_root,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    filter(None, (str(self.project_root), os.environ.get("PYTHONPATH", "")))
                ),
            },
        }
        if os.name == "nt" and not self._show_child_terminal:
            # Fusion is a GUI application. Suppress the console window Windows
            # would otherwise create for the Python child.
            popen_options["creationflags"] = subprocess.CREATE_NO_WINDOW
        command = [self.child_interpreter, "-m", "server", "--port", str(self.port)]
        if standby:
            command.append("--standby")
        return _ChildProcess(subprocess.Popen(command, **popen_options))

    def _prepare_replacement(self) -> None:
        replacement = self._launch_child(standby=True)
        with self._lifecycle_lock:
            if self._shutdown_requested.is_set():
                stopped = True
            else:
                self._replacement = replacement
                stopped = False
        if stopped:
            replacement.close()
            raise RuntimeError("adapter stopped while warming the replacement child")
        replacement.start_serving(
            lambda message: self._handle_child_command(replacement, message, standby=True)
        )
        if not replacement.startup_complete.wait(10):
            self._discard_replacement(replacement)
            raise TimeoutError("timed out while warming the replacement child")
        if replacement.startup_error is not None:
            self._discard_replacement(replacement)
            raise RuntimeError(f"replacement child failed to start: {replacement.startup_error}")

    def _discard_replacement(self, replacement: _ChildProcess) -> None:
        with self._lifecycle_lock:
            if self._replacement is replacement:
                self._replacement = None
        replacement.close()

    def _activate_replacement(self, retiring: _ChildProcess) -> None:
        with self._lifecycle_lock:
            replacement = self._replacement
        if replacement is None:
            raise RuntimeError("replacement child is not ready")
        try:
            result = replacement.conversation.start_http_server()
            replacement.owns_startup = bool(
                isinstance(result, dict) and result.get("startup")
            )
        except Exception:
            self._discard_replacement(replacement)
            raise
        with self._lifecycle_lock:
            if self._shutdown_requested.is_set():
                if self._replacement is replacement:
                    self._replacement = None
                stopped = True
            else:
                self._child = replacement
                self._replacement = None
                stopped = False
        if stopped:
            replacement.close()
            raise RuntimeError("adapter stopped while activating the replacement child")
        self._phase = _Phase.RUNNING
        self._restart_attempts = 0

    def _handle_child_command(
        self, child: _ChildProcess, message: dict[str, Any], *, standby: bool
    ) -> ConversationResult:
        command = message.get("command")
        expected_ready = "standby-ready" if standby else "ready"
        if command == "startup":
            if standby:
                raise RuntimeError("standby child cannot install startup features")
            child.fingerprint = message.get("fingerprint")
            if child.fingerprint != self._extension_fingerprint:
                self._phase = _Phase.MISMATCH
                return ConversationResult(
                    error="child extension fingerprint mismatch",
                    error_type="ExtensionFingerprintError",
                )
            return ConversationResult({"accepted": True})
        if command == expected_ready:
            child.fingerprint = message.get("fingerprint")
            child.owns_startup = message.get("startup") is True
            if not standby and child.fingerprint != self._extension_fingerprint:
                child.startup_error = RuntimeError("child extension fingerprint mismatch")
                if not standby:
                    self._phase = _Phase.MISMATCH
                child.terminate()
                child.startup_complete.set()
                return ConversationResult(close=True)
            if not standby:
                self._phase = _Phase.RUNNING
                self._restart_attempts = 0
                if not self._startup.done():
                    self._startup.set_result(True)
            child.startup_complete.set()
            return ConversationResult()
        if command == "exec":
            result = self._handle_exec(message)
            return ConversationResult(result, binary=isinstance(result, (bytes, bytearray, memoryview)))
        if command == "quit":
            return ConversationResult(close=True)
        if command == "restart":
            show_terminal = message.get("show_terminal", False)
            if not isinstance(show_terminal, bool):
                raise ValueError("restart show_terminal must be a boolean")
            self._phase = _Phase.REPLACING
            self._show_child_terminal = show_terminal
            try:
                self._prepare_replacement()
            except Exception as error:
                self._phase = _Phase.RUNNING
                return ConversationResult(error=str(error), error_type="ReplacementStartupError")
            if child.owns_startup:
                try:
                    child.conversation.retire_startup()
                except Exception as error:
                    assert self._replacement is not None
                    self._discard_replacement(self._replacement)
                    self._phase = _Phase.RUNNING
                    return ConversationResult(
                        error=str(error), error_type="StartupRetirementError"
                    )
            try:
                self._reset_extensions_on_ui_thread()
            except Exception:
                _LOG.exception("Fusion extension reset failed")
                assert self._replacement is not None
                self._discard_replacement(self._replacement)
                self._phase = _Phase.RESET_REQUIRED
                return ConversationResult(
                    error="Fusion extension reset failed",
                    error_type="FusionResetError",
                )
            assert self._replacement is not None
            if self._replacement.fingerprint != self._extension_fingerprint:
                fingerprint = self._replacement.fingerprint
                self._discard_replacement(self._replacement)
                return ConversationResult(
                    error=("replacement extension fingerprint does not match Fusion: "
                           f"{fingerprint!r}"),
                    error_type="ReplacementFingerprintError",
                )
            return ConversationResult({"action": message.get("kind", "restart")})
        if command == "activate_replacement":
            self._activate_replacement(child)
            return ConversationResult({"action": "activated"})
        raise RuntimeError(f"unexpected child message: {message!r}")

    def _continue_recovery(self) -> bool:
        """Consume one bounded recovery attempt, prompting only after exhaustion."""
        if self._restart_attempts >= self.MAX_RESTART_ATTEMPTS:
            if not self._ask_to_keep_trying():
                self._shutdown_requested.set()
                return False
            self._restart_attempts = 0
        else:
            self._restart_attempts += 1
        if self._phase not in (_Phase.RESET_REQUIRED, _Phase.MISMATCH):
            self._phase = _Phase.RECOVERING
        return True

    def _reset_extensions_on_ui_thread(self) -> None:
        """Reload extension declarations through Fusion's UI-thread boundary."""
        dispatch = getattr(self.host, "dispatch", None)
        if not callable(dispatch):
            raise RuntimeError("Fusion extension reset requires a Fusion UI-thread dispatcher")
        self._extension_fingerprint = dispatch(reset_extensions)

    def _ask_to_keep_trying(self) -> bool:
        """Show the retry/abort decision on Fusion's UI thread."""
        dispatch = getattr(self.host, "dispatch", None)
        context_factory = getattr(self.host, "context", None)
        if not callable(dispatch) or not callable(context_factory):
            return False
        return bool(dispatch(self._show_restart_prompt, context_factory()))

    @staticmethod
    def _show_restart_prompt(context: dict[str, Any]) -> bool:
        ui = context.get("ui")
        adsk = context.get("adsk")
        if ui is None or adsk is None:
            return False
        result = ui.messageBox(
            "Fusion Headless could not restart three times.\n\n"
            "Choose Retry to begin a new recovery cycle, or Cancel to stop the add-in.",
            "Fusion Headless",
            adsk.core.MessageBoxButtonTypes.RetryCancelButtonType,
        )
        return result == adsk.core.DialogResults.RetryDialog

    def _handle_exec(self, message: dict[str, Any]) -> Any:
        if message.get("command") != "exec" or not isinstance(message.get("code"), str):
            raise RuntimeError(f"invalid adapter exec request: {message!r}")

        dispatch = getattr(self.host, "dispatch", None)
        if not callable(dispatch):
            raise RuntimeError("adapter exec requests require a Fusion UI-thread dispatcher")
        return dispatch(self._execute_code, message["code"])

    def _execute_code(self, code: str) -> Any:
        """Execute code after the host has dispatched this call to Fusion's UI thread."""
        context_factory = getattr(self.host, "context", None)
        if not callable(context_factory):
            raise RuntimeError("adapter exec requests require a Fusion execution context")
        namespace = context_factory()
        namespace["__builtins__"] = __builtins__
        namespace["fusion_context"] = FusionContext(
            namespace.get("app"), namespace.get("ui"), namespace.get("adsk")
        )
        namespace.update({name: definition.value for name, definition in registry.fusion.items()})
        namespace.update({name: self._server_proxy(name) for name in registry.server})
        function = generated_function(code)
        function.__globals__.update(namespace)
        with server_callback_scope(self._server_proxy):
            return function()

    def _server_proxy(self, name: str):
        def call(*args: Any, **kwargs: Any) -> Any:
            child = self._child
            if child is None:
                raise RuntimeError("server bridge is not connected")
            return child.conversation.call_server(name, list(args), kwargs)
        return call

    def stop(self, timeout: float = 5.0, *, teardown_startup: bool = True) -> None:
        with self._lifecycle_lock:
            self._shutdown_requested.set()
            child, replacement, thread = self._child, self._replacement, self._thread
        if child is not None:
            if teardown_startup and child.owns_startup and child.process.poll() is None:
                try:
                    child.conversation.shutdown()
                except Exception:
                    pass
            child.close(timeout)
        if replacement is not None and replacement is not child:
            replacement.close(timeout)
        if thread is not None:
            thread.join(timeout=timeout)
        # A worker still inside Popen retains ownership. It will observe the
        # stop request and close its late child before it can serve any work.

    def stop_from_ui_thread(self, timeout: float = 5.0) -> None:
        """Stop when Fusion already owns the calling UI thread."""
        try:
            close_startup_ui()
        finally:
            self.stop(timeout, teardown_startup=False)

    def __enter__(self) -> "FusionAdapter":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
