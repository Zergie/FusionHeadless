# Create New FusionHeadless Route

Create a new HTTP route handler for the FusionHeadless server.

## Workflow

1. **Create route module** in `routes/new_feature.py` with handler function and test
2. **Register route** in `routes/__init__.py`
3. **Test locally** by running the route module directly

## Route Template

Every route module follows this structure:

```python
"""Brief description of what this route does."""

def handle(query: dict, app, adsk) -> any:
    # Validate inputs
    if "required_param" not in query:
        raise Exception("Missing required_param")

    # Use Fusion API
    result = app.activeProduct.rootComponent

    # Return native Python type (auto JSON-serialized)
    return {"status": "ok", "data": result}

if __name__ == "__main__":
    from _client_ import test
    test(__file__, { "required_param": "value" }, timeout=30)
```

## Key Concepts

### Dependency Injection
Request any Fusion context by parameter name in the `handle()` signature:
- `query`: dict of parsed request parameters
- `app`: Fusion application instance
- `adsk`: Fusion API module
- `ui`: User interface (dialogs)
- `os`, `sys`: Python stdlib

**Example:**
```python
def handle(query: dict, app, ui) -> dict:
    ui.messageBox(f"Active doc: {app.activeDocument.name}")
    return {"doc": app.activeDocument.name}
```

### Return Types
- **Native Python** (dict, list, str): auto-serialized to JSON
- **BinaryResponse**: for file exports (STEP, STL, etc.)
- **HttpResponse**: for custom response types

**Binary example (see `routes/export.py`):**
```python
from _utils_ import BinaryResponse

def handle(query: dict, app, adsk) -> BinaryResponse:
    # ... export logic ...
    with open(filepath, 'rb') as f:
        content = f.read()
    os.remove(filepath)
    return BinaryResponse(content)
```

### Error Handling
Raise exceptions with context; the server catches them and returns 500 JSON with traceback:
```python
if not component:
    raise Exception(f"Component '{query['component']}' not found in {design.name}")
```

### Parameter Validation
Accept lists or single values; handle both:
```python
bodies = query.get("body")
if isinstance(bodies, list):
    # Multiple bodies selected
else:
    # Single body
```

## Registration

Add your route to `routes/__init__.py`:
```python
register("/new_feature", "new_feature")
```

Format: `register("/endpoint_path", "module_name")`

## Testing

Test the route locally **before** deploying to Fusion:

```bash
cd routes
python new_feature.py  # Runs with Fusion context
```

The test client (`_client_.test()`) communicates with the running Fusion instance via the HTTP server.

## Common Patterns

**Visibility Toggle** (`_utils_.py`):
```python
from _utils_ import setVisibility, Visibility

setVisibility(app.activeProduct, 'all', Visibility.SHOW)
# ... do work ...
setVisibility(app.activeProduct, 'all', Visibility.RESTORE)
```

**Serialization Depth** (control recursion for large object trees):
```python
# POST /eval with depth param
# { "code": "app.activeDocument", "depth": 3 }
```

**Component/Body Lookup** (find by name or ID):
```python
items = [x for x in app.activeProduct.rootComponent.allOccurrences
         if x.component.name == query["component"]
         or x.component.id == query["component"]]
if len(items) == 0:
    raise Exception(f"Component '{query['component']}' not found.")
design = items[0].component
```

## Reload During Development

Use the `/reload` endpoint to reload route modules **without restarting Fusion**:

```bash
curl http://localhost:5000/reload
```

Or programmatically:
```python
from _client_ import client
client("http://localhost:5000/reload")
```

This is useful for iterative development — edit a route, reload, and test again.

## Reference

- [routes/__init__.py](../../routes/__init__.py) — Route registry, module loading
- [routes/_utils_.py](../../routes/_utils_.py) — `BinaryResponse`, `setVisibility()`, helpers
- [routes/_client_.py](../../routes/_client_.py) — Test client
- [routes/export.py](../../routes/export.py) — Example: complex route with binary export
- [routes/select.py](../../routes/select.py) — Example: component/body selection
