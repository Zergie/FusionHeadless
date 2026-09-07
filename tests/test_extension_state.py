from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from context import FusionContext, fusion, registry, server
from extension_state import extension_fingerprint, reset_extensions
import routes
import mcp.tools as mcp_tools
from mcp import registry as mcp_registry
import routing


class ExtensionStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = reset_extensions()
        self.addCleanup(reset_extensions)

    def test_reset_replaces_declarations_and_preserves_module_references(self) -> None:
        original_route = routes.fusion_eval
        original_tool = mcp_tools.mcp_list_open_documents
        routes.runtime_attribute = object()
        mcp_tools.runtime_attribute = object()

        @fusion
        class RuntimeOnly:
            pass

        @server
        def runtime_callback():
            return None

        @routing.api_route("/temporary-extension")
        def runtime_route(context):
            return None

        @mcp_registry.mcp_tool("temporary_extension", description="Temporary", input_schema={})
        def runtime_tool(query, context):
            return None

        self.assertNotEqual(extension_fingerprint(), self.baseline)
        self.assertEqual(reset_extensions(), self.baseline)
        self.assertEqual(extension_fingerprint(), self.baseline)
        for module in (routes, mcp_tools):
            self.assertIs(importlib.import_module(module.__name__), module)
            self.assertFalse(hasattr(module, "runtime_attribute"))
        self.assertIsNot(routes.fusion_eval, original_route)
        self.assertIsNot(mcp_tools.mcp_list_open_documents, original_tool)
        self.assertNotIn(RuntimeOnly.__name__, registry.fusion)
        self.assertNotIn(runtime_callback.__name__, registry.server)
        self.assertNotIn(runtime_route, [item.operation for item in routing.route_definitions()])
        self.assertNotIn(runtime_tool, [item.operation for item in mcp_registry.tool_definitions()])
        for item in (*routing.route_definitions(), *mcp_registry.tool_definitions()):
            self.assertIs(registry.fusion[item.operation.__name__].value, item.operation)

    def test_partial_import_failure_clears_declarations_and_allows_retry(self) -> None:
        original_import = importlib.import_module
        for module in (routes, mcp_tools):
            with self.subTest(module=module.__name__):
                original_route = routes.fusion_eval

                def fail_import(name, package=None):
                    fresh = original_import(name, package)
                    if name == module.__name__:
                        # Fail after decorators have already registered values.
                        raise ImportError(f"broken extension {name}")
                    return fresh

                with patch("extension_state.importlib.import_module", side_effect=fail_import):
                    with self.assertRaisesRegex(RuntimeError, "Fusion extension reset failed.*broken extension"):
                        reset_extensions()

                self.assertEqual(set(registry.fusion), {"FusionContext"})
                self.assertIs(registry.fusion["FusionContext"].value, FusionContext)
                self.assertEqual(registry.server, {})
                self.assertEqual(routing.route_definitions(), ())
                self.assertEqual(mcp_registry.tool_definitions(), ())
                with self.assertRaisesRegex(RuntimeError, "extension module has no source path"):
                    extension_fingerprint()
                self.assertEqual(reset_extensions(), self.baseline)
                self.assertIsNot(routes.fusion_eval, original_route)
                self.assertIs(original_import(module.__name__), module)

    def test_fingerprint_failure_also_clears_replacement_and_allows_retry(self) -> None:
        with patch("extension_state.Path.read_bytes", side_effect=OSError("source unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Fusion extension reset failed.*source unavailable"):
                reset_extensions()
        self.assertEqual(set(registry.fusion), {"FusionContext"})
        self.assertEqual(registry.server, {})
        self.assertEqual(routing.route_definitions(), ())
        self.assertEqual(mcp_registry.tool_definitions(), ())
        self.assertEqual(reset_extensions(), self.baseline)

    def test_fingerprint_covers_sources_and_delivery_metadata(self) -> None:
        original_read = Path.read_bytes
        with patch("extension_state.Path.read_bytes", lambda path: original_read(path) + b"\n# changed"):
            self.assertNotEqual(extension_fingerprint(), self.baseline)

        export = next(item for item in routing.route_definitions()
                      if item.operation is routes.export_route)
        routing.api_route(export.path, methods=export.methods,
                          binary=routing.BinaryResponse("test/type", "changed"))(export.operation)
        self.assertNotEqual(extension_fingerprint(), self.baseline)
        reset_extensions()

        tool = mcp_registry.tool_definitions()[0]
        mcp_registry.mcp_tool(tool.name, description=tool.description,
                           input_schema={**tool.input_schema, "description": "changed"})(tool.operation)
        self.assertNotEqual(extension_fingerprint(), self.baseline)

    def test_fingerprint_matches_a_fresh_process(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c",
             "from extension_state import extension_fingerprint; print(extension_fingerprint())"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            check=True, timeout=10,
        )
        self.assertEqual(result.stdout.strip(), self.baseline)


if __name__ == "__main__":
    unittest.main()
