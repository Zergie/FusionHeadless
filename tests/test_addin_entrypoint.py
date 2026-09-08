from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from tests.test_stl_export_command import NativeUI


ROOT = Path(__file__).resolve().parents[1]


class FakeApplication:
    def __init__(self) -> None:
        self.userInterface = FakeUi()


class FakeUi(NativeUI):
    def __init__(self) -> None:
        super().__init__([], Path("unused.stl"))

    def messageBox(self, message: str) -> None:
        self.messages.append(message)


class FakeHost:
    instances: list["FakeHost"] = []

    def __init__(self, app, adsk) -> None:
        self.app = app
        self.adsk = adsk
        self.started = False
        self.closed = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def dispatch(self, callback, *args, **kwargs):
        return callback(*args, **kwargs)

    def context(self):
        return {"app": self.app, "ui": self.app.userInterface, "adsk": self.adsk}


class FakeAdapter:
    instances: list["FakeAdapter"] = []

    def __init__(self, host) -> None:
        self.host = host
        self.started = 0
        self.stop_requests = []
        self.start_result = True
        self.port = 5000
        self.__class__.instances.append(self)

    def start(self) -> bool:
        self.started += 1
        return self.start_result

    def stop_from_ui_thread(self) -> None:
        self.stop_requests.append("ui-thread")


class ImmediateThread:
    def __init__(self, *, target, args=(), daemon) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self) -> None:
        self.target(*self.args)


class AddinEntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeHost.instances = []
        FakeAdapter.instances = []
        self.app = FakeApplication()
        self.adsk = types.ModuleType("adsk")
        core = types.ModuleType("adsk.core")
        core.Application = type("Application", (), {"get": staticmethod(lambda: self.app)})
        core.CommandCreatedEventHandler = object
        self.adsk.core = core
        self.adsk.fusion = types.ModuleType("adsk.fusion")

    def load_entrypoint(self):
        with patch.dict(sys.modules, {"adsk": self.adsk, "adsk.core": self.adsk.core,
                                     "adsk.fusion": self.adsk.fusion}):
            spec = importlib.util.spec_from_file_location("test_fusion_addin", ROOT / "FusionHeadless.py")
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
        module.FusionHost = FakeHost
        module.FusionAdapter = FakeAdapter
        module.Thread = ImmediateThread
        return module

    def test_manifest_declares_legacy_startup_entrypoint(self) -> None:
        manifest = json.loads((ROOT / "FusionHeadless.manifest").read_text(encoding="utf-8"))

        self.assertEqual(manifest["id"], "FusionHeadless")
        self.assertEqual(manifest["entry"], "FusionHeadless.py")
        self.assertTrue(manifest["runOnStartup"])

    def test_run_is_idempotent_and_stop_releases_the_host(self) -> None:
        entrypoint = self.load_entrypoint()

        entrypoint.run({})
        entrypoint.run({})
        entrypoint.stop({})

        self.assertEqual(len(FakeHost.instances), 1)
        self.assertTrue(FakeHost.instances[0].started)
        self.assertTrue(FakeHost.instances[0].closed)
        self.assertEqual(FakeAdapter.instances[0].started, 1)
        self.assertEqual(FakeAdapter.instances[0].stop_requests, ["ui-thread"])
        self.assertEqual(self.app.userInterface.definition.commandCreated.handlers, [])
        self.assertFalse(self.app.userInterface.definition.deleted)
        self.assertFalse(self.app.userInterface.control.deleted)

    def test_failed_background_start_shows_only_setup_guidance(self) -> None:
        entrypoint = self.load_entrypoint()

        def create_failing_adapter(host):
            adapter = FakeAdapter(host)
            adapter.start_result = False
            return adapter

        entrypoint.FusionAdapter = create_failing_adapter
        self.addCleanup(entrypoint.stop, {})
        entrypoint.run({})

        self.assertEqual(len(self.app.userInterface.messages), 1)
        self.assertEqual(
            self.app.userInterface.messages[0],
            "FusionHeadless setup is incomplete. Complete setup and see README.md.",
        )


if __name__ == "__main__":
    unittest.main()
