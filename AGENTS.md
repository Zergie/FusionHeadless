# FusionHeadless workspace instructions

## Project overview

FusionHeadless exposes Fusion 360 automation on `localhost:5000`. The add-in is
split across a built-in-only Fusion adapter and a FastAPI child process. See
`README.md` for the public API and security warning.

## Architecture and ownership

- `adapter.py` runs in or next to Fusion. It launches and supervises the child,
  owns the framed bridge, and dispatches Fusion work onto Fusion's UI thread.
  It and the Fusion-side modules must remain compatible with Fusion's bundled
  Python environment.
- `server.py` is the child process. It owns FastAPI, Uvicorn, the localhost
  listener, HTTP request/response handling, lifecycle endpoints, and the MCP
  endpoint. Its pinned third-party dependencies are in `requirements.txt`.
- `routes/` contains one module per Fusion-backed HTTP route. Each path and
  its metadata are declared beside the implementation with `routing.api_route`.
  `routes/__init__.py` explicitly imports the operations to register.
- `routing.py` is the built-in-only route-definition interface shared across
  the process seam. `server.py` installs its `route_definitions()`
  automatically.
- `mcp/registry.py` owns MCP declarations, inventory, validation, and dispatch.
  Each tool in `mcp/tools/` is declared with `mcp_tool` beside its implementation;
  `mcp/tools/__init__.py` explicitly imports the tools. `mcp/endpoint.py` owns
  the child-only HTTP endpoint and JSON-RPC handling.
- `context.py` defines the explicit `@fusion` and `@server` process-boundary
  registrations and supported value serialization. `bridge.py` implements the
  framed transport.

Only the child binds the HTTP port. All Fusion API calls execute through the
adapter on Fusion's UI thread. Raw `/eval` and `/exec` execution is inherently
unsafe, so the service must remain local-only.

## Adding a Fusion-backed HTTP route

Use the `fusionheadless-new-route` skill when it is available. A normal
Fusion-backed route lives in one module under `routes/`. Add or change its
decorated function there; for a new module, add an explicit operation import in
`routes/__init__.py`. `server.py` derives its FastAPI registration from that
declaration and should not be edited.

```python
from routing import api_route


@api_route("/example", methods=("POST",))
def example_route(context, name: str | None = None):
    return {"document": context.app.activeDocument.name}
```

Every registered HTTP operation receives one immutable context object first,
followed by individually typed public parameters. FastAPI and `fusion_cli`
derive their schemas from that signature. Use `routing.ApiParameter` inside
`typing.Annotated` for transport-neutral parameter help. Use `context.app`,
`context.ui`, and `context.adsk` as needed. For a binary route, attach
`routing.BinaryResponse` metadata and return bytes from the implementation.

## Adding an MCP tool

Use the `fusionheadless-new-mcp-tool` skill when it is available. Add one
`@mcp_tool` declaration beside its implementation in `mcp/tools/<name>.py`,
importing the decorator from `mcp.registry`. Import new tools explicitly in
`mcp/tools/__init__.py`. The tool inventory, required argument validation, and bridge dispatch are derived
automatically. Do not add a second metadata table or a string copy of the
operation name.

## Process-boundary context

Server execution is the default. Export only the definitions that must cross
the process seam:

```python
from context import fusion, server


@fusion
def active_document_name(app):
    return app.activeDocument.name


@server
def normalize_name(value):
    return value.strip().lower()
```

Only explicitly decorated definitions are installed in the corresponding
remote namespace. Keep child-only helpers and imports undecorated. Supported
values cross by value; top-level binary results use raw bridge frames.

## Development rules

- Keep each public path in one declaration. Derive tests and inventory from
  registered definitions instead of repeating URL literals.
- Keep mutually exclusive decisions explicit with `if`/`elif`/`else` when the
  branches cannot both apply.
- Avoid one-use forwarding helpers that merely rename an expression. Retain
  helpers that own policy, isolate a process seam, or provide a useful test
  seam.
- Preserve unrelated uncommitted changes.
- Raise errors with enough context to identify the invalid input or failed
  Fusion operation.

## Verification

Run from the repository root:

```text
python -c "import os,pathlib,sys,unittest; d=str(pathlib.Path('.scratch/deps').resolve()); os.environ['PYTHONPATH']=d+os.pathsep+os.environ.get('PYTHONPATH',''); sys.path.insert(0,d); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(0 if r.wasSuccessful() else 1)"
python -m compileall -q FusionHeadless.py adapter.py bridge.py context.py fusion_host.py server.py routes mcp fusion_support.py extension_state.py routing.py fusion_invocation.py versioning.py cli tests
git diff --check
```

The test suite launches the real child against a narrow fake Fusion host and
covers HTTP behavior, bridge framing, mutation routes, binary responses, MCP,
lifecycle replacement, recovery, and shutdown.

## Current references

- `README.md` — architecture, setup, endpoints, and behavior
- `adapter.py` — Fusion-side lifecycle and UI-thread execution
- `server.py` — child HTTP and MCP protocol handling
- `routing.py` and `routes/` — Fusion-backed HTTP extension interface
- `mcp/registry.py` and `mcp/tools/` — MCP extension interface and implementations
- `tests/` — executable contracts and examples
