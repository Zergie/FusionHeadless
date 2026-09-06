from __future__ import annotations

import json
import math
import os
import socket
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from adapter import FusionAdapter
import fusion_routes
from tests.harness import FakeFusionHost, route_path


class ExportOptions:
    def __init__(self, filename: str) -> None:
        self.filename = filename


class ExportManager:
    def __init__(self) -> None:
        self.format = None

    def _options(self, format_name: str, path: str) -> ExportOptions:
        self.format = format_name
        self.last_options = ExportOptions(path)
        return self.last_options

    def createSTEPExportOptions(self, path, design):
        return self._options("step", path)

    def createSTLExportOptions(self, design, path):
        return self._options("stl", path)

    def createFusionArchiveExportOptions(self, path, design):
        return self._options("f3d", path)

    def createC3MFExportOptions(self, design, path):
        return self._options("3mf", path)

    def createOBJExportOptions(self, design, path):
        return self._options("obj", path)

    def execute(self, options):
        with open(options.filename, "wb") as output:
            output.write(b"\x00Fusion\n" + self.format.encode() + bytes(range(256)))
        return True


class BinaryAdsk:
    class core:
        class CameraTypes:
            PerspectiveCameraType = "perspective"

        class SaveImageFileOptions:
            @staticmethod
            def create(path):
                options = type("Options", (), {})()
                options.path = path
                return options

    class fusion:
        class RenderAspectRatios:
            CustomRenderAspectRatio = "custom-aspect"

        class RenderResolutions:
            CustomRenderResolution = "custom-resolution"


class SelectableItem:
    def __init__(self, owner, index, selected=False):
        self.owner = owner
        self.index = index
        self._selected = selected

    @property
    def isSelected(self):
        return self._selected

    @isSelected.setter
    def isSelected(self, value):
        if value and self.owner.exclusive:
            for item in self.owner.items:
                item._selected = False
        self._selected = bool(value)


class SelectableItems:
    def __init__(self, selected, *, exclusive=False):
        self.exclusive = exclusive
        self.items = [SelectableItem(self, index, value)
                      for index, value in enumerate(selected)]

    @property
    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]

    def selected(self):
        return [item.isSelected for item in self.items]


class ControlDefinition:
    def __init__(self, selected, *, exclusive=False):
        self.listItems = SelectableItems(selected, exclusive=exclusive)


class CommandDefinitions:
    def __init__(self):
        self.controls = {
            "ViewCameraCommand": ControlDefinition([True, False], exclusive=True),
            "VisibilityOverrideCommand": ControlDefinition([True, False]),
        }

    def itemById(self, identity):
        return type("Command", (), {"controlDefinition": self.controls[identity]})()


class BinarySelections(list):
    def __init__(self):
        super().__init__(["selected"])
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1
        super().clear()


class BinaryUI:
    def __init__(self):
        self.activeSelections = BinarySelections()
        self.commandDefinitions = CommandDefinitions()


class FakeVector:
    def __init__(self):
        self.scale = None

    def normalize(self):
        return True

    def scaleBy(self, value):
        self.scale = value


class FakePoint:
    def __init__(self):
        self.vector = FakeVector()
        self.translation = None

    def vectorTo(self, other):
        return self.vector

    def distanceTo(self, other):
        return 10.0

    def copy(self):
        return FakePoint()

    def translateBy(self, vector):
        self.translation = vector


class FakeCamera:
    def __init__(self):
        self.eye = FakePoint()
        self.target = FakePoint()
        self.upVector = object()
        self.perspectiveAngle = 0.5
        self.isSmoothTransition = True
        self.cameraType = "orthographic"


class FakeNamedView:
    def __init__(self):
        self.apply_calls = 0

    def apply(self):
        self.apply_calls += 1


class FakeNamedViews:
    def __init__(self):
        self.requested = None
        self.view = FakeNamedView()

    def itemByName(self, name):
        self.requested = name
        return self.view


class FakeRendering:
    def __init__(self):
        self.started_with = None

    def startLocalRender(self, path, camera):
        self.started_with = camera
        with open(path, "wb") as output:
            output.write(b"\x89PNG\r\n\x1a\n\x00rendered")


class FakeRenderManager:
    def __init__(self):
        self.sceneSettings = type("Scene", (), {
            "cameraType": "orthographic",
            "cameraExposure": 0.0,
        })()
        self.rendering = FakeRendering()


class FakeViewport:
    def __init__(self, save_image):
        self.visualStyle = "old"
        self.camera = FakeCamera()
        self.refresh_calls = 0
        self.home_calls = 0
        self.fit_calls = 0
        self.saveAsImageFileWithOptions = save_image

    def refresh(self):
        self.refresh_calls += 1

    def goHome(self):
        self.home_calls += 1

    def fit(self):
        self.fit_calls += 1


class BinaryHost(FakeFusionHost):
    def __init__(self):
        super().__init__()
        self.ui = BinaryUI()
        root = type("Root", (), {"bRepBodies": [], "allOccurrences": []})()
        product = type("Product", (), {
            "rootComponent": root,
            "exportManager": ExportManager(),
            "renderManager": FakeRenderManager(),
        })()
        viewport = FakeViewport(self._save_image)
        self.app.activeProduct = product
        self.app.activeViewport = viewport
        self.app.activeDocument = type("Document", (), {
            "design": type("Design", (), {"namedViews": FakeNamedViews()})(),
        })()
        self._adsk = BinaryAdsk()
        self.image_options = None
        self.do_events_calls = 0

        def do_events():
            self.do_events_calls += 1

        self._adsk.doEvents = do_events

    def _save_image(self, options):
        self.image_options = options
        with open(options.path, "wb") as output:
            output.write(b"\x89PNG\r\n\x1a\n\x00exact")

    def context(self):
        return {"app": self.app, "ui": self.ui, "adsk": self._adsk}


class BinaryRouteTests(unittest.TestCase):
    def setUp(self):
        self.host = BinaryHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.adapter = FusionAdapter(host=self.host, port=self.port)
        self.assertTrue(self.adapter.start(timeout=5))
        self.addCleanup(self.adapter.stop)

    def request(self, path, values):
        request = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(values).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()

    def test_export_is_raw_binary_with_legacy_content_type_and_filename(self):
        manager = self.host.app.activeProduct.exportManager
        for format_name in ("f3d", "step", "stl", "3mf", "obj"):
            with self.subTest(format=format_name):
                status, headers, body = self.request(
                    route_path(fusion_routes.export_route), {"format": format_name}
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers["content-type"], "application/octet-stream")
                self.assertEqual(headers["content-disposition"],
                                 f'attachment; filename="export.{format_name}"')
                self.assertEqual(body, b"\x00Fusion\n" + format_name.encode() + bytes(range(256)))
                self.assertEqual(manager.format, format_name)
                self.assertFalse(os.path.exists(manager.last_options.filename))

    def test_failed_exports_reject_partial_files_and_clean_up(self):
        manager = self.host.app.activeProduct.exportManager
        for format_name in ("f3d", "step", "stl", "3mf", "obj"):
            for failure in ("false", "exception", "no-file"):
                with self.subTest(format=format_name, failure=failure):
                    def fail(options):
                        if failure != "no-file":
                            with open(options.filename, "wb") as output:
                                output.write(b"partial export")
                        if failure == "exception":
                            raise RuntimeError("export interrupted")
                        return False

                    manager.execute = fail
                    with self.assertRaises(HTTPError) as caught:
                        self.request(route_path(fusion_routes.export_route), {"format": format_name})
                    with caught.exception as response:
                        self.assertEqual(response.code, 500)
                        error = json.load(response)["error"]
                    self.assertIn(f"Fusion failed to export {format_name}", error)
                    if failure == "exception":
                        self.assertIn("export interrupted", error)
                    self.assertFalse(os.path.exists(manager.last_options.filename))

    def test_normal_exports_restore_bodies_and_occurrences_on_every_exit(self):
        product = self.host.app.activeProduct
        manager = product.exportManager
        root_body = SimpleNamespace(name="Root body", isLightBulbOn=False)
        bodies = [SimpleNamespace(name=name, isLightBulbOn=state)
                  for name, state in [("First", False), ("Second", True), ("Other", True)]]
        component = SimpleNamespace(name="Part", id="part-id", bRepBodies=bodies)
        # Repeated occurrences expose the same native bodies more than once.
        occurrences = [SimpleNamespace(component=component, isLightBulbOn=state)
                       for state in (False, True)]
        product.rootComponent.bRepBodies = [root_body]
        product.rootComponent.allOccurrences = occurrences
        items = [root_body, *bodies, *occurrences]
        initial = [item.isLightBulbOn for item in items]
        execute = manager.execute
        for format_name in ("f3d", "step", "stl", "3mf", "obj"):
            for failure in (None, "options", "false", "exception", "read"):
                with self.subTest(format=format_name, failure=failure):
                    def export(options):
                        self.assertEqual([item.isLightBulbOn for item in items],
                                         [True, True, True, False, True, True])
                        if failure == "read":
                            return True  # Successful Fusion call with no output file.
                        execute(options)
                        if failure == "exception":
                            raise RuntimeError("export interrupted")
                        return failure != "false"

                    def fail_options(*args):
                        self.assertTrue(root_body.isLightBulbOn)
                        raise RuntimeError("cannot create export options")

                    with patch.object(manager, "execute", side_effect=export):
                        with patch.object(manager, "_options", wraps=manager._options) as options:
                            if failure == "options":
                                options.side_effect = fail_options
                            values = {"format": format_name, "component": "part-id",
                                      "body": ["First", "Second"]}
                            if failure is None:
                                self.assertEqual(self.request(route_path(fusion_routes.export_route), values)[0], 200)
                            else:
                                with self.assertRaises(HTTPError) as caught:
                                    self.request(route_path(fusion_routes.export_route), values)
                                with caught.exception as response:
                                    self.assertEqual(response.code, 500)
                    self.assertEqual([item.isLightBulbOn for item in items], initial)
                    if failure != "options":
                        self.assertFalse(os.path.exists(manager.last_options.filename))

    def test_export_selection_is_validated_before_visibility_changes(self):
        class UntouchedBody:
            name = "Visible"
            @property
            def isLightBulbOn(self):
                return False
            @isLightBulbOn.setter
            def isLightBulbOn(self, value):
                raise AssertionError("invalid selection must not change visibility")

        root = self.host.app.activeProduct.rootComponent
        root.name = "Root"
        root.bRepBodies = [UntouchedBody()]
        for selector in ({"component": "Unknown"}, {"body": ["Missing"]},
                         {"body": ["Visible", "Missing"]}):
            with self.subTest(selector=selector):
                with self.assertRaises(HTTPError) as caught:
                    self.request(route_path(fusion_routes.export_route), selector)
                with caught.exception as response:
                    self.assertEqual(response.code, 500)
                    error = json.load(response)["error"]
                self.assertIn("not found", error)
                if "body" in selector:
                    self.assertIn("Root", error)
                    self.assertIn("Missing", error)

    def test_render_is_exact_png_and_applies_dimensions(self):
        status, headers, body = self.request(route_path(fusion_routes.render_route), {
            "quality": "ShadedWithVisibleEdgesOnly", "width": 320, "height": 200,
        })
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "image/png")
        self.assertEqual(headers["content-disposition"], 'inline; filename="render.png"')
        self.assertEqual(body, b"\x89PNG\r\n\x1a\n\x00exact")
        self.assertEqual((self.host.image_options.width, self.host.image_options.height), (320, 200))

    def test_render_applies_visual_style_during_capture_and_restores_it(self):
        viewport = self.host.app.activeViewport
        styles = (
            "Shaded", "ShadedWithHiddenEdges", "ShadedWithVisibleEdgesOnly",
            "Wireframe", "WireframeWithHiddenEdges", "WireframeWithVisibleEdgesOnly",
        )
        for expected, quality in enumerate(styles):
            for fail_capture in (False, True):
                with self.subTest(quality=quality, fail_capture=fail_capture):
                    captured_styles = []

                    def capture(options):
                        captured_styles.append(viewport.visualStyle)
                        if fail_capture:
                            raise RuntimeError("capture failed")
                        self.host._save_image(options)

                    with patch.object(viewport, "saveAsImageFileWithOptions", side_effect=capture):
                        if fail_capture:
                            with self.assertRaises(HTTPError) as caught:
                                self.request(route_path(fusion_routes.render_route), {"quality": quality})
                            with caught.exception as response:
                                self.assertEqual(response.code, 500)
                                self.assertIn("capture failed", json.load(response)["error"])
                        else:
                            status, _, _ = self.request(
                                route_path(fusion_routes.render_route), {"quality": quality},
                            )
                            self.assertEqual(status, 200)
                    self.assertEqual(captured_styles, [expected])
                    self.assertEqual(viewport.visualStyle, "old")

    def test_render_applies_named_view_focal_length_and_restores_controls(self):
        camera_control = self.host.ui.commandDefinitions.controls["ViewCameraCommand"]
        visibility_control = self.host.ui.commandDefinitions.controls["VisibilityOverrideCommand"]

        status, _, _ = self.request(route_path(fusion_routes.render_route), {
            "quality": "ShadedWithVisibleEdgesOnly",
            "view": "Render_1",
            "focalLength": 100,
        })

        viewport = self.host.app.activeViewport
        named_views = self.host.app.activeDocument.design.namedViews
        self.assertEqual(status, 200)
        self.assertEqual(named_views.requested, "Render_1")
        self.assertEqual(named_views.view.apply_calls, 1)
        self.assertEqual(viewport.camera.cameraType, "perspective")
        self.assertAlmostEqual(
            viewport.camera.perspectiveAngle,
            2.0 * math.atan(12.0 / 100.0),
        )
        self.assertEqual(viewport.refresh_calls, 1)
        self.assertGreaterEqual(self.host.ui.activeSelections.clear_calls, 1)
        self.assertEqual(camera_control.listItems.selected(), [True, False])
        self.assertEqual(visibility_control.listItems.selected(), [True, False])

    def test_render_applies_local_render_exposure_and_custom_resolution(self):
        status, _, body = self.request(route_path(fusion_routes.render_route), {
            "quality": 50,
            "exposure": 8.2,
            "width": 640,
            "height": 480,
        })

        manager = self.host.app.activeProduct.renderManager
        rendering = manager.rendering
        self.assertEqual(status, 200)
        self.assertEqual(body, b"\x89PNG\r\n\x1a\n\x00rendered")
        self.assertEqual(manager.sceneSettings.cameraExposure, 8.2)
        self.assertEqual(rendering.aspectRatio, "custom-aspect")
        self.assertEqual(rendering.resolution, "custom-resolution")
        self.assertEqual((rendering.resolutionWidth, rendering.resolutionHeight), (640, 480))
        self.assertIs(rendering.started_with, self.host.app.activeViewport.camera)

    def test_render_normalizes_occurrence_names_and_reveals_isolated_children(self):
        child = type("Child", (), {"isVisible": False, "isLightBulbOn": False})()
        component = type("Component", (), {"bRepBodies": []})()
        occurrence = type("Occurrence", (), {
            "name": "Direct Drive x4 v12:1",
            "component": component,
            "bRepBodies": [],
            "childOccurrences": [child],
            "isVisible": True,
            "isLightBulbOn": False,
            "isIsolated": False,
        })()
        self.host.app.activeProduct.rootComponent.allOccurrences = [occurrence]

        status, _, _ = self.request(route_path(fusion_routes.render_route), {
            "quality": "ShadedWithVisibleEdgesOnly",
            "isolate": ["Direct Drive x4"],
        })

        self.assertEqual(status, 200)
        self.assertTrue(occurrence.isIsolated)
        self.assertTrue(occurrence.isLightBulbOn)
        self.assertTrue(child.isLightBulbOn)

    def test_render_keeps_explicitly_hidden_children_out_of_isolation(self):
        class Occurrence:
            def __init__(self, name, children=()):
                self.name = name
                self.component = type("Component", (), {"bRepBodies": []})()
                self.bRepBodies = []
                self.childOccurrences = list(children)
                self.isLightBulbOn = False
                self.isIsolated = False

            @property
            def isVisible(self):
                return self.isLightBulbOn

        excluded = Occurrence("Filament Spools:1")
        included = Occurrence("Feeder:1")
        parent = Occurrence("Direct Drive x4 v12:1", [excluded, included])
        self.host.app.activeProduct.rootComponent.allOccurrences = [
            parent, excluded, included,
        ]

        values = {
            "show": ["all"],
            "isolate": ["Direct Drive x4"],
            "hide": ["Filament Spools"],
        }
        for request_values in (values, dict(reversed(list(values.items())))):
            with self.subTest(request_order=list(request_values)):
                status, _, _ = self.request(
                    route_path(fusion_routes.render_route), request_values,
                )

                self.assertEqual(status, 200)
                self.assertTrue(parent.isIsolated)
                self.assertTrue(parent.isLightBulbOn)
                self.assertTrue(included.isLightBulbOn)
                self.assertFalse(excluded.isLightBulbOn)

    def test_unsupported_export_format_returns_json_error(self):
        request = Request(
            f"http://127.0.0.1:{self.port}{route_path(fusion_routes.export_route)}",
            data=b'{"format":"pdf"}',
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 422)
        payload = json.loads(raised.exception.read())
        self.assertEqual(payload["detail"][0]["loc"], ["body", "format"])


if __name__ == "__main__":
    unittest.main()
