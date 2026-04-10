---
name: fusionheadless-new-mcp-tool
description: 'Add a new MCP tool to FusionHeadless. Use when creating a new routes/mcp/<tool_name>.py, adding a tool to the MCP tools/list endpoint, or implementing a new tool callable from VS Code MCP client.'
argument-hint: 'tool name and brief description of what it should do'
---

# Add New FusionHeadless MCP Tool

Creates a new MCP tool exposed via `tools/list` and callable via `tools/call` on the `/mcp` endpoint.

## Conventions

- **Tool name** = filename stem (e.g. `list_open_documents.py` → `"list_open_documents"`)
- **Tool description** = module-level docstring, whitespace-normalized
- **Input schema** = returned by `get_input_schema()` — must be `{"type": "object", ...}`
- **Files starting with `_`** are never discovered as tools

## Workflow

### 1. Create the tool module

Create `routes/mcp/<tool_name>.py` from the template below.
The filename becomes the MCP tool name — choose it carefully (breaking change to rename).

```python
"""One-line summary. Longer explanation on subsequent lines.

Detail continues here. The full docstring (whitespace-normalized) becomes
the MCP tool description visible to the client.
"""


def get_input_schema() -> dict:
    """Must be the first function — appears immediately after imports/constants."""
    return {
        "type": "object",
        "properties": {
            "param_name": {
                "type": "string",
                "description": "What this parameter does."
            }
        },
        "required": ["param_name"]   # omit key or use [] when no required params
    }


def handle(query: dict, app, adsk) -> dict:
    # Validate
    value = query.get("param_name")
    if not value:
        raise Exception("'param_name' is required")

    # Fusion API work here
    return {"result": value}


if __name__ == "__main__":
    from _client_ import test
    test(__file__, {"param_name": "example"}, timeout=30)
```

**Rules:**
- `get_input_schema()` must be the **first function**, right after any imports and module-level constants.
- `required` lives inside the schema dict, not as a separate method.
- No `describe()` — that pattern is removed.

### 2. Dependency injection in `handle()`

Request context by parameter name:

| Parameter | Value |
|-----------|-------|
| `query` | Dict of tool arguments from the MCP call |
| `app` | Fusion `Application` instance |
| `adsk` | Fusion API module |

Only declare parameters you need — unused ones are skipped automatically.

### 3. Return types

| Return | Effect |
|--------|--------|
| `dict` / `list` / `str` | JSON-serialized into MCP text content |
| `{"content": [...]}` | Passed through as-is (already MCP content) |

### 4. Test locally

```bash
cd routes/mcp
python <tool_name>.py
```

No registration step needed — the dispatcher auto-discovers all `.py` files in `routes/mcp/` that don't start with `_`.

### 5. Verify discovery

After reloading or restarting Fusion, check `tools/list`:

```bash
curl -s -X POST http://localhost:5000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python -m json.tool
```

Confirm:
- `name` equals the filename stem
- `description` equals the normalized docstring
- `inputSchema.type` is `"object"`
- `required` fields are present

Or use the `/reload` endpoint first to pick up changes without restarting Fusion:

```bash
curl http://localhost:5000/reload
```

## Checklist

- [ ] Filename chosen deliberately (it becomes the external tool name)
- [ ] Module docstring is present and descriptive (missing one triggers a dispatcher warning)
- [ ] `get_input_schema()` is the first function in the file
- [ ] `required` array is accurate inside the schema
- [ ] `handle()` validates inputs and raises clear exceptions on bad input
- [ ] Local test passes (`python <tool_name>.py`)
- [ ] Tool appears in `tools/list` with correct name, description, and schema

## Discovery Warnings

The dispatcher prints warnings and **skips** tools that:
- Are missing `get_input_schema()`
- Return a schema where `type != "object"`
- Have `get_input_schema()` raise an exception
- Have an empty module docstring

Check Fusion's Python console for `[FusionHeadless] WARNING:` lines if a tool doesn't appear.
