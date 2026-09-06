from __future__ import annotations

from concurrent.futures import Future
from queue import Queue
import threading
import unittest

from process_conversation import (ConversationError, ConversationResult,
                                  ProcessConversation, RemoteConversationError)


class LinkedConnection:
    """Small in-memory adapter for exercising the conversation interface."""

    def __init__(self) -> None:
        self.incoming: Queue[object] = Queue()
        self.peer: LinkedConnection | None = None
        self.read_threads: set[int] = set()

    def read(self):
        self.read_threads.add(threading.get_ident())
        value = self.incoming.get()
        if value is None:
            raise EOFError()
        return value

    def write(self, value) -> None:
        assert self.peer is not None
        self.peer.incoming.put(value)


def pair() -> tuple[ProcessConversation, ProcessConversation, LinkedConnection, LinkedConnection]:
    left, right = LinkedConnection(), LinkedConnection()
    left.peer, right.peer = right, left
    return ProcessConversation(left), ProcessConversation(right), left, right


class ProcessConversationTests(unittest.TestCase):
    def setUp(self):
        self.peer_errors = []
        self.addCleanup(lambda: self.assertEqual(self.peer_errors, []))

    def run_call(self, callback):
        result = Future()

        def run():
            try:
                result.set_result(callback())
            except Exception as error:
                result.set_exception(error)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 1)
        return result

    def start_peer(self, session: ProcessConversation, handler):
        def serve():
            try:
                session.serve_forever(lambda message: ConversationResult(close=True)
                                      if message["command"] == "quit" else handler(message))
            except Exception as error:
                self.peer_errors.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 1)
        return thread

    def start_pair(self, peer_handler):
        client, peer, left, right = pair()
        self.start_peer(client, lambda _message: ConversationResult())
        self.start_peer(peer, peer_handler)
        self.addCleanup(left.incoming.put, None)
        self.addCleanup(right.incoming.put, None)
        return client, peer, left, right

    def test_execute_returns_normal_value_through_the_interface(self) -> None:
        client, peer, _, _ = self.start_pair(
            lambda message: ConversationResult({"code": message["code"]})
        )
        self.assertEqual(client.execute_fusion("return 42"), {"code": "return 42"})

    def test_restart_passes_the_terminal_visibility_request(self) -> None:
        client, _peer, _, _ = self.start_pair(
            lambda message: ConversationResult(message)
        )

        result = client.restart("restart", show_terminal=True)

        self.assertEqual(result, {
            "command": "restart",
            "kind": "restart",
            "show_terminal": True,
            "reply": True,
        })

    def test_execute_consumes_the_binary_envelope(self) -> None:
        client, peer, _, _ = self.start_pair(
            lambda _message: ConversationResult(b"\x00png", binary=True)
        )
        self.assertEqual(client.execute_fusion("render"), b"\x00png")

    def test_remote_handler_error_is_classified(self) -> None:
        def fail(_message):
            raise ValueError("bad command")
        client, _peer, _, _ = self.start_pair(fail)
        with self.assertRaisesRegex(RemoteConversationError, "bad command"):
            client.execute_fusion("bad")

    def test_reverse_server_call_stays_inside_the_conversation(self) -> None:
        client, peer, left, right = pair()
        self.start_peer(client, lambda message: ConversationResult(
            message["args"][0] * 2 if message["command"] == "call" else None
        ))

        def execute(_message):
            # Model synchronous dispatch to Fusion's separate UI thread.
            def on_ui_thread():
                ui_threads.append(threading.get_ident())
                return peer.call_server("double", [21], {})

            return ConversationResult(self.run_call(on_ui_thread).result(timeout=2))

        ui_threads = []
        self.start_peer(peer, execute)
        self.addCleanup(left.incoming.put, None)
        self.addCleanup(right.incoming.put, None)
        self.assertEqual(self.run_call(
            lambda: client.execute_fusion("return double(21)")
        ).result(timeout=3), 42)
        self.assertEqual(len(right.read_threads), 1)
        self.assertTrue(right.read_threads.isdisjoint(ui_threads))

    def test_server_callback_rejects_nested_fusion_and_restart_then_recovers(self) -> None:
        client, peer, left, right = pair()

        def callback(message):
            if message["name"] == "restart":
                return client.restart("restart")
            return client.execute_fusion("nested")

        def execute(message):
            if message["code"] == "after callback":
                return 42
            return peer.call_server(message["code"], [], {})

        self.start_peer(client, callback)
        self.start_peer(peer, execute)
        self.addCleanup(left.incoming.put, None)
        self.addCleanup(right.incoming.put, None)
        for command in ("exec", "restart"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(RemoteConversationError, "[Nn]ested Fusion"):
                    self.run_call(lambda: client.execute_fusion(command)).result(timeout=2)
                self.assertEqual(self.run_call(
                    lambda: client.execute_fusion("after callback")
                ).result(timeout=2), 42)

    def test_peer_close_unblocks_a_pending_reverse_call(self) -> None:
        for closing_message in (None, {"command": "quit"}):
            with self.subTest(closing_message=closing_message):
                client, peer, left, right = pair()
                callback_started = threading.Event()
                release_callback = threading.Event()
                reverse_finished = threading.Event()

                def callback(_message):
                    callback_started.set()
                    release_callback.wait(3)

                def execute(_message):
                    try:
                        return peer.call_server("wait", [], {})
                    finally:
                        reverse_finished.set()

                self.start_peer(client, callback)
                self.start_peer(peer, execute)
                self.addCleanup(release_callback.set)
                self.addCleanup(left.incoming.put, None)
                self.addCleanup(right.incoming.put, None)
                result = self.run_call(lambda: client.execute_fusion("wait"))
                self.assertTrue(callback_started.wait(1))
                right.incoming.put(closing_message)
                # Closing the Fusion side wakes its pending callback, allowing
                # the original caller to fail instead of waiting indefinitely.
                left.incoming.put(closing_message)
                with self.assertRaises(ConversationError):
                    result.result(timeout=1)
                self.assertTrue(reverse_finished.wait(1))
                release_callback.set()

    def test_independent_fusion_request_waits_for_callback_and_runs_afterwards(self) -> None:
        client, peer, left, right = pair()
        callback_started = threading.Event()
        release_callback = threading.Event()
        executed = []

        def callback(_message):
            callback_started.set()
            release_callback.wait(3)
            return 21

        def execute(message):
            executed.append(message["code"])
            if message["code"] == "first":
                return peer.call_server("wait", [], {})
            return 42

        self.start_peer(client, callback)
        self.start_peer(peer, execute)
        self.addCleanup(release_callback.set)
        self.addCleanup(left.incoming.put, None)
        self.addCleanup(right.incoming.put, None)
        first = self.run_call(lambda: client.execute_fusion("first"))
        self.assertTrue(callback_started.wait(1))
        second_started = threading.Event()

        def second_request():
            second_started.set()
            return client.execute_fusion("second")

        second = self.run_call(second_request)
        self.assertTrue(second_started.wait(1))
        self.assertEqual(executed, ["first"])
        release_callback.set()
        self.assertEqual(first.result(timeout=1), 21)
        self.assertEqual(second.result(timeout=1), 42)
        self.assertEqual(executed, ["first", "second"])

    def test_eof_during_binary_payload_unblocks_waiter(self) -> None:
        client, _peer, left, right = pair()
        self.start_peer(client, lambda _message: None)
        result = self.run_call(lambda: client.execute_fusion("binary"))
        self.assertEqual(right.incoming.get(timeout=1)["command"], "exec")
        left.incoming.put({"reply": True, "ok": True, "binary": True, "length": 3})
        left.incoming.put(None)
        with self.assertRaisesRegex(ConversationError, "closed by peer"):
            result.result(timeout=1)

    def test_peer_eof_unblocks_a_waiting_request(self) -> None:
        client, _peer, left, _right = pair()
        thread = self.start_peer(client, lambda _message: ConversationResult())
        left.incoming.put(None)
        thread.join(1)
        with self.assertRaises(ConversationError):
            client.execute_fusion("after close")


if __name__ == "__main__":
    unittest.main()
