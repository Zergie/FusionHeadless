---
name: fusionheadless-new-route
description: Add or change a Fusion-backed HTTP route in FusionHeadless using its colocated api_route declaration.
argument-hint: Route path and the Fusion operation it should perform
---

# Add a Fusion-backed HTTP route

Add, remove, or rename a normal Fusion-backed endpoint in one module under `routes/`. For a new module,
import its operation explicitly in `routes/__init__.py`. Do not edit `server.py`; it installs every declaration
returned by `routing.route_definitions()`.

## Decorator interface

Import `api_route`, `ApiParameter`, and, for binary responses,
`BinaryResponse` from `routing.py`. Import `Annotated` from `typing` when a
parameter needs public help text:

```python
@api_route(
    path,
    methods=("GET",),
    binary=None,
)
```

- `path` is the single source of truth for the public URL.
- `methods` is a tuple of accepted HTTP methods. It defaults to GET. Use GET
  for read-only work and POST for all other operations. `/parameter` and `/scripts`
  intentionally support both.
- `binary` is optional response metadata. When present, the operation returns
  bytes and the child applies its media type and content-disposition headers.

The decorated function accepts one immutable `context` object first, followed
by individually typed public parameters. The signature drives FastAPI's
OpenAPI document and therefore the shipped `fusion_cli`; do not add CLI-only
route metadata. Use `Annotated[..., ApiParameter("help text")]` for parameter
documentation. Use `context.app`, `context.ui`, and `context.adsk` as needed.

## Current binary-route example

The `/render` declaration in `routes/render.py` is the reference pattern:

```python
@api_route(
    "/render",
    methods=("POST",),
    binary=BinaryResponse("image/png", "render.png", disposition="inline"),
)
def render_route(
    context: Any,
    view: Annotated[str | None, ApiParameter("Named Fusion view.")] = None,
    width: Annotated[int, ApiParameter("Output width in pixels.")] = 1280,
) -> bytes:
    """Render the active viewport and return an exact PNG byte payload."""
    # Produce and return the PNG bytes.
```

For a JSON response, omit `binary` and return a JSON-compatible value. The
child wraps successful Fusion-backed JSON results in its standard status
envelope. Raise a contextual exception for invalid parameters or failed Fusion
operations; the child converts it to the route's error response.

## Workflow

1. Read nearby implementations under `routes/` and identify reusable
   policy helpers.
2. Add one decorated function. Put the URL, methods, and optional
   binary metadata only in its decorator.
3. Import new operation modules in `routes/__init__.py`.
4. Add behavior tests under `tests/`. Obtain the URL from the registered route
   definition when a test needs it; do not duplicate the path literal.
5. Verify that `server.py` and the route registry implementation were not changed.

Do not create a second route registry, manually add a FastAPI decorator in
`server.py`, or compare request paths in conditionals. Built-in child-only
endpoints are a separate concern and are not covered by this skill.

## Verification

Run the complete suite from the repository root:

```text
python -c "import os,pathlib,sys,unittest; d=str(pathlib.Path('.scratch/deps').resolve()); os.environ['PYTHONPATH']=d+os.pathsep+os.environ.get('PYTHONPATH',''); sys.path.insert(0,d); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(0 if r.wasSuccessful() else 1)"
python -m compileall -q FusionHeadless.py adapter.py bridge.py context.py fusion_host.py server.py routes mcp fusion_support.py extension_state.py routing.py fusion_invocation.py versioning.py cli tests
git diff --check
```

Confirm that the new route appears in `routing.route_definitions()`, accepts
the declared method, exposes its typed parameters and help through OpenAPI,
receives the unified Fusion context, and preserves the expected JSON or binary
response contract.

## References

- `routing.py` — `api_route`, `RouteDefinition`, and `BinaryResponse`
- `routes/` — Fusion-backed route declarations and focused helper modules
- `server.py` — automatic installation and response handling
- `tests/test_contract.py` — registration contract
- `tests/test_binary_routes.py` — binary response examples
- `tests/test_mutation_routes.py` — mutation route examples
