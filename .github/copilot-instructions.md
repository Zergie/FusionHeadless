# FusionHeadless Workspace Instructions

## Project Overview

**FusionHeadless** is a Fusion 360 add-in that exposes the Fusion Python API over HTTP (localhost:5000) for headless automation and testing. See [README.md](../../README.md) for feature overview and security warnings.

This workspace contains **three separate projects**:

1. **Fusion 360 Add-in** ([`server.py`](../server.py))
   HTTP server running inside Fusion 360, dispatching requests via custom events to the UI thread.

2. **CLI Client** ([`send.py`](../send.py))
   Example command-line tool for sending requests to the server. Useful for scripting and testing.

3. **URL Handler** ([`url_handler.py`](../url_handler.py))
   Windows URL protocol handler for `FusionHeadless://` URLs. Enables clicking links to trigger Fusion operations (e.g., opening files, running commands).

### Dependency Constraints

- **`server.py`**: Builtin Python only. Runs in Fusion 360's own Python environment, which is maintained separately. No external dependencies allowed.
- **`send.py`**: Can use external modules via [`requirements.txt`](../requirements.txt) (e.g., Pygments, jmespath). Runs in isolated venv.
- **`url_handler.py`**: Avoid external dependencies. Keep it simple and self-contained for maximum compatibility.

**Key Constraints:**
- All Fusion API calls must execute on the UI thread (Fusion requirement)
- HTTP server runs in daemon thread; uses custom events to dispatch to UI thread
- Raw Python `eval()`/`exec()` execution — inherently unsafe, local-only use

---

## Architecture

### Threading Model
- **HTTP Server** (`server.py`): Runs on `localhost:5000`, listens in daemon thread
- **UI Thread**: Fusion API execution only on main thread
- **Dispatch**: HTTP requests → custom event → execute on UI thread → return response

### Route Pattern
All routes located in [`routes/`](../routes/):

```python
# def handle(query: dict, app, adsk, [optional params]) -> any:
#   - query: parsed GET/POST parameters
#   - app, adsk, ui, os, sys: globally available
#   - Return: native Python (auto JSON-serialized) or HttpResponse subclass
```

**Dependency Injection**: Handler signature inspected; context injected by parameter name.
**Error Handling**: Exceptions → 500 JSON with traceback.
**Testing**: Each route has `if __name__ == "__main__": test(...)` for local verification.

### Entry Points
- **`FusionHeadless.py`**: Fusion add-in entry point; manages server thread lifecycle and custom event handlers
- **`server.py`**: HTTP request dispatcher; serializes Fusion objects to JSON via recursive `object2json()`

---

## Common Development Tasks

### Adding a New Route
See the **`fusionheadless-new-route`** skill for detailed steps on creating, registering, and testing routes.

Quick summary:
1. Create `routes/new_feature.py` with `handle(query, app, adsk)` function
2. Register in `routes/__init__.py`: `register("/new_feature", "new_feature")`
3. Test locally: `cd routes && python new_feature.py`

### Adding a New MCP Tool
See the **`fusionheadless-new-mcp-tool`** skill for detailed steps on creating and testing MCP tools.

Quick summary:
1. Create `routes/mcp/<tool_name>.py` — filename becomes the MCP tool name
2. Write module docstring — becomes the tool description
3. Implement `get_input_schema()` first, then `handle(query, app, adsk)`
4. No registration needed — auto-discovered by the dispatcher
5. Test locally: `cd routes/mcp && python <tool_name>.py`

### Accessing Fusion Context
In any route handler, request the context you need:
- `app`: Fusion application instance
- `adsk`: Fusion API module
- `ui`: User interface for dialogs/messages
- `os`, `sys`: Python stdlib

Example:
```python
def handle(query: dict, app, ui, adsk) -> dict:
    doc = app.activeDocument
    ui.messageBox(f"Document: {doc.name}")
    return {"doc_name": doc.name}
```

### Returning Binary Data
For exports (STEP, STL, etc.), use `BinaryResponse` from [`routes/_utils_.py`](../routes/_utils_.py):
```python
from _utils_ import BinaryResponse

def handle(query: dict, app, adsk) -> BinaryResponse:
    # ... export logic ...
    with open(filepath, 'rb') as f:
        content = f.read()
    os.remove(filepath)
    return BinaryResponse(content)
```

### Serialization & Depth Control
Fusion objects are recursively serialized to JSON. Control depth via `depth` query param:
```python
# POST /eval
# { "code": "app.activeDocument", "depth": 3 }
```

Default depth: 2. Deeper traversal = slower but more data.

---

## Development Workflow

### Local Testing
Each route is self-contained and testable without server:
```bash
cd c:\...\FusionHeadless\routes
python export.py        # Runs test with Fusion context
python select.py        # Tests component selection
```

### Iterative Development
Use **`/reload`** endpoint to reload route modules without restarting Fusion:
```bash
curl http://localhost:5000/reload
```

Or programmatically in a test script:
```python
from _client_ import client
client("http://localhost:5000/reload")
```

### Error Inspection
Errors are returned as 500 JSON responses with full traceback:
```json
{
  "status": "error",
  "error": "Component 'missing' not found",
  "traceback": "..."
}
```

---

## Key Files

| File | Purpose |
|------|---------|
| [FusionHeadless.py](../FusionHeadless.py) | Fusion add-in lifecycle management |
| [server.py](../server.py) | HTTP server, request dispatcher, JSON serialization |
| [send.py](../send.py) | CLI client for sending requests to FusionHeadless |
| [routes/__init__.py](../routes/__init__.py) | Route registry and lazy module loading |
| [routes/_utils_.py](../routes/_utils_.py) | `BinaryResponse`, Visibility helpers, common utilities |
| [routes/_client_.py](../routes/_client_.py) | Test client for local route testing |
| [cli/](../cli/) | Utility modules used by `send.py` |
| [cli/methods.py](../cli/methods.py) | HTTP client methods (`get`, `post`, `file`) |
| [cli/Arguments.py](../cli/Arguments.py) | Query parameter parsing (ListArgument, GroupArgument) |
| [cli/EvalHelper.py](../cli/EvalHelper.py) | Enhanced dict/list for Python expression evaluation |
| [cli/match_with_files.py](../cli/match_with_files.py) | File matching utilities |
| [cli/my_printer.py](../cli/my_printer.py) | Pretty printer for formatted output |
| [requirements.txt](../requirements.txt) | Dependencies (Pygments, jmespath) |
| [Makefile](../Makefile) | Build setup (Python 3.14 venv) |

### CLI Module (`cli/`)

The [`cli/`](../cli/) directory contains utility modules supporting the [`send.py`](../send.py) CLI client:

- **`methods.py`**: HTTP request primitives (`get()`, `post()`, `file()`)
- **`Arguments.py`**: Parameter parsing for list and grouped arguments
- **`EvalHelper.py`**: `EvalDict` and `EvalList` for Python expression evaluation on responses
- **`match_with_files.py`**: File matching and filtering utilities
- **`my_printer.py`**: Pretty-printing with syntax highlighting (via Pygments)
- **`ContextVariable.py`**: Context variable helpers
- **`Exceptions.py`**: Custom exception types
- **`term.py`**: Terminal utilities

**Usage in `send.py`**:
```python
from cli.methods import get, post, file
from cli.match_with_files import match_with_files
from cli.EvalHelper import EvalDict, EvalList
```

---

## Common Patterns

### Parameters as Lists
Accept multiple values for a parameter:
```python
bodies = query.get("body")
if isinstance(bodies, list):
    # Multiple bodies selected
else:
    # Single body
```

### Visibility Toggling
Use `setVisibility()` to show/hide components temporarily:
```python
from _utils_ import setVisibility, Visibility

setVisibility(app.activeProduct, 'all', Visibility.SHOW)
# ... do work ...
setVisibility(app.activeProduct, 'all', Visibility.RESTORE)
```

### Exception Messages
Always provide context in error messages:
```python
if not component:
    raise Exception(f"Component '{query['component']}' not found in {design.name}")
```

---

## Build & Setup

See [Makefile](../Makefile) for Python 3.14 venv setup:
```bash
make setup    # Install dependencies
make clean    # Remove venv
```

---

## Related Documentation
- [README.md](../README.md) — Installation, API endpoints, examples
- [FusionHeadless.py](../FusionHeadless.py) — Add-in registration and threading model
