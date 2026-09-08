from __future__ import annotations

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

from adapter import FusionAdapter
from cli import fusion_cli
from context import FusionContext, server_callback_scope
import routes
import server
from tests.harness import route_path
from tests.test_binary_routes import BinaryHost, ExportOptions
from tests.test_stl_orientation import box_stl, read_stl


def body(name, *, reversed_normal=False):
    plane = SimpleNamespace(
        normal=SimpleNamespace(asArray=lambda: [0, 0, 1 if reversed_normal else -1]),
        origin=SimpleNamespace(asArray=lambda: [1, 2, 3]),
    )
    return SimpleNamespace(name=name, isLightBulbOn=False, faces=[SimpleNamespace(
        appearance=SimpleNamespace(name="Build Plate"), geometry=plane,
        isParamReversed=reversed_normal)])


class OrientedExportTests(unittest.TestCase):
    def setUp(self):
        self.host = BinaryHost()
        # Real Fusion dispatches synchronously to a different thread. Running
        # callbacks on the bridge reader itself hides reverse-call deadlocks.
        ui_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fake-fusion-ui")
        self.addCleanup(ui_thread.shutdown)
        self.host.dispatch = lambda callback, *args, **kwargs: ui_thread.submit(callback, *args, **kwargs).result(timeout=3)
        self.root = self.host.app.activeProduct.rootComponent
        self.root.name = "Root"
        self.root.bRepBodies = [body("Plate", reversed_normal=True), body("Cover")]
        self.root.occurrences = []
        self.host._adsk.core.Plane = SimpleNamespace(cast=lambda geometry: geometry)
        self.host._adsk.fusion.DistanceUnits = SimpleNamespace(MillimeterDistanceUnits=0)
        self.options = []
        self.geometry = []
        self.states = []

        def options(geometry, path):
            result = ExportOptions(path)
            self.options.append(result)
            self.geometry.append(geometry)
            return result

        def execute(options):
            self.states.append([item.isLightBulbOn for item in self.root.bRepBodies])
            with open(options.filename, "wb") as output:
                output.write(box_stl([10, 20, 30]))
            return True

        manager = self.host.app.activeProduct.exportManager
        manager.createSTLExportOptions = options
        manager.execute = execute
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.adapter = FusionAdapter(host=self.host, port=port)
        self.assertTrue(self.adapter.start(timeout=5))
        self.addCleanup(self.adapter.stop)
        self.url = f"http://127.0.0.1:{port}{route_path(routes.export_route)}"

    def request(self, **values):
        request = Request(self.url, data=json.dumps({"format": "stl", **values}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_option_is_discovered_by_cli(self):
        commands = fusion_cli.commands_from_openapi(server.app.openapi())
        parser = fusion_cli.build_parser(commands)
        args = parser.parse_args(["export", "--format", "stl", "--body", "Plate"])
        self.assertEqual(fusion_cli._arguments_for_command(args, commands["export"]),
                         {"format": "stl", "body": ["Plate"]})
        args = parser.parse_args(["export", "--format", "stl", "--orient", "Print Bed"])
        self.assertEqual(fusion_cli._arguments_for_command(args, commands["export"]),
                         {"format": "stl", "orient": "Print Bed"})
        args = parser.parse_args(["export", "--format", "stl", "--data", '{"orient":null}'])
        self.assertEqual(fusion_cli._arguments_for_command(args, commands["export"]),
                         {"format": "stl", "orient": None})
        self.assertNotIn("build_plate_appearance", [option.wire_name for option in commands["export"].options])
        definition = next(item for item in fusion_cli.powershell_parameters(server.app.openapi(), "export")
                          if item["name"] == "Orient")
        self.assertEqual(definition["kind"], "string")
        self.assertNotIn("falseFlag", definition)

    def test_booleans_are_rejected_and_omitted_or_null_preserves_original_stl(self):
        for value in (True, False):
            status, _, data = self.request(orient=value)
            self.assertEqual(status, 422, data)
        self.assertEqual(self.options, [])
        self.root.bRepBodies[0].faces = []
        for values in ({}, {"orient": None}):
            with self.subTest(values=values):
                status, _, data = self.request(**values)
                self.assertEqual(status, 200, data)
                np.testing.assert_allclose(read_stl(data).vectors.min(axis=(0, 1)), [10, 20, 30])

    def test_other_formats_ignore_orientation_and_use_original_export(self):
        status, _, data = self.request(format="step", orient="Print Bed")
        self.assertEqual(status, 200, data)
        self.assertEqual(self.host.app.activeProduct.exportManager.format, "step")
        self.assertEqual(self.options, [])

    def test_custom_appearance_uses_case_sensitive_substring_matching(self):
        self.root.bRepBodies[0].faces[0].appearance.name = "Print Bed Blue"
        status, _, data = self.request(body=["Plate"], orient="Print Bed")
        self.assertEqual(status, 200, data)
        np.testing.assert_allclose(read_stl(data).vectors.min(axis=(0, 1)), [-1, -1.5, 0])
        for values, expected_name in [({"orient": "Build Plate"}, "Build Plate"),
                                      ({"orient": "print bed"}, "print bed")]:
            status, _, data = self.request(body=["Plate"], **values)
            self.assertEqual(status, 500)
            self.assertIn(repr(expected_name), json.loads(data)["error"])

    def test_blank_appearance_is_rejected_before_export(self):
        for name in ("", " \t\n"):
            with self.subTest(name=name):
                status, _, data = self.request(body=["Plate"], orient=name)
                self.assertEqual(status, 500)
                self.assertIn("orient appearance name must not be", json.loads(data)["error"])
        self.assertEqual(self.options, [])

    def test_single_body_runs_mesh_processing_in_child_and_converts_cm_to_mm(self):
        with patch("stl_orientation.orient_stl", side_effect=AssertionError("must run in child")):
            status, headers, data = self.request(body=["Plate"], orient="Build Plate")
        self.assertEqual(status, 200, data)
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        model = read_stl(data)
        np.testing.assert_allclose(model.vectors.min(axis=(0, 1)), [-1, -1.5, 0])
        np.testing.assert_allclose(model.vectors.max(axis=(0, 1)), [1, 1.5, 4])
        self.assertIs(self.geometry[0], self.root.bRepBodies[0])
        self.assertTrue(self.options[0].isBinaryFormat)
        self.assertEqual(self.options[0].unitType, 0)
        self.assertFalse(os.path.exists(self.options[0].filename))
        self.assertEqual([item.isLightBulbOn for item in self.root.bRepBodies], [False, False])

    def test_occurrence_proxy_uses_native_contact_plane_for_local_stl(self):
        native = self.root.bRepBodies[0]
        native.faces[0].geometry.normal.asArray = lambda: [0, 1, 0]
        native.faces[0].geometry.origin.asArray = lambda: [1, 2.3, 3]
        native.faces[0].isParamReversed = False
        native.nativeObject = None
        native.assemblyContext = None
        proxy_face = SimpleNamespace(
            appearance=native.faces[0].appearance,
            nativeObject=native.faces[0],
            geometry=SimpleNamespace(
                normal=SimpleNamespace(asArray=lambda: [0, 1, 0]),
                origin=SimpleNamespace(asArray=lambda: [1, 2.36, 3]),
            ),
            isParamReversed=False,
        )
        proxy = SimpleNamespace(
            name=native.name,
            faces=[proxy_face],
            parentComponent=self.root,
            nativeObject=native,
            assemblyContext=SimpleNamespace(fullPathName="Plate:1"),
        )
        self.host.app.activeProduct.findEntityByToken = lambda token: [proxy]

        status, _, data = self.request(
            body=["Plate"], entity_token="proxy-token", orient="Build Plate"
        )

        self.assertEqual(status, 200, data)
        model = read_stl(data)
        self.assertAlmostEqual(model.vectors.min(axis=(0, 1))[2], 0)

    def test_group_restores_visibility_on_success_and_processing_failure(self):
        self.root.bRepBodies.append(body("Unselected"))
        for normal, expected in [([0, 0, -1], 200), ([1, 0, 0], 500)]:
            self.root.bRepBodies[1].faces[0].geometry.normal.asArray = lambda: normal
            status, _, data = self.request(body=["Plate", "Cover"], orient="Build Plate")
            self.assertEqual(status, expected, data)
            self.assertEqual(self.states[-1], [True, True, False])
            self.assertEqual([item.isLightBulbOn for item in self.root.bRepBodies], [False] * 3)
            self.assertFalse(os.path.exists(self.options[-1].filename))

    def test_component_export_excludes_children_and_requires_an_explicit_group(self):
        child = SimpleNamespace(isLightBulbOn=True)
        self.root.id = "component-id"
        self.root.occurrences = [child]
        self.root.allOccurrences = [SimpleNamespace(component=self.root)]
        status, _, data = self.request(component="component-id", orient="Build Plate")
        self.assertEqual(status, 500)
        self.assertIn("explicit body names", json.loads(data)["error"])
        execute = self.host.app.activeProduct.exportManager.execute
        def check_child_hidden(options):
            self.assertFalse(child.isLightBulbOn)
            return execute(options)
        self.host.app.activeProduct.exportManager.execute = check_child_hidden
        status, _, data = self.request(component="Root", body=["Plate", "Cover"], orient="Build Plate")
        self.assertEqual(status, 200, data)
        self.assertTrue(child.isLightBulbOn)

    def test_failed_fusion_export_cleans_partial_file_and_restores_visibility(self):
        execute = self.host.app.activeProduct.exportManager.execute
        for failure in ("false", "exception"):
            with self.subTest(failure=failure):
                def fail(options):
                    execute(options)
                    if failure == "exception":
                        raise RuntimeError("export interrupted")
                    return False
                self.host.app.activeProduct.exportManager.execute = fail
                status, _, data = self.request(orient="Build Plate")
                self.assertEqual(status, 500)
                self.assertIn("Fusion failed to export oriented STL", json.loads(data)["error"])
                if failure == "exception":
                    self.assertIn("export interrupted", json.loads(data)["error"])
                self.assertEqual([item.isLightBulbOn for item in self.root.bRepBodies], [False, False])
                self.assertFalse(os.path.exists(self.options[-1].filename))

    def test_rejects_bad_selection_missing_or_nonplanar_markings(self):
        for values, message in [({"body": []}, "at least one"),
                                ({"body": ["Unknown"]}, "not found"),
                                ({"component": "Unknown"}, "not found")]:
            status, _, data = self.request(orient="Build Plate", **values)
            self.assertEqual(status, 500)
            self.assertIn(message, json.loads(data)["error"])
        self.root.bRepBodies[0].faces[0].appearance.name = "Steel"
        status, _, data = self.request(body=["Plate"], orient="Build Plate")
        self.assertEqual(status, 500)
        self.assertIn("no planar face marked", json.loads(data)["error"])
        self.root.bRepBodies[0].faces[0].appearance.name = "Build Plate"
        self.host._adsk.core.Plane.cast = lambda geometry: None
        status, _, data = self.request(body=["Plate"], orient="Build Plate")
        self.assertEqual(status, 500)
        self.assertIn("must be planar", json.loads(data)["error"])
        self.assertEqual(self.options, [])


class ServerCallbackContextTests(unittest.TestCase):
    def test_registration_is_required_and_scope_clears_after_failure(self):
        context = FusionContext(None, None, None)
        with self.assertRaisesRegex(ValueError, "Unregistered"):
            context.call_server(lambda: None)
        operation = routes.export._orient_export_file
        with self.assertRaisesRegex(RuntimeError, "active Fusion invocation"):
            context.call_server(operation, "path", [])
        def factory(name):
            self.assertEqual(name, operation.__name__)
            def fail(*args, **kwargs):
                raise ValueError("child rejected mesh")
            return fail
        with self.assertRaisesRegex(ValueError, "child rejected"):
            with server_callback_scope(factory):
                context.call_server(operation, "path", [])
        with self.assertRaisesRegex(RuntimeError, "active Fusion invocation"):
            context.call_server(operation, "path", [])


if __name__ == "__main__":
    unittest.main()
