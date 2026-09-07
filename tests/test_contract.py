from __future__ import annotations

import ast
import inspect
from pathlib import Path
import subprocess
import sys
import unittest

import adapter
import mcp.tools as mcp_tools
from mcp import registry as mcp_registry
import routes
import server
from fastapi.routing import APIRoute
from routing import route_definitions


class ProcessSplitContractTests(unittest.TestCase):
    def test_fusion_package_imports_need_only_the_standard_library(self) -> None:
        # -S removes site-packages so an accidental FastAPI/numpy dependency
        # in a package initializer fails even on a fully provisioned machine.
        result = subprocess.run(
            [sys.executable, "-S", "-c", "import adapter, routes, mcp.tools; "
             "import sys; assert 'mcp.endpoint' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_adapter_has_no_http_framework_or_listener_surface(self) -> None:
        source = Path(adapter.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) and node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertNotIn("fastapi", imported)
        self.assertNotIn("uvicorn", imported)
        self.assertNotIn("http.server", imported)

    def test_mcp_tools_has_no_http_framework_dependency(self) -> None:
        source = Path(mcp_tools.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) and node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertNotIn("fastapi", imported)
        self.assertNotIn("uvicorn", imported)

    def test_child_exposes_every_migrated_route(self) -> None:
        expected = {definition.path: definition.operation.__name__
                    for definition in route_definitions()}
        installed = {
            definition.path: definition.operation.__name__
            for route in server.app.routes if isinstance(route, APIRoute)
            if (definition := getattr(
                route.endpoint, "__fusionheadless_route__", None
            )) is not None
        }
        self.assertEqual(installed, expected)

    def test_routes_use_context_first_typed_parameters(self) -> None:
        operations = [definition.operation for definition in route_definitions()]
        operations.append(routes.fusion_status)
        for operation in operations:
            with self.subTest(operation=operation.__name__):
                parameters = list(inspect.signature(operation).parameters.values())
                self.assertEqual(parameters[0].name, "context")
                self.assertTrue(all(parameter.annotation is not inspect.Parameter.empty
                                    for parameter in parameters[1:]))

    def test_mcp_operations_keep_the_query_context_interface(self) -> None:
        for definition in mcp_registry.tool_definitions():
            with self.subTest(operation=definition.operation.__name__):
                parameters = list(inspect.signature(definition.operation).parameters)
                self.assertEqual(parameters, ["query", "context"])

    def test_runtime_dependencies_are_pinned(self) -> None:
        requirements = Path(__file__).parents[1] / "requirements.txt"
        lines = {
            line.strip()
            for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        self.assertIn("fastapi==0.115.6", lines)
        self.assertIn("uvicorn==0.34.0", lines)


if __name__ == "__main__":
    unittest.main()
