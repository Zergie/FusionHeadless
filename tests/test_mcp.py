from __future__ import annotations

import json
import socket
from types import ModuleType, SimpleNamespace
import unittest
from urllib.request import Request, urlopen

from adapter import FusionAdapter
from context import FusionContext, registry
from fusion_invocation import FusionOperationInvoker
from mcp.registry import call_tool, tool_definitions, tool_inventory
import server
from mcp.endpoint import mcp
from tests.harness import FakeFusionHost, route_path


class McpRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = FakeFusionHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.adapter = FusionAdapter(host=self.host, port=self.port)
        self.assertTrue(self.adapter.start(timeout=5))
        self.addCleanup(self.adapter.stop)

    def post(self, payload: object) -> dict:
        request = Request(
            f"http://127.0.0.1:{self.port}{route_path(mcp)}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_initialize_and_tools_list_preserve_json_rpc_shape(self) -> None:
        initialized = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(initialized["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(initialized["result"]["serverInfo"]["version"], "0.2.0")
        listed = self.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(
            [tool["name"] for tool in listed["result"]["tools"]],
            ["get_api_documentation", "list_open_documents", "search_components"],
        )

    def test_tool_call_crosses_bridge_and_wraps_result(self) -> None:
        result = self.post({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_open_documents", "arguments": {}},
        })
        self.assertEqual(result["result"]["content"][0]["type"], "text")
        self.assertEqual(json.loads(result["result"]["content"][0]["text"])["count"], 0)

    def test_component_search_selects_document_and_filters_across_bridge(self) -> None:
        occurrences = [
            SimpleNamespace(name="Bolt v3:1", component=SimpleNamespace(
                name="Fastener", material=SimpleNamespace(name=material),
            ))
            for material in ("Steel", "Brass")
        ]
        design = SimpleNamespace(rootComponent=SimpleNamespace(allOccurrences=occurrences))
        selected = SimpleNamespace(
            name="Assembly v7", dataFile=SimpleNamespace(id="assembly-id"),
            products=SimpleNamespace(count=1, item=lambda index: design),
        )
        self.host.app.activeDocument = SimpleNamespace(name="Other document")
        self.host.app.documents = SimpleNamespace(count=1, item=lambda index: selected)
        response = self.post({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "search_components", "arguments": {
                "query": "Bolt", "exact": True, "document": "Assembly",
                "exclude_material": "steel",
            }},
        })
        result = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(result["resolved_document"], "Assembly v7")
        self.assertEqual(result["matches"], [{"name": "Fastener", "material": "Brass", "count": 1}])


class McpToolDefinitionTests(unittest.TestCase):
    def test_inventory_preserves_exact_public_metadata(self) -> None:
        self.assertEqual(tool_inventory(), [
            {
                "name": "get_api_documentation",
                "description": "Search Fusion API documentation by class/member names and docstrings.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search_term": {"type": "string", "description": "Search text."},
                        "category": {
                            "type": "string",
                            "enum": ["class_name", "member_name", "description", "all"],
                        },
                    },
                    "required": ["search_term"],
                },
            },
            {
                "name": "list_open_documents",
                "description": "List all currently open Fusion 360 documents.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "search_components",
                "description": "Search and count matching components/occurrences in an open Fusion document (active by default).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search text or regex pattern."},
                        "use_regex": {"type": "boolean", "description": "Use case-insensitive regex matching."},
                        "exact": {"type": "boolean", "description": "Use case-insensitive exact matching."},
                        "exclude_material": {"type": "string", "description": "Material exclusion regex."},
                        "document": {"type": "string", "description": "Open document name or data-file id."},
                    },
                    "required": ["query"],
                },
            },
        ])

    def test_definitions_reference_registered_fusion_callables(self) -> None:
        definitions = tool_definitions()
        self.assertEqual(
            [definition.name for definition in definitions],
            ["get_api_documentation", "list_open_documents", "search_components"],
        )
        for definition in definitions:
            self.assertTrue(callable(definition.operation))
            self.assertEqual(
                getattr(definition.operation, "__fusionheadless_context__", None),
                "fusion",
            )
            self.assertIs(
                registry.fusion[definition.operation.__name__].value,
                definition.operation,
            )

    def test_dispatch_uses_the_definition_operation(self) -> None:
        commands: list[str] = []

        def fusion_call(command: str) -> object:
            commands.append(command)
            return {"count": 0}

        result = call_tool("list_open_documents", {}, FusionOperationInvoker(fusion_call))
        definition = next(
            item for item in tool_definitions() if item.name == "list_open_documents"
        )
        self.assertEqual(
            commands,
            [f"return {definition.operation.__name__}({{}}, fusion_context)"],
        )
        self.assertEqual(result["content"][0]["type"], "text")

    def test_dispatch_validates_name_arguments_and_required_fields(self) -> None:
        invoker = FusionOperationInvoker(lambda command: command)
        with self.assertRaisesRegex(ValueError, "Tool 'unknown' not found"):
            call_tool("unknown", {}, invoker)
        with self.assertRaisesRegex(ValueError, "Tool arguments must be an object"):
            call_tool("list_open_documents", [], invoker)
        for name, required in (
            ("get_api_documentation", "search_term"),
            ("search_components", "query"),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError, f"Missing required argument '{required}'"
                ):
                    call_tool(name, {}, invoker)

    def test_documentation_and_component_operations_preserve_behavior(self) -> None:
        definitions = {item.name: item.operation for item in tool_definitions()}

        core = ModuleType("core")

        class Widget:
            """A documented widget."""

            @property
            def size(self) -> int:
                """Return the widget size."""
                return 1

        core.Widget = Widget
        documentation = definitions["get_api_documentation"](
            {"search_term": "Widget", "category": "class_name"},
            FusionContext(None, None, SimpleNamespace(core=core)),
        )
        self.assertEqual(documentation["count"], 1)
        self.assertEqual(documentation["matches"][0]["name"], "Widget")

        occurrences = [
            SimpleNamespace(component=SimpleNamespace(name="Widget(1)")),
            SimpleNamespace(component=SimpleNamespace(name="Widget(2)")),
        ]
        design = SimpleNamespace(rootComponent=SimpleNamespace(allOccurrences=occurrences))

        class Products:
            count = 1

            def item(self, index: int) -> object:
                if index != 0:
                    raise AssertionError(f"unexpected product index: {index}")
                return design

        products = Products()
        app = SimpleNamespace(
            activeDocument=SimpleNamespace(name="Demo", products=products)
        )
        components = definitions["search_components"](
            {"query": "widget"}, FusionContext(app, None, None)
        )
        self.assertEqual(components["total_component_scanned"], 2)
        self.assertEqual(components["total_component_matches"], 2)
        self.assertEqual(components["matches"], [
            {"name": "Widget", "material": None, "count": 2}
        ])


if __name__ == "__main__":
    unittest.main()
