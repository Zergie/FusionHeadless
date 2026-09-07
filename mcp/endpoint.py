"""Child-only MCP HTTP endpoint and JSON-RPC handling."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from mcp.registry import call_tool, tool_inventory

PROTOCOL_VERSION = "2024-11-05"
router = APIRouter()


@router.post("/mcp")
async def mcp(
    query: Annotated[dict[str, Any], Body(description="JSON-RPC request")],
    request: Request,
) -> Any:
    rpc_id = query.get("id")
    method = query.get("method")
    params = query.get("params") or {}
    if method is not None and not isinstance(method, str):
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                              "error": {"code": -32600, "message": "Invalid Request"}})
    if method and method.startswith("notifications/"):
        return JSONResponse({})
    elif method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "FusionHeadless", "version": request.app.version}}
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tool_inventory()}}
    elif method == "tools/call":
        if not isinstance(params, dict):
            return {"jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32602, "message": "Invalid params"}}
        try:
            result = await run_in_threadpool(
                call_tool,
                params.get("name"), params.get("arguments") or {},
                request.app.state.fusion_invoker,
            )
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        except Exception as error:
            return {"jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32603, "message": str(error)}}
    elif method:
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}
    else:
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32600, "message": "Invalid Request"}}

