"""Failure contracts through export and render operations using the fake host."""

from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import routes
from tests.test_binary_routes import BinaryHost, SelectableItem


class TemporaryOperationTests(unittest.TestCase):
    def setUp(self):
        self.host = BinaryHost()
        self.context = SimpleNamespace(**self.host.context())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        location = patch("tempfile.gettempdir", return_value=directory.name)
        location.start()
        self.addCleanup(location.stop)

    def test_partial_exclusive_control_change_restores_original_selection(self):
        control = self.host.ui.commandDefinitions.controls["ViewCameraCommand"].listItems
        original_property = SelectableItem.isSelected
        failed = False

        def set_selected(item, value):
            nonlocal failed
            original_property.fset(item, value)
            if item is control.item(1) and value and not failed:
                failed = True
                raise RuntimeError("camera setter failed after changing selection")

        with patch.object(SelectableItem, "isSelected", property(original_property.fget, set_selected)):
            with self.assertRaisesRegex(RuntimeError, "camera setter failed"):
                routes.render_route(self.context, camera=1)
        self.assertTrue(failed)
        self.assertEqual(control.selected(), [True, False])
        self.assertEqual(self.host.app.activeViewport.visualStyle, "old")
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_failed_control_restore_does_not_skip_camera_style_or_file_cleanup(self):
        camera = self.host.ui.commandDefinitions.controls["ViewCameraCommand"].listItems
        visibility = self.host.ui.commandDefinitions.controls["VisibilityOverrideCommand"].listItems
        original_property = SelectableItem.isSelected
        save = self.host.app.activeViewport.saveAsImageFileWithOptions

        def fail_capture(options):
            save(options)
            raise RuntimeError("capture interrupted")

        def set_selected(item, value):
            if item is visibility.item(0) and value:
                raise RuntimeError("visibility restore rejected")
            original_property.fset(item, value)

        with (
            patch.object(SelectableItem, "isSelected", property(original_property.fget, set_selected)),
            patch.object(self.host.app.activeViewport, "saveAsImageFileWithOptions", side_effect=fail_capture),
        ):
            with self.assertRaises(RuntimeError) as caught:
                routes.render_route(self.context, focalLength=100)
        self.assertIn("capture interrupted", str(caught.exception))
        self.assertIn("visibility restore rejected", str(caught.exception))
        self.assertIn("VisibilityOverrideCommand", str(caught.exception))
        self.assertIn("capture interrupted", str(caught.exception.__cause__))
        self.assertEqual(camera.selected(), [True, False])
        self.assertEqual(self.host.app.activeViewport.visualStyle, "old")
        self.assertEqual(list(self.directory.iterdir()), [])
        # Camera changes are intentionally persistent, unlike control selections.
        self.assertEqual(self.host.app.activeViewport.camera.cameraType, "perspective")

    def test_cleanup_reports_multiple_failures_after_attempting_each(self):
        controls = self.host.ui.commandDefinitions.controls
        targets = [controls[name].listItems.item(0)
                   for name in ("ViewCameraCommand", "VisibilityOverrideCommand")]
        original_property = SelectableItem.isSelected
        attempts = []

        def set_selected(item, value):
            if item in targets and value:
                label = "camera restore" if item is targets[0] else "visibility restore"
                attempts.append(label)
                raise RuntimeError(label)
            original_property.fset(item, value)

        with patch.object(SelectableItem, "isSelected", property(original_property.fget, set_selected)):
            with self.assertRaises(RuntimeError) as caught:
                routes.render_route(self.context, camera=1)
        self.assertCountEqual(attempts, ["camera restore", "visibility restore"])
        self.assertIn("camera restore", str(caught.exception))
        self.assertIn("visibility restore", str(caught.exception))
        self.assertEqual(self.host.app.activeViewport.visualStyle, "old")
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_export_restore_failure_does_not_skip_other_bodies_or_file_cleanup(self):
        class Body:
            def __init__(self, name, fail_restore=False):
                self.name = name
                self._visible = False
                self.fail_restore = fail_restore
                self.restores = 0

            @property
            def isLightBulbOn(self):
                return self._visible

            @isLightBulbOn.setter
            def isLightBulbOn(self, value):
                if not value:
                    self.restores += 1
                    if self.fail_restore:
                        raise RuntimeError("body restore rejected")
                self._visible = value

        first, second = Body("First"), Body("Second", fail_restore=True)
        product = self.host.app.activeProduct
        product.rootComponent.bRepBodies = [first, second]
        with self.assertRaisesRegex(RuntimeError, "Second.*body restore rejected"):
            routes.export_route(self.context, format="stl")
        self.assertFalse(first.isLightBulbOn)
        self.assertEqual(first.restores, 1)
        self.assertEqual(second.restores, 1)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_file_created_during_failed_export_option_creation_is_removed(self):
        manager = self.host.app.activeProduct.exportManager

        def fail_options(geometry, path):
            Path(path).write_bytes(b"partial options output")
            raise RuntimeError("options failed after creating a file")

        with patch.object(manager, "createSTLExportOptions", side_effect=fail_options):
            with self.assertRaisesRegex(RuntimeError, "options failed"):
                routes.export_route(self.context, format="stl")
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_file_cleanup_failure_retains_operation_error_and_restores_state(self):
        viewport = self.host.app.activeViewport
        save = viewport.saveAsImageFileWithOptions
        unlink = Path.unlink

        def fail_capture(options):
            save(options)
            raise RuntimeError("capture failed")

        def fail_unlink(path, *args, **kwargs):
            if path.parent == self.directory:
                raise PermissionError("temporary file is locked")
            return unlink(path, *args, **kwargs)

        with (
            patch.object(viewport, "saveAsImageFileWithOptions", side_effect=fail_capture),
            patch.object(Path, "unlink", fail_unlink),
        ):
            with self.assertRaises(RuntimeError) as caught:
                routes.render_route(self.context, camera=1)
        message = str(caught.exception)
        self.assertIn("capture failed", message)
        self.assertIn("temporary file is locked", message)
        self.assertIn(str(self.directory), message)
        self.assertEqual(viewport.visualStyle, "old")
        for control in self.host.ui.commandDefinitions.controls.values():
            self.assertEqual(control.listItems.selected(), [True, False])
        self.assertEqual(len(list(self.directory.iterdir())), 1)
