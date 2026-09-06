# Architecture and development

[← FusionHeadless](../README.md)

FusionHeadless exposes Fusion 360 automation on `localhost:5000`. The add-in
is split into two processes:

- The Fusion adapter (`adapter.py`) launches and supervises the child, owns
  the framed bridge, and dispatches Fusion API work onto Fusion's UI thread.
- The FastAPI child (`server.py`) owns the HTTP listener, request parsing,
  responses, automatic route installation, and MCP endpoint.
- Fusion-backed routes declare their complete HTTP interface beside their
  implementation in `fusion_routes.py`.
- `extension_state.py` owns extension replacement and the fingerprint used by
  Fusion and the child to verify that their loaded extensions match.

Only the child binds HTTP port 5000. The child first claims the port, then
creates the global lock file and sends the `ready` protocol message. A stale
lock file does not prevent a successful bind. The child removes a lock file it
owns during orderly shutdown. A port conflict with an existing lock file ends
with `quit`; a conflict without one asks the adapter to show the operating
system error in a Fusion message box before quitting.


## Embedding the adapter

Start the adapter from the add-in entry point, or use `FusionAdapter` directly:

```
from adapter import FusionAdapter

adapter = FusionAdapter(host=fusion_host)
adapter.start()
try:
    # HTTP clients can use http://127.0.0.1:5000 here.
    ...
finally:
    adapter.stop()
```

## Context bridge

Server execution is the default. Explicit decorators define the public
cross-process surface:

```
from context import fusion, server

@fusion
def active_document_name(app):
    return app.activeDocument.name

@server
def server_helper(value):
    return value.upper()
```

Only `@fusion` definitions are installed in the restricted Fusion namespace;
unmarked helpers and imports stay child-local. `@server` definitions are
explicit callbacks available to Fusion code. The bridge permits
`server → Fusion → server`: a dedicated reader delivers replies while command
execution waits on Fusion's UI thread. Fusion execution remains serialized.
Server callbacks cannot invoke Fusion again or request a restart; these nested
requests raise `NestedFusionCallError` before waiting on the original call.
Independent requests wait until the active Fusion call finishes.

Inside a registered Fusion operation, use
`context.call_server(decorated_server_function, *args, **kwargs)` to invoke a
child function. Only `@server` registrations are accepted, and callback access
is scoped to the active UI-thread invocation. Child-only dependencies should
be imported inside the server function so Fusion never loads them.
On Windows, the child reserves its input pipe for the bridge and redirects
standard input to the null device. This allows native libraries to initialize
while the bridge reader waits for messages.

Supported values cross by value. Decorated class instances carry their class
identity and recursively supported `__dict__` state; reconstruction bypasses
`__init__`. Lists, tuples, dictionaries, JSON scalars, and nested registered
objects are supported. Cycles, unregistered custom objects, and nested binary
values are rejected. Top-level binary results use raw `B<len>:` frames.

## Diagnostics and recovery

Bridge frames are length-prefixed: JSON uses `J<len>:` followed by UTF-8 bytes,
and top-level binary uses `B<len>:` followed by raw bytes. Protocol failures,
incomplete frames, and child execution failures are reported as errors rather
than being silently interpreted.

After a child that was ready exits unexpectedly, the adapter makes at most
three automatic restart attempts, delaying attempts two and three. A new
`ready` resets the failure count. After three failures Fusion displays a
Retry/Cancel prompt: Retry starts a fresh cycle, while Cancel stops
supervision. Intentional `quit`, requested lifecycle replacement, lock
ownership conflicts, and add-in shutdown are not treated as crashes.

The adapter tracks these transitions with explicit lifecycle phases. Each
child keeps its conversation and cleanup together, so an old child's cleanup
cannot affect its replacement. Concurrent startup callers share one startup
result; shutdown also covers a child that is still being launched.
In the child, `ServerRuntime` owns the connection, listener, Uvicorn instance,
and lockfile cleanup. Restart completion stops that same Uvicorn instance
after sending the response.

## Verification

Run the process-level suite from the repository root:

```
python -c "import os,pathlib,sys,unittest; d=str(pathlib.Path('.scratch/deps').resolve()); os.environ['PYTHONPATH']=d+os.pathsep+os.environ.get('PYTHONPATH',''); sys.path.insert(0,d); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(0 if r.wasSuccessful() else 1)"
python -m compileall -q FusionHeadless.py adapter.py bridge.py context.py extension_state.py fusion_host.py server.py fusion_routes.py mcp_tools.py routing.py fusion_invocation.py versioning.py cli tests
git diff --check
```

The tests use a narrow fake Fusion host and launch the real child process, so
they verify HTTP responses, bridge frames, Fusion state changes, binary bodies,
MCP calls, lifecycle replacement, crash recovery, and shutdown without a
Fusion installation.
