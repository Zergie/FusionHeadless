# FusionHeadless

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

## Setup

Create the project virtual environment and install the pinned child dependencies.
On Windows (including Git Bash):

```text
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

On macOS:

```text
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The add-in starts the child with `.venv/Scripts/python.exe` on Windows or
`.venv/bin/python` on macOS. If the add-in reports that setup is incomplete,
complete the steps above and restart Fusion.

The shipped command-line client has its own small environment. Create it once
and install its pinned dependencies:

```text
py -3 -m venv cli\.venv
cli\.venv\Scripts\python.exe -m pip install -r cli\requirements.txt
```

On macOS or Linux, use `python3 -m venv cli/.venv` and
`cli/.venv/bin/python -m pip install -r cli/requirements.txt` instead.

Start the adapter from the add-in entry point, or use `FusionAdapter` directly:

```python
from adapter import FusionAdapter

adapter = FusionAdapter(host=fusion_host)
adapter.start()
try:
    # HTTP clients can use http://127.0.0.1:5000 here.
    ...
finally:
    adapter.stop()
```

## HTTP API

The child exposes the migrated public routes:

```text
/status       /components  /bodies      /projects
/files        /document    /parameter   /select
/export       /render      /eval        /exec
/restart      /scripts     /mcp
```

Read-only routes use `GET`: `/status`, `/components`, `/bodies`, `/projects`,
`/files`, and `/scripts`. Mutating or computational routes use `POST` with a JSON object:
`/document`, `/select`, `/export`, `/render`, `/eval`, `/exec`, `/restart`, and
`/mcp`. `/parameter` and `/scripts` deliberately support both: `GET` lists their
resources and `POST` changes them. `/parameter` updates values with a `set` array
containing `NAME=EXPRESSION` strings. `/scripts` returns separate `scripts` and
`addons` arrays from Fusion's script collection. It accepts `enable` and `disable`
arrays of add-in Script IDs, which start/stop the add-ins and set whether each runs
on Fusion startup. Fusion documents this collection as
[`Application.scripts`](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Scripts.htm),
so the endpoint is named `/scripts`.

This typed API is not wire-compatible with the former free-form query/body
contract. FastAPI validates every declared parameter and publishes the exact
contract at `/openapi.json`. `/exec` accepts `{"code": "..."}`; its code is a
function body, so use `return` to produce a result. Single-line and multiline
code are supported.

A Fusion-backed route is added, removed, or changed in one place. The
built-in-only `@api_route` decorator registers the Fusion operation and gives
the FastAPI child everything it needs to install the HTTP route:

```python
from routing import api_route

@api_route("/example")
def example_route(context, name: str | None = None):
    return {"document": context.app.activeDocument.name}
```

```text
POST /exec
Content-Type: application/json

{"code":"value = app.activeDocument\nreturn value.name"}
```

`/eval` retains expression evaluation and optional depth-limited Fusion-object
serialization. Both endpoints execute in Fusion and return useful syntax or
runtime errors. `POST /restart` resets the Fusion extension context before
replacing the FastAPI child: runtime registrations, route declarations, MCP
tools, and extension-module state are discarded, then `fusion_routes` and
`mcp_tools` are imported fresh. The response is completed before the child
exits. New requests receive `503` with `Retry-After: 1` until the replacement
is ready with a matching extension fingerprint. Send
`{"show_terminal": true}` to start the replacement child with a visible
Windows terminal for debugging; the default is hidden.

`/reload` no longer exists, and `GET /restart` returns `404`. Changes to
adapter infrastructure (`adapter.py`, `bridge.py`, `context.py`, `routing.py`,
`extension_state.py`, or `fusion_host.py`) still require restarting the Fusion
add-in. If a context reset import fails, Fusion keeps no partial registrations, the child exits,
and the adapter retries through its normal recovery budget.

## Command-line client

`fusion_cli` derives its verbs and switches from the server's OpenAPI document;
route signatures in `fusion_routes.py` remain the single source of truth. The
schema is cached locally by normalized server origin and the `0.2.0` version in
`FusionHeadless.manifest`. It is fetched when absent, with `cli --refresh`,
or once after an unknown verb or switch. Set `FUSION_HEADLESS_URL` or pass
`--base-url` to target a different origin.

Windows Command Prompt examples:

```text
cli\fusion_cli.cmd status
cli\fusion_cli.cmd cli --refresh
cli\fusion_cli.cmd render --view Home --hide "Body 1" --no-anti-aliased --output render.png
cli\fusion_cli.cmd parameter --set d1=3.5 --set "d2=4 mm"
cli\fusion_cli.cmd exec --file operation.py
```

On macOS or Linux, use `cli/fusion_cli.sh`. PowerShell users can run the
DynamicParam wrapper for native PowerShell switches and completion:

```powershell
& .\cli\fusion_cli.ps1 render -View Home -Hide 'Body 1' -IsAntiAliased:$false -Output render.png
& .\cli\fusion_cli.ps1 parameter -Set 'd1=3.5','d2=4 mm'
& .\cli\fusion_cli.ps1 cli -Refresh
```

Use `--raw` for only the unwrapped endpoint result, `--query` to transform that
result with JMESPath, and `--output` to write it.
Binary responses use the server's `Content-Disposition` filename when no
output path is supplied. Existing identical output files are left untouched.

## Print-oriented STL export

Apply an appearance to the planar face of each printable body that should
contact the print bed. Pass its name explicitly in `orient`, for example:

```json
{"format": "stl", "component": "Bracket", "body": ["Body1"], "orient": "Print Bed"}
```

Send this JSON to `POST /export`, or use the generated CLI option:

```text
cli/fusion_cli.cmd export --format stl --component Bracket --body Body1 --orient "Print Bed" --output bracket.stl
```

Matching uses a case-sensitive substring, so `Print Bed Blue` also matches.
There is no default appearance name. Omit `orient` or use `"orient": null`
to export an STL in its original orientation. Booleans and blank appearance
names are rejected.
String values are always appearance names, including `"true"` and `"false"`.

PowerShell accepts `-Orient 'Print Bed'`.
Refresh an existing CLI schema
cache with `cli --refresh` after updating the add-in. Git Bash can call the
CLI Python script using its Windows virtual-environment interpreter directly.

The face's outward normal is rotated to negative Z (including reversed Fusion
surface normals). The exported mesh is centered in X/Y and its minimum Z is
placed at zero. The marked face must actually lie on that supporting plane;
geometry protruding below it is rejected. The output is binary STL with
millimeter coordinates, unchanged scale and triangle ordering. X then Y
rotation follows the existing printable-body convention; no extra yaw or
automatic packing is applied.

All exports restore body and occurrence visibility after success or failure.
Component and body selections are validated before visibility changes begin.
Other formats ignore `orient` and preserve their existing export geometry.
Oriented STL export supports a single body or a rigid
group of bodies in one component.
Omitting `body` includes the component's own bodies only when it has no child
occurrences. For assemblies, choose explicit body names in one component.
Each selected body needs a marked planar face. Multiple marked faces must have
matching outward normals and lie on the same plane within mesh precision;
otherwise export the bodies separately. Curved contact faces and missing
markings produce contextual errors.

Fusion reads the markings and exports the selected native geometry on its UI
thread. The existing child then processes the temporary STL with `numpy-stl`;
the model is never rotated, and temporary visibility changes are restored even
on failure. Install/update the repository's `requirements.txt` in `.venv` to
enable this feature. No `stl_cmd`, global Python packages, or NumPy installation
inside Fusion is required. Changes to the new context callback support require
restarting the add-in once; subsequent route changes use the normal restart.

The reusable child-side module is `stl_orientation.orient_stl(data, planes)`.
It accepts binary STL bytes and contact-plane dictionaries containing an
outward `normal`, a `point` in STL millimeters, and an optional diagnostic
`label`, then returns oriented binary STL bytes. It has no Fusion dependency.

## Context bridge

Server execution is the default. Explicit decorators define the public
cross-process surface:

```python
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

```text
python -c "import os,pathlib,sys,unittest; d=str(pathlib.Path('.scratch/deps').resolve()); os.environ['PYTHONPATH']=d+os.pathsep+os.environ.get('PYTHONPATH',''); sys.path.insert(0,d); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(0 if r.wasSuccessful() else 1)"
python -m compileall -q FusionHeadless.py adapter.py bridge.py context.py extension_state.py fusion_host.py server.py fusion_routes.py mcp_tools.py routing.py fusion_invocation.py versioning.py cli tests
git diff --check
```

The tests use a narrow fake Fusion host and launch the real child process, so
they verify HTTP responses, bridge frames, Fusion state changes, binary bodies,
MCP calls, lifecycle replacement, crash recovery, and shutdown without a
Fusion installation.
