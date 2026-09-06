# HTTP API reference

[← FusionHeadless](../README.md)

The child exposes the migrated public routes:

```
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

```
from routing import api_route

@api_route("/example")
def example_route(context, name: str | None = None):
    return {"document": context.app.activeDocument.name}
```

```
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
