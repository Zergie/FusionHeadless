---
name: fusionheadless-new-mcp-tool
description: Add or change a FusionHeadless MCP tool using one colocated mcp_tool declaration and implementation.
argument-hint: Tool name and the Fusion operation it should perform
---

# Add an MCP tool

Add, remove, or rename a tool in one place: `mcp_tools.py`. The module derives
the client inventory and bridge dispatch from each decorated implementation;
`server.py` already serves them through `/mcp`.

## Decorator interface

Declare the external name, description, and JSON input schema immediately
beside the implementation:

```python
@mcp_tool(
    name,
    description="One concise client-facing description.",
    input_schema={"type": "object", "properties": {}},
)
def mcp_operation(query: dict[str, Any], context: Any) -> dict[str, Any]:
    app = context.app
    return {"result": "value"}
```

- `name` is the single source of truth for the external MCP tool name.
- `description` is returned by `tools/list`.
- `input_schema` is returned as `inputSchema`; its `required` array also drives
  required-argument validation before the Fusion call.
- The decorated function is registered for Fusion execution. Its actual Python
  function name drives bridge dispatch automatically.

Do not add a parallel metadata dictionary, a separate required-arguments list,
a string copy of the operation name, or another registration step.

## Current example

This declaration is copied from `mcp_tools.py`:

```python
@mcp_tool(
    "list_open_documents",
    description="List all currently open Fusion 360 documents.",
    input_schema={"type": "object", "properties": {}},
)
def mcp_list_open_documents(query: dict[str, Any], context: Any) -> dict[str, Any]:
    # Read the Fusion application and return a JSON-compatible dictionary.
```

Use the same signature shape for new tools: invocation supplies `query` and
the unified context. Read `context.app`, `context.ui`, or `context.adsk` only
when needed. Validate values more deeply inside the function when JSON Schema
presence checks are insufficient.

## Return contract

- A value without a top-level `content` key is serialized into one MCP text
  content item.
- A dictionary containing `content` is passed through as an already-formed MCP
  result.
- Raise a clear exception for invalid input or unavailable Fusion state; the
  MCP endpoint returns the failure as a JSON-RPC error.

## Workflow

1. Read the existing definitions and helpers in `mcp_tools.py`.
2. Add one decorated implementation with its complete external metadata.
3. Add characterization and dispatch tests in `tests/test_mcp.py`. Derive
   expectations from `tool_definitions()` or `tool_inventory()` where the
   contract should follow declarations.
4. Confirm `tools/list` includes the declaration and `tools/call` invokes the
   decorated operation.

Do not edit `server.py` for a normal tool addition. Do not create a discovery
directory or make filenames part of the public contract.

## Verification

Run the complete suite from the repository root:

```text
python -c "import os,pathlib,sys,unittest; d=str(pathlib.Path('.scratch/deps').resolve()); os.environ['PYTHONPATH']=d+os.pathsep+os.environ.get('PYTHONPATH',''); sys.path.insert(0,d); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(0 if r.wasSuccessful() else 1)"
python -m compileall -q adapter.py bridge.py context.py server.py fusion_routes.py mcp_tools.py routing.py tests
git diff --check
```

Verify the external name, description, schema, required arguments, dispatch,
return wrapping, and invalid-input behavior.

## References

- `mcp_tools.py` — `mcp_tool`, inventory, dispatch, and implementations
- `server.py` — JSON-RPC protocol endpoint
- `tests/test_mcp.py` — declaration and protocol contracts
- `tests/test_contract.py` — process-dependency boundary
