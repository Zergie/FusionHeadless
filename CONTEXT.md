# FusionHeadless context

## Fusion operation

A registered function that executes in Fusion through FusionHeadless. A Fusion
operation receives a request query and a Fusion context, and returns its native
value. HTTP routes and MCP tools are delivery adapters for Fusion operations.

## Fusion context

The immutable execution context supplied by the Fusion adapter to every Fusion
operation. It exposes the live `app`, `ui`, and `adsk` values without requiring
operations to know positional context conventions.

## Fusion-operation invocation

The child-side module that validates a registered Fusion operation, binds its
Fusion context, dispatches it through the process seam, and returns the native
execution result. It does not own HTTP or MCP delivery formatting, nor the raw
`/exec` operation.

## Extension state

The loaded set of Fusion route and MCP tool modules and their registrations.
`extension_state.py` owns replacement of that set and the fingerprint used to
check that Fusion and its child loaded matching extensions. Replacement clears
runtime declarations and leaves no extension registrations after a failure;
the Fusion adapter owns UI-thread scheduling and recovery decisions.

## Child lifecycle

The Fusion adapter's supervision of one child at a time. Explicit phases
distinguish startup, running, replacement, extension reset, fingerprint
mismatch, recovery, and completion. One startup result is shared by callers;
each launched child owns its conversation and process-handle cleanup. A stop
request also applies to a child whose launch has not finished yet.

## Server runtime

The child-side owner of the conversation, HTTP listener, Uvicorn instance,
serving thread, and lockfile ownership. HTTP handlers ask this runtime to
execute Fusion work or request replacement. The runtime rejects new requests
during replacement and closes its connection and HTTP server after the
response completes; a rejected extension reset still requires replacement.

## Temporary Fusion effects

The state changes and output files owned temporarily by one Fusion operation.
The module in `routes/_temporary.py` captures original values before mutation
and attempts every restoration and file cleanup, preserving failure context.
Each operation chooses which effects are temporary; intentional persistent
render changes are outside this module's ownership.
