from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks

from adapter import FusionAdapter
from bridge import FramedConnection
from extension_state import extension_fingerprint
from process_conversation import RemoteConversationError
import server
from tests.harness import FakeFusionHost


class ScriptedProcess:
    """A child-process adapter with deterministic incoming protocol messages."""

    def __init__(self, messages, *, running=False):
        output = io.BytesIO()
        frames = FramedConnection(io.BytesIO(), output)
        for message in messages:
            frames.write(message)
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(output.getvalue())
        self.stderr = io.BytesIO()
        self.returncode = None if running else 0
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True
        self.returncode = 1


class AdapterLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FusionAdapter(host=FakeFusionHost())
        self.adapter.RESTART_DELAY = 0
        self.addCleanup(self.adapter.stop)
        self.ready = {"command": "ready", "fingerprint": extension_fingerprint()}
        self.quit = {"command": "quit"}

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("lifecycle did not complete within two seconds")
            time.sleep(0.005)

    def test_initial_quit_or_eof_does_not_retry(self):
        for messages in ([self.quit], []):
            with self.subTest(messages=messages):
                child = ScriptedProcess(messages)
                with patch("adapter.subprocess.Popen", return_value=child) as launch:
                    self.assertFalse(self.adapter.start())
                    self.adapter.stop()
                self.assertEqual(launch.call_count, 1)
                self.assertTrue(child.stdout.closed)
                self.assertIsNone(self.adapter.process)

    def test_recovery_runs_on_worker_backs_off_and_prompts_after_three_attempts(self):
        children = [ScriptedProcess([self.ready]), *[ScriptedProcess([]) for _ in range(3)]]
        launch_threads = []

        def launch(*args, **kwargs):
            launch_threads.append(threading.current_thread())
            return children[len(launch_threads) - 1]

        self.adapter.RESTART_DELAY = 0.02
        with (patch("adapter.subprocess.Popen", side_effect=launch),
              patch.object(self.adapter, "_ask_to_keep_trying", return_value=False) as prompt):
            started = time.monotonic()
            self.assertTrue(self.adapter.start())
            self.wait_for(lambda: self.adapter.intentional_shutdown)
            self.adapter.stop()
        self.assertEqual(len(launch_threads), 4)
        self.assertTrue(all(thread is not threading.current_thread() for thread in launch_threads))
        self.assertGreaterEqual(time.monotonic() - started, 0.04)
        prompt.assert_called_once()
        self.assertTrue(all(child.stdin.closed and child.stdout.closed and child.stderr.closed
                            for child in children))

    def test_retry_starts_a_fresh_restart_budget(self):
        children = [ScriptedProcess([self.ready]), *[ScriptedProcess([]) for _ in range(7)]]
        with (patch("adapter.subprocess.Popen", side_effect=children) as launch,
              patch.object(self.adapter, "_ask_to_keep_trying", side_effect=[True, False]) as prompt):
            self.assertTrue(self.adapter.start())
            self.wait_for(lambda: self.adapter.intentional_shutdown)
            self.adapter.stop()
        self.assertEqual(launch.call_count, 8)
        self.assertEqual(prompt.call_count, 2)

    def test_ready_resets_the_budget_after_recovery(self):
        children = [ScriptedProcess([self.ready]), ScriptedProcess([]),
                    ScriptedProcess([self.ready]), *[ScriptedProcess([]) for _ in range(3)]]
        with (patch("adapter.subprocess.Popen", side_effect=children) as launch,
              patch.object(self.adapter, "_ask_to_keep_trying", return_value=False) as prompt):
            self.assertTrue(self.adapter.start())
            self.wait_for(lambda: self.adapter.intentional_shutdown)
            self.adapter.stop()
        self.assertEqual(launch.call_count, 6)
        prompt.assert_called_once()

    def test_replacement_resets_extensions_and_forwards_terminal_option(self):
        children = [ScriptedProcess([self.ready, {"command": "restart", "show_terminal": True}, self.quit]),
                    ScriptedProcess([self.ready, self.quit])]
        with (patch("adapter.subprocess.Popen", side_effect=children) as launch,
              patch("adapter.reset_extensions", return_value=extension_fingerprint()) as reset):
            self.assertTrue(self.adapter.start())
            self.wait_for(lambda: children[-1].stdout.closed)
            self.adapter.stop()
        self.assertEqual(launch.call_count, 2)
        reset.assert_called_once()
        self.assertIn(reset, self.adapter.host.app.dispatched)
        if os.name == "nt":
            self.assertEqual(launch.call_args_list[0].kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
            self.assertNotIn("creationflags", launch.call_args_list[1].kwargs)

    def test_failed_reset_is_retried_before_launching_the_replacement(self):
        children = [ScriptedProcess([self.ready, {"command": "restart"}, self.quit]),
                    ScriptedProcess([self.ready, self.quit])]
        with (patch("adapter.subprocess.Popen", side_effect=children) as launch,
              patch("adapter.reset_extensions", side_effect=[RuntimeError("bad import"),
                    RuntimeError("still bad"), extension_fingerprint()]) as reset,
              self.assertLogs("adapter", level="ERROR")):
            self.assertTrue(self.adapter.start())
            self.wait_for(lambda: children[-1].stdout.closed)
            self.adapter.stop()
        self.assertEqual(reset.call_count, 3)
        self.assertEqual(launch.call_count, 2)

    def test_initial_fingerprint_mismatch_terminates_child_without_recovery(self):
        child = ScriptedProcess([{"command": "ready", "fingerprint": "mismatch"}], running=True)
        with patch("adapter.subprocess.Popen", return_value=child) as launch:
            self.assertFalse(self.adapter.start())
            self.adapter.stop()
        self.assertTrue(child.terminated)
        self.assertTrue(child.stdout.closed)
        self.assertEqual(launch.call_count, 1)

    def test_recovery_fingerprint_mismatch_resets_before_retrying(self):
        children = [ScriptedProcess([self.ready]),
                    ScriptedProcess([{"command": "ready", "fingerprint": "mismatch"}], running=True),
                    ScriptedProcess([self.ready, self.quit])]
        with (patch("adapter.subprocess.Popen", side_effect=children) as launch,
              patch("adapter.reset_extensions", return_value=extension_fingerprint()) as reset):
            self.assertTrue(self.adapter.start())
            self.wait_for(lambda: children[-1].stdout.closed)
            self.adapter.stop()
        self.assertEqual(launch.call_count, 3)
        self.assertTrue(children[1].terminated)
        reset.assert_called_once()

    def test_stop_during_launch_cleans_late_child_without_serving_it(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        child = ScriptedProcess([self.ready], running=True)

        def launch(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test did not release launch")
            return child

        with (patch("adapter.subprocess.Popen", side_effect=launch) as popen,
              ThreadPoolExecutor(max_workers=1) as executor):
            started = executor.submit(self.adapter.start)
            self.assertTrue(entered.wait(1))
            self.adapter.stop(timeout=0.01)
            release.set()
            self.assertFalse(started.result(timeout=2))
        self.assertTrue(child.stdin.closed and child.stdout.closed)
        self.assertIsNone(self.adapter.process)
        self.assertEqual(popen.call_count, 1)

    def test_start_failure_can_be_followed_by_a_new_start(self):
        child = ScriptedProcess([self.ready, self.quit])
        with patch("adapter.subprocess.Popen", side_effect=[OSError("cannot launch"), child]) as launch:
            with self.assertRaisesRegex(OSError, "cannot launch"):
                self.adapter.start()
            self.adapter.stop()
            self.assertTrue(self.adapter.start())
            self.wait_for(lambda: child.stdout.closed)
            self.adapter.stop()
        self.assertEqual(launch.call_count, 2)

    def test_start_timeout_stops_the_late_child(self):
        release = threading.Event()
        self.addCleanup(release.set)
        child = ScriptedProcess([self.ready], running=True)

        def launch(*args, **kwargs):
            if not release.wait(2):
                raise RuntimeError("test did not release launch")
            return child

        with patch("adapter.subprocess.Popen", side_effect=launch) as popen:
            with self.assertRaisesRegex(TimeoutError, "launching the server child"):
                self.adapter.start(timeout=0.02)
            release.set()
            self.wait_for(lambda: child.stdout.closed)
            self.adapter.stop()
        self.assertEqual(popen.call_count, 1)
        self.assertIsNone(self.adapter.process)

    def test_concurrent_start_waits_for_the_same_startup_result(self):
        entered, release = threading.Event(), threading.Event()
        child = ScriptedProcess([self.ready, self.quit])
        self.addCleanup(release.set)

        def launch(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test did not release launch")
            return child

        with (patch("adapter.subprocess.Popen", side_effect=launch) as popen,
              ThreadPoolExecutor(max_workers=2) as executor):
            first = executor.submit(self.adapter.start)
            self.assertTrue(entered.wait(1))
            second = executor.submit(self.adapter.start)
            try:
                with self.assertRaises(TimeoutError):
                    second.result(timeout=0.02)
            finally:
                release.set()
            self.assertTrue(first.result(timeout=2))
            self.assertTrue(second.result(timeout=2))
            self.wait_for(lambda: child.stdout.closed)
            self.adapter.stop()
        self.assertEqual(popen.call_count, 1)


class ServerLifecycleTests(unittest.TestCase):
    def test_runtime_stops_its_http_server_and_releases_owned_resources(self):
        conversation = Mock()
        http_server = Mock(should_exit=False)
        listener = Mock()
        bridge_input = io.BytesIO()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TEMP": directory}):
            runtime = server.ServerRuntime(server.app)
            lockfile = Path(directory) / "FusionHeadless.lock"

            def serve(handler):
                self.assertEqual(lockfile.read_text(), str(os.getpid()))
                self.assertFalse(http_server.should_exit)
                runtime.request_restart()
                runtime.complete_restart()
                self.assertTrue(http_server.should_exit)

            conversation.serve_forever.side_effect = serve
            with (patch("server.os.dup", return_value=100),
                  patch("server.os.dup2"),
                  patch("server.os.fdopen", return_value=bridge_input),
                  patch("server.FramedConnection"),
                  patch("server.ProcessConversation", return_value=conversation),
                  patch("server.socket.socket", return_value=listener),
                  patch("server.uvicorn.Config"),
                  patch("server.uvicorn.Server", return_value=http_server)):
                self.assertEqual(runtime.run(5000), 0)
            self.assertFalse(lockfile.exists())
        self.assertTrue(bridge_input.closed)
        listener.close.assert_called_once()
        http_server.run.assert_called_once_with(sockets=[listener])
        conversation.close.assert_called_once_with("requested replacement")
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            runtime.execute_fusion("return 1")

    def test_port_conflict_releases_listener_without_removing_another_lock(self):
        listener = Mock()
        listener.bind.side_effect = OSError("port owned")
        bridge_input = io.BytesIO()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TEMP": directory}):
            lockfile = Path(directory) / "FusionHeadless.lock"
            lockfile.write_text("another child")
            runtime = server.ServerRuntime(server.app)
            with (patch("server.os.dup", return_value=100),
                  patch("server.os.dup2"),
                  patch("server.os.fdopen", return_value=bridge_input),
                  patch("server.FramedConnection") as bridge,
                  patch("server.ProcessConversation"),
                  patch("server.socket.socket", return_value=listener),
                  patch("server.uvicorn.Server") as http_server):
                self.assertEqual(runtime.run(5000), 0)
            self.assertEqual(lockfile.read_text(), "another child")
        self.assertTrue(bridge_input.closed)
        listener.close.assert_called_once()
        http_server.assert_not_called()
        bridge.return_value.write.assert_called_once_with({"command": "quit", "reason": "port already owned"})

    def test_restart_response_precedes_close_and_rejected_reset_still_exits(self):
        for failure in (None, RemoteConversationError("bad import", "FusionResetError")):
            with self.subTest(failure=failure):
                conversation = Mock()
                conversation.restart.side_effect = failure
                runtime = server.ServerRuntime(server.app, conversation)
                background = BackgroundTasks()
                with patch.object(server, "_runtime", runtime):
                    response = asyncio.run(server.restart(background, server.RestartRequest(show_terminal=True)))
                conversation.restart.assert_called_once_with("restart", show_terminal=True)
                conversation.close.assert_not_called()
                self.assertTrue(runtime.restarting)
                if failure is None:
                    self.assertEqual(response, {"status": "ok", "result": {"server": "Restarting.."}})
                else:
                    self.assertEqual(response.status_code, 500)
                asyncio.run(background())
                conversation.close.assert_called_once_with("requested replacement")

    def test_failed_restart_reopens_admission_and_does_not_close(self):
        conversation = Mock()
        conversation.restart.side_effect = RuntimeError("bridge unavailable")
        runtime = server.ServerRuntime(server.app, conversation)
        background = BackgroundTasks()
        with patch.object(server, "_runtime", runtime):
            response = asyncio.run(server.restart(background))
        self.assertEqual(response.status_code, 500)
        self.assertFalse(runtime.restarting)
        asyncio.run(background())
        conversation.close.assert_not_called()

    def test_runtime_requires_a_connection_and_preserves_syntax_errors(self):
        runtime = server.ServerRuntime(server.app)
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            runtime.execute_fusion("return 1")
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            runtime.request_restart()
        self.assertFalse(runtime.restarting)
        conversation = Mock()
        conversation.execute_fusion.side_effect = RemoteConversationError("invalid code", "SyntaxError")
        with self.assertRaisesRegex(SyntaxError, "invalid code"):
            server.ServerRuntime(server.app, conversation).execute_fusion("invalid code")


if __name__ == "__main__":
    unittest.main()
