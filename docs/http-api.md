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

## Export to an application URL

`POST /export` accepts an optional `redirect_url` template. For example:

```json
{
  "format": "stl",
  "redirect_url": "orcaslicer://open?file={url}"
}
```

The template must be an absolute URL containing exactly one literal `{url}`.
Other application schemes are supported as well. After export succeeds, the
server replaces `{url}` with a percent-encoded local download URL and responds
with `303 See Other` and a `Location` header. Omitting `redirect_url`, or setting
it to `null`, preserves the ordinary binary response. Invalid templates return
`422` before Fusion exports anything.

The child retains the exported bytes in memory for **five minutes**, with a
random token at `GET /downloads/{token}/{filename}`. The first GET atomically
consumes the token; subsequent requests return `404`. An interrupted download
also consumes the token, so retry by exporting again. Unclaimed exports are
automatically removed at expiry; restarting the child invalidates all tokens.
Redirects and downloads use `Cache-Control: no-store`.

The token maps directly to the file bytes and explicit filename metadata.
The server generates the response header and URL from that filename; it does
not reconstruct filenames from headers. Expiry runs on the HTTP event loop.

Open the redirect target through a browser navigation or the operating system's
URL handler. Following it with `fetch()` or an HTTP CLI does not launch an
application. The application must have its URL scheme registered and be able
to fetch the loopback URL on the same computer; browsers may prompt before
opening it. No application is launched by the server itself.

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
tools, and extension-module state are discarded, then the `routes` and `mcp.tools`
packages, their submodules, and shared `fusion_support` helpers are imported
fresh. Their explicit package imports determine which operations are loaded.
The response is completed before the child exits. New requests receive `503` with `Retry-After: 1` until the replacement
is ready with a matching extension fingerprint. Send
`{"show_terminal": true}` to start the replacement child with a visible
Windows terminal for debugging; the default is hidden.

`/reload` no longer exists, and `GET /restart` returns `404`. Changes to
adapter infrastructure (`adapter.py`, `bridge.py`, `context.py`, `routing.py`,
`extension_state.py`, or `fusion_host.py`) still require restarting the Fusion
add-in. If a context reset import fails, Fusion keeps no partial registrations, the child exits,
and the adapter retries through its normal recovery budget.
