from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest
from unittest.mock import patch

from adapter import FusionAdapter
from bridge import FrameProtocolError, FramedConnection
from context import fusion, registry, serialize_value, server as server_export
import routes
import server
from tests.harness import ChildProcessHarness, FakeFusionHost, route_path


class FragmentedStream(io.BytesIO):
    def __init__(self, data: bytes, chunk_size: int) -> None:
        super().__init__(data)
        self.chunk_size = chunk_size

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.chunk_size
        return super().read(min(size, self.chunk_size))


class FrameTests(unittest.TestCase):
    def decode(self, raw: bytes, chunk_size: int = 1):
        return FramedConnection(FragmentedStream(raw, chunk_size), io.BytesIO()).read()

    def encode(self, value):
        output = io.BytesIO()
        FramedConnection(io.BytesIO(), output).write(value)
        return output.getvalue()

    def test_json_uses_utf8_byte_length_and_round_trips_fragmented(self) -> None:
        value = {"message": "Grüße\n世界", "items": [1, True, None]}
        encoded = self.encode(value)
        payload = encoded.split(b":", 1)[1]
        self.assertEqual(encoded.split(b":", 1)[0], b"J" + str(len(payload)).encode())
        self.assertEqual(self.decode(encoded, 2), value)

    def test_top_level_binary_round_trips_without_conversion(self) -> None:
        value = b"\x00raw\n\xffbytes"
        encoded = self.encode(value)
        self.assertEqual(encoded, b"B11:" + value)
        self.assertEqual(self.decode(encoded), value)

    def test_invalid_frames_fail_clearly(self) -> None:
        cases = (b"X2:{}", b"Jtwo:{}", b"J5:{}", b"J2:\xff\xff")
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(FrameProtocolError):
                self.decode(raw)
        with self.assertRaises(TypeError, msg="nested bytes must not be JSON encoded"):
            self.encode({"not_allowed": b"bytes"})

    def test_clean_eof_before_a_frame_is_distinct(self) -> None:
        with self.assertRaises(EOFError):
            FramedConnection(io.BytesIO(), io.BytesIO()).read()

    def test_cycles_fail_before_writing_a_frame(self) -> None:
        cycle_list = []
        cycle_list.append(cycle_list)
        cycle_dict = {}
        cycle_dict["self"] = cycle_dict
        for value in (cycle_list, cycle_dict):
            with self.subTest(kind=type(value).__name__):
                output = io.BytesIO()
                with self.assertRaisesRegex(TypeError, "cyclic object graphs"):
                    FramedConnection(io.BytesIO(), output).write(value)
                self.assertEqual(output.getvalue(), b"")

    def test_serializer_rejects_nested_binary_in_values_and_keys(self) -> None:
        values = ([b"bytes"], {"data": bytearray(b"bytes")},
                  (memoryview(b"bytes"),), {b"key": 1}, {(b"key",): 1})
        for value in values:
            for encode in (serialize_value, self.encode):
                with self.subTest(value=value, encode=encode.__name__):
                    with self.assertRaisesRegex(TypeError, "top-level bridge payload"):
                        encode(value)

    def test_dictionary_keys_follow_json_contract(self) -> None:
        value = {"text": 1, 2: 2, 3.5: 3, False: 4, None: 5}
        self.assertEqual(serialize_value(value), value)
        self.assertEqual(self.decode(self.encode(value)),
                         {"text": 1, "2": 2, "3.5": 3, "false": 4, "null": 5})
        for encode in (serialize_value, self.encode):
            with self.subTest(encode=encode.__name__):
                with self.assertRaisesRegex(TypeError, "bridge dictionary keys"):
                    encode({("tuple",): 1})

    def test_decorated_instances_cross_by_value_without_reinitializing(self) -> None:
        constructor_calls: list[int] = []

        @fusion
        class Point:
            def __init__(self, x: int) -> None:
                constructor_calls.append(x)
                self.x = x
                self.meta = {"axes": ("x", "y")}

        original = Point(3)
        encoded = self.encode({"point": original, "items": [original], "pair": (1, 2)})
        copied = self.decode(encoded)

        self.assertEqual(constructor_calls, [3])
        self.assertIsInstance(copied["point"], Point)
        self.assertIsNot(copied["point"], original)
        self.assertEqual(copied["point"].__dict__, original.__dict__)
        self.assertIsInstance(copied["point"].meta["axes"], tuple)
        copied["point"].x = 9
        self.assertEqual(original.x, 3)

        copied_again = self.decode(self.encode(copied["point"]))
        self.assertEqual(copied_again.x, 9)

    def test_by_value_rejects_cycles_and_unregistered_types(self) -> None:
        cycle: list[object] = []
        cycle.append(cycle)
        with self.assertRaisesRegex(TypeError, "cyclic object graphs"):
            serialize_value(cycle)

        class NotDecorated:
            pass

        with self.assertRaisesRegex(TypeError, "unregistered custom type"):
            serialize_value(NotDecorated())


class ProcessHarnessTests(unittest.TestCase):
    def test_child_exits_after_handler_failure_with_input_still_open(self) -> None:
        child = ChildProcessHarness(["-m", "server", "--port", "0"])
        self.addCleanup(child.close)
        startup = child.read()
        self.assertEqual(startup["command"], "startup")
        child.write({"reply": True, "ok": True, "value": {"accepted": True}})
        startup = child.read()
        self.assertEqual(startup["command"], "exec")
        child.write({"reply": True, "ok": True, "value": {"installed": False}})
        self.assertEqual(child.read()["command"], "ready")
        child.write({"command": "invalid-command"})
        self.assertNotEqual(child.process.wait(timeout=4), 0)

    def test_real_child_exchanges_frames_and_fake_host_dispatches(self) -> None:
        child = ChildProcessHarness([
            "-c",
            "from bridge import FramedConnection; import sys; "
            "bridge = FramedConnection(sys.stdin.buffer, sys.stdout.buffer); "
            "message = bridge.read(); bridge.write({'echo': message}); "
            "message = bridge.read(); bridge.write(message)",
        ])
        self.addCleanup(child.close)
        child.write({"unicode": "ä"})
        self.assertEqual(child.read(), {"echo": {"unicode": "ä"}})
        child.write(b"\x00\xff")
        self.assertEqual(child.read(), b"\x00\xff")
        self.assertEqual(child.close(), 0)

        host = FakeFusionHost()
        self.assertEqual(host.dispatch(lambda value: value + 1, 41), 42)
        host.app.userInterface.messageBox("bridge failure")
        self.assertEqual(host.app.userInterface.message_boxes, ["bridge failure"])


class AdapterExecTests(unittest.TestCase):
    def test_scripts_lists_scripts_and_addins_and_changes_addin_state(self) -> None:
        addins = [
            SimpleNamespace(id="second", name="Zebra", isAddIn=True,
                            author="Zoe", description="Second add-in", folder="C:/AddIns/Zebra",
                            programmingLanguage=1, isRunOnStartup=False, isRunning=True),
            SimpleNamespace(id="first", name="Alpha", isAddIn=True,
                            author="Alice", description="First add-in", folder="C:/AddIns/Alpha",
                            programmingLanguage=0, isRunOnStartup=True, isRunning=False),
            SimpleNamespace(id="script", name="Not an add-in", isAddIn=False,
                            author="Sam", description="A script", folder="C:/Scripts/Example",
                            programmingLanguage=0, isRunOnStartup=False, isRunning=False),
        ]
        app = SimpleNamespace(
            version="2.0",
            applicationFolders=SimpleNamespace(),
            scripts=SimpleNamespace(count=len(addins), item=addins.__getitem__),
        )

        result = routes.scripts_route(SimpleNamespace(app=app))

        self.assertEqual(result, {
            "scripts": [
                {"id": "script", "name": "Not an add-in", "author": "Sam",
                 "description": "A script", "folder": "C:/Scripts/Example",
                 "programmingLanguage": "Prompt",
                 "enabled": False, "running": False},
            ],
            "addons": [
                {"id": "first", "name": "Alpha", "author": "Alice",
                 "description": "First add-in", "folder": "C:/AddIns/Alpha",
                 "programmingLanguage": "Prompt",
                 "enabled": True, "running": False},
                {"id": "second", "name": "Zebra", "author": "Zoe",
                 "description": "Second add-in", "folder": "C:/AddIns/Zebra",
                 "programmingLanguage": "Python",
                 "enabled": False, "running": True},
            ],
        })

        addins[0].stop = lambda: setattr(addins[0], "isRunning", False) or True
        addins[1].run = lambda wait: setattr(addins[1], "isRunning", True) or True
        result = routes.scripts_route(
            SimpleNamespace(app=app), enable=["first"], disable=["second"]
        )

        self.assertEqual(result, {
            "scripts": [
                {"id": "script", "name": "Not an add-in", "author": "Sam",
                 "description": "A script", "folder": "C:/Scripts/Example",
                 "programmingLanguage": "Prompt",
                 "enabled": False, "running": False},
            ],
            "addons": [
                {"id": "first", "name": "Alpha", "author": "Alice",
                 "description": "First add-in", "folder": "C:/AddIns/Alpha",
                 "programmingLanguage": "Prompt",
                 "enabled": True, "running": True},
                {"id": "second", "name": "Zebra", "author": "Zoe",
                 "description": "Second add-in", "folder": "C:/AddIns/Zebra",
                 "programmingLanguage": "Python",
                 "enabled": False, "running": False},
            ],
        })

    def test_scripts_rejects_conflicting_and_unknown_addin_ids(self) -> None:
        addin = SimpleNamespace(id="known", name="Known", isAddIn=True,
                                isRunOnStartup=False, isRunning=False)
        app = SimpleNamespace(scripts=SimpleNamespace(count=1, item=lambda _: addin))

        with self.assertRaisesRegex(ValueError, "both enabled and disabled"):
            routes.scripts_route(SimpleNamespace(app=app),
                                        enable=["known"], disable=["known"])
        with self.assertRaisesRegex(ValueError, "Unknown add-in Script ID"):
            routes.scripts_route(SimpleNamespace(app=app), enable=["missing"])

    def test_eval_preserves_expression_and_depth_contract(self) -> None:
        host = FakeFusionHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        adapter = FusionAdapter(host=host, port=port)
        self.assertTrue(adapter.start(timeout=5))
        self.addCleanup(adapter.stop)

        request = Request(
            f"http://127.0.0.1:{port}{route_path(routes.fusion_eval)}",
            data=b'{"code":"1 + 2"}',
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.read(), b'{"status":"ok","result":3}')

    def test_post_restart_replaces_child_and_resets_fusion_extensions(self) -> None:
        host = FakeFusionHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        adapter = FusionAdapter(host=host, port=port)
        self.assertTrue(adapter.start(timeout=5))
        self.addCleanup(adapter.stop)
        assert adapter.process is not None
        original_pid = adapter.process.pid
        original_route = routes.fusion_eval

        @fusion
        def runtime_registration(query, context):
            return "stale"

        request = Request(
            f"http://127.0.0.1:{port}{route_path(server.restart)}",
            data=b"",
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.read(), b'{"status":"ok","result":{"server":"Restarted"}}')

        self.assertIsNotNone(adapter.process)
        self.assertNotEqual(adapter.process.pid, original_pid)
        self.assertNotIn("runtime_registration", registry.fusion)
        self.assertIsNot(routes.fusion_eval, original_route)

        with urlopen(
            f"http://127.0.0.1:{port}{route_path(server.status)}", timeout=0.5
        ) as response:
            self.assertEqual(response.status, 200)

    def test_restart_can_replace_an_already_replaced_child(self) -> None:
        host = FakeFusionHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        adapter = FusionAdapter(host=host, port=port)
        self.assertTrue(adapter.start(timeout=5))
        self.addCleanup(adapter.stop)

        for _ in range(2):
            assert adapter.process is not None
            retiring_pid = adapter.process.pid
            request = Request(
                f"http://127.0.0.1:{port}{route_path(server.restart)}",
                data=b"",
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                self.assertEqual(
                    response.read(), b'{"status":"ok","result":{"server":"Restarted"}}'
                )
            assert adapter.process is not None
            self.assertNotEqual(adapter.process.pid, retiring_pid)
            with urlopen(
                f"http://127.0.0.1:{port}{route_path(server.status)}", timeout=0.5
            ) as response:
                self.assertEqual(response.status, 200)

    def test_exec_route_round_trips_return_value_through_real_child(self) -> None:
        host = FakeFusionHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        adapter = FusionAdapter(host=host, port=port)
        self.assertTrue(adapter.start(timeout=5))
        self.addCleanup(adapter.stop)
        host.app.dispatched.clear()

        request = Request(
            f"http://127.0.0.1:{port}{route_path(server.execute)}",
            data=json.dumps({
                "code": "return {'message': 'Grüße', 'value': 41 + 1}"
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), '{"message":"Grüße","value":42}'.encode())

        self.assertEqual(host.app.dispatched, [adapter._execute_code])

    def test_real_child_rejects_callback_reentry_and_accepts_the_next_request(self) -> None:
        @server_export
        def nested_fusion_probe():
            pass  # The real implementation is installed in the child below.

        self.addCleanup(registry.server.pop, nested_fusion_probe.__name__, None)
        host = FakeFusionHost()
        ui_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fake-fusion-ui")
        self.addCleanup(ui_thread.shutdown)
        host.dispatch = lambda callback, *args, **kwargs: ui_thread.submit(
            callback, *args, **kwargs
        ).result(timeout=3)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        adapter = FusionAdapter(host=host, port=port)
        self.addCleanup(adapter.stop)
        child_source = (
            "import server\n"
            "from context import server as server_export\n"
            "@server_export\n"
            "def nested_fusion_probe():\n"
            "    return server._fusion_call('return 99')\n"
            "server.main()\n"
        )
        popen = subprocess.Popen

        def launch(arguments, **options):
            return popen([arguments[0], "-c", child_source, "--port", str(port)], **options)

        with patch("adapter.subprocess.Popen", side_effect=launch):
            self.assertTrue(adapter.start(timeout=5))
        url = f"http://127.0.0.1:{port}{route_path(server.execute)}"
        request = Request(url, data=json.dumps({
            "code": "return nested_fusion_probe()",
        }).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        with caught.exception as response:
            self.assertEqual(response.code, 500)
            self.assertIn("Nested Fusion calls are not supported", json.load(response)["error"])
        request = Request(url, data=json.dumps({"code": "return 42"}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            self.assertEqual(json.load(response), 42)

    def test_restart_prompt_uses_retry_cancel_message_box(self) -> None:
        class DialogResults:
            RetryDialog = object()

        class MessageBoxButtonTypes:
            RetryCancelButtonType = object()

        class Ui:
            def messageBox(self, *args):
                self.arguments = args
                return DialogResults.RetryDialog

        ui = Ui()
        adsk = type("Adsk", (), {
            "core": type("Core", (), {
                "DialogResults": DialogResults,
                "MessageBoxButtonTypes": MessageBoxButtonTypes,
            }),
        })()

        self.assertTrue(FusionAdapter._show_restart_prompt({"ui": ui, "adsk": adsk}))
        self.assertEqual(ui.arguments[2], MessageBoxButtonTypes.RetryCancelButtonType)

    def test_exec_runs_code_with_fusion_context(self) -> None:
        host = FakeFusionHost()
        adapter = FusionAdapter(host=host)

        adapter._handle_exec({
            "command": "exec",
            "code": "app.marker = 42\nui.messageBox('executed')\nassert adsk is None",
        })

        self.assertEqual(host.app.marker, 42)
        self.assertEqual(host.app.userInterface.message_boxes, ["executed"])
        self.assertEqual(host.app.dispatched, [adapter._execute_code])

    def test_exec_rejects_non_schema_messages(self) -> None:
        with self.assertRaises(RuntimeError):
            FusionAdapter()._handle_exec({"command": "exec", "operation": "message_box"})

    def test_exec_requires_a_ui_thread_dispatcher(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "UI-thread dispatcher"):
            FusionAdapter()._handle_exec({"command": "exec", "code": "pass"})


if __name__ == "__main__":
    unittest.main()
