"""MCP tool dispatcher — JSON-RPC 2.0 over HTTP for VS Code MCP client.

Implements the standard MCP protocol methods:
  initialize              — capability negotiation handshake
  ping                    — keep-alive
  tools/list              — discover available tools
  tools/call              — execute a tool
  notifications/*         — client notifications (no response)

Tools live in routes/mcp/<tool_name>.py. Each tool module must define:
    get_input_schema() -> { "type": "object", "properties": {...}, ... }
    handle(query, app, adsk) -> any   (auto-wrapped into MCP content)

Tool name is derived from the filename stem. Tool description is derived from
the full module docstring (whitespace-normalized). Files starting with '_' are
never considered tools.

POST http://localhost:5000/mcp
Body: {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
"""

import importlib.util
import json
import os
import sys

from _utils_ import HttpResponse

_tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp")
PROTOCOL_VERSION = "2024-11-05"


class JsonRpcResponse(HttpResponse):
    """Raw JSON-RPC 2.0 response — bypasses server's {"status":"ok","result":...} wrapper."""

    def __init__(self, data: dict):
        super().__init__(200)
        self.headers["Content-Type"] = "application/json"
        self._data = data

    def send_content(self, requestHandler):
        requestHandler.wfile.write(json.dumps(self._data).encode())


def _get_module(tool_name):
    """Lazy-load tool module; stored in sys.modules so /reload finds it."""
    key = f"FusionHeadless.mcp.{tool_name}"
    if key not in sys.modules:
        tool_path = os.path.join(_tools_dir, f"{tool_name}.py")
        if not os.path.exists(tool_path):
            return None
        spec = importlib.util.spec_from_file_location(key, tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[key] = module
    return sys.modules.get(key)


def _normalize_docstring(doc):
    """Collapse all whitespace/newlines in a docstring into single spaces."""
    return " ".join((doc or "").split())


def _discover_tools():
    """Scan routes/mcp/ and return list of tool metadata dicts."""
    tools = []
    if not os.path.isdir(_tools_dir):
        return tools
    for filename in sorted(os.listdir(_tools_dir)):
        if filename.startswith("_") or not filename.endswith(".py"):
            continue
        tool_name = filename[:-3]
        module = _get_module(tool_name)
        if module is None:
            continue
        if not hasattr(module, "get_input_schema") or not callable(module.get_input_schema):
            print(f"[FusionHeadless] WARNING: Tool '{tool_name}' missing get_input_schema(), skipping.")
            continue
        try:
            schema = module.get_input_schema()
            if not isinstance(schema, dict) or schema.get("type") != "object":
                print(f"[FusionHeadless] WARNING: Tool '{tool_name}' get_input_schema() must return an object schema, skipping.")
                continue
        except Exception as e:
            print(f"[FusionHeadless] WARNING: Tool '{tool_name}' get_input_schema() raised {e}, skipping.")
            continue
        description = _normalize_docstring(getattr(module, "__doc__", None))
        if not description:
            print(f"[FusionHeadless] WARNING: Tool '{tool_name}' has no module docstring.")
        tools.append({
            "name": tool_name,
            "description": description,
            "inputSchema": schema,
        })
    return tools


def _call_tool(tool_name, arguments, app, adsk):
    """Dispatch to tool handler with dependency injection; wrap result in MCP content."""
    module = _get_module(tool_name)
    if not module or not hasattr(module, "handle"):
        raise Exception(f"Tool '{tool_name}' not found")
    fn = module.handle
    varnames = fn.__code__.co_varnames[:fn.__code__.co_argcount]
    kwargs = {k: v for k, v in {"query": arguments, "app": app, "adsk": adsk}.items() if k in varnames}
    result = fn(**kwargs)
    # Auto-wrap into MCP content if not already
    if isinstance(result, dict) and "content" in result:
        return result
    text = result if isinstance(result, str) else json.dumps(result, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def handle(query: dict, app, adsk) -> JsonRpcResponse:
    """Main MCP JSON-RPC 2.0 dispatcher."""
    rpc_id = query.get("id")
    method = query.get("method")
    params = query.get("params") or {}

    def ok(result):
        return JsonRpcResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    def error(code, message):
        return JsonRpcResponse({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}})

    if method == "initialize":
        return ok({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "FusionHeadless", "version": "1.0.0"}
        })

    elif method == "ping":
        return ok({})

    elif method is not None and method.startswith("notifications/"):
        return JsonRpcResponse({})  # Notifications expect no response

    elif method == "tools/list":
        return ok({"tools": _discover_tools()})

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            return ok(_call_tool(tool_name, arguments, app, adsk))
        except Exception as e:
            return error(-32603, str(e))

    elif method is not None:
        return error(-32601, f"Method not found: {method}")

    return error(-32600, "Invalid Request")


if __name__ == "__main__":
    from _client_ import test
    test(__file__, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=30)
