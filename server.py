"""Child-owned HTTP service and startup/ownership protocol."""

from __future__ import annotations

import argparse
import inspect
import os
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Annotated, Any, Callable

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
import uvicorn
from pydantic import BaseModel, create_model, Field

from bridge import FramedConnection
from binary_downloads import router as downloads_router
from context import registry
from extension_state import extension_fingerprint
from fusion_invocation import FusionOperationInvoker
from http_delivery import compile_delivery
import routes
import startup
from mcp.endpoint import router as mcp_router
from process_conversation import (ConversationResult, ProcessConversation,
                                  RemoteConversationError)
from routing import RouteDefinition, route_definitions, route_parameters
from versioning import manifest_version


APP_VERSION = manifest_version()
app = FastAPI(title="FusionHeadless", version=APP_VERSION)
_startup_time = time.monotonic()


class ServerRuntime:
    """Own this child's connection, HTTP resources, and replacement lifecycle."""

    def __init__(self, application: FastAPI, conversation: ProcessConversation | None = None) -> None:
        self.application = application
        self._conversation = conversation
        self._restart_in_progress = threading.Event()
        self._restart_lock = threading.Lock()
        self._http_server: uvicorn.Server | None = None
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lockfile = Path(os.getenv("TEMP") or "/tmp") / "FusionHeadless.lock"
        self._owns_lock = False
        self._port: int | None = None
        self._startup_token = f"{os.getpid()}:{id(self)}"
        self._startup_installed = False

    @property
    def restarting(self) -> bool:
        return self._restart_in_progress.is_set()

    def execute_fusion(self, code: str) -> Any:
        if self._conversation is None:
            raise RuntimeError("Fusion bridge is not connected")
        try:
            return self._conversation.execute_fusion(code)
        except RemoteConversationError as error:
            if error.error_type == "SyntaxError":
                raise SyntaxError(str(error)) from error
            raise

    def request_restart(self, *, show_terminal: bool = False) -> None:
        with self._restart_lock:
            if self._restart_in_progress.is_set():
                raise RuntimeError("restart is already in progress")
            self._restart_in_progress.set()
        try:
            if self._conversation is None:
                raise RuntimeError("Fusion bridge is not connected")
            self._conversation.restart("restart", show_terminal=show_terminal)
        except Exception as error:
            if not (isinstance(error, RemoteConversationError)
                    and error.error_type in ("FusionResetError", "ReplacementFingerprintError")):
                self._restart_in_progress.clear()
            raise

    def invoke_fusion(self, operation: Callable[..., Any], query: dict[str, Any]) -> Any:
        """Invoke a registered Fusion operation for child-owned orchestration."""
        if self._conversation is None:
            raise RuntimeError("Fusion bridge is not connected")
        return FusionOperationInvoker(self.execute_fusion).invoke(operation, query)

    def install_startup(self) -> None:
        if not self._startup_installed:
            self._startup_installed = startup.install(
                self,
                f"http://127.0.0.1:{self._port}",
                self._startup_token,
            )

    def uninstall_startup(self) -> None:
        if self._startup_installed:
            startup.uninstall(self, self._startup_token)
            self._startup_installed = False

    def retire_startup(self) -> None:
        startup.cancel(self._startup_token)
        self._startup_installed = False

    def activate_replacement(self) -> None:
        if self._conversation is None:
            raise RuntimeError("Fusion bridge is not connected")
        self._conversation.activate_replacement()

    def stop_accepting(self) -> None:
        """Release the HTTP port on Uvicorn's loop without draining connections."""
        if self._http_server is not None:
            accepting_servers = list(getattr(self._http_server, "servers", ()))
            for accepting_server in accepting_servers:
                accepting_server.close()
        if self._listener is not None:
            self._listener.close()
            self._listener = None

    def start_http_server(self) -> dict[str, bool]:
        if self._port is None:
            raise RuntimeError("server port is not configured")
        self._start_http(self._port)
        try:
            self.install_startup()
        except Exception:
            self.stop_accepting()
            raise
        return {"listening": True, "startup": self._startup_installed}

    def complete_restart(self) -> None:
        """Called after the HTTP response; stop the actual owned HTTP server."""
        if self._http_server is not None:
            self._http_server.should_exit = True
        try:
            startup.cancel(self._startup_token)
            self._startup_installed = False
        finally:
            if self._conversation is not None:
                try:
                    self._conversation.close("requested replacement")
                except (BrokenPipeError, OSError):
                    pass

    def _remove_owned_lock(self) -> None:
        if not self._owns_lock:
            return
        try:
            if self._lockfile.read_text(encoding="utf-8") == str(os.getpid()):
                self._lockfile.unlink()
        except FileNotFoundError:
            pass

    def _start_http(self, port: int) -> None:
        try:
            # Port ownership is authoritative; write the lock only after binding.
            self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._listener.bind(("127.0.0.1", port))
            self._listener.listen()
            self._listener.setblocking(False)
        except Exception:
            if self._listener is not None:
                self._listener.close()
                self._listener = None
            raise

        self._lockfile.parent.mkdir(parents=True, exist_ok=True)
        self._lockfile.write_text(str(os.getpid()), encoding="utf-8")
        self._owns_lock = True
        config = uvicorn.Config(self.application, log_config=None, access_log=False)
        self._http_server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._http_server.run, kwargs={"sockets": [self._listener]}, daemon=True,
        )
        self._thread.start()

    def run(self, port: int, *, standby: bool = False) -> int:
        bridge_input = os.fdopen(os.dup(sys.stdin.fileno()), "rb")
        if os.name == "nt":
            # Native-library initialization can inspect stdin and block behind
            # a pipe read. Keep the bridge on its own descriptor on Windows.
            with open(os.devnull, "rb") as null_input:
                os.dup2(null_input.fileno(), sys.stdin.fileno())
        bridge = FramedConnection(bridge_input, sys.stdout.buffer)
        self._conversation = ProcessConversation(bridge)
        self._port = port
        self._restart_in_progress.clear()
        reader_started = False
        conversation_thread: threading.Thread | None = None
        conversation_errors: list[BaseException] = []

        def serve_conversation() -> None:
            try:
                assert self._conversation is not None
                self._conversation.serve_forever(_handle_server_command)
            except BaseException as error:
                conversation_errors.append(error)

        try:
            if standby:
                conversation_thread = threading.Thread(
                    target=serve_conversation,
                    name="fusionheadless-child-conversation",
                    daemon=True,
                )
                conversation_thread.start()
                reader_started = True
                self._conversation.notify({
                    "command": "standby-ready",
                    "fingerprint": extension_fingerprint(),
                    "startup": False,
                })
            else:
                try:
                    self._start_http(port)
                except OSError as error:
                    if self._lockfile.exists():
                        bridge.write({"command": "quit", "reason": "port already owned"})
                    else:
                        notification = f"FusionHeadless could not bind localhost:{port}: {error}"
                        bridge.write({"command": "exec",
                                      "code": f"if ui is not None:\n    ui.messageBox({notification!r})"})
                        bridge.write({"command": "quit", "reason": "port unavailable"})
                    return 0
                conversation_thread = threading.Thread(
                    target=serve_conversation,
                    name="fusionheadless-child-conversation",
                    daemon=True,
                )
                conversation_thread.start()
                reader_started = True
                fingerprint = extension_fingerprint()
                self._conversation.approve_startup(fingerprint)
                self.install_startup()
                self._conversation.notify({
                    "command": "ready",
                    "fingerprint": fingerprint,
                    "startup": self._startup_installed,
                })
            assert conversation_thread is not None
            conversation_thread.join()
            if conversation_errors:
                raise conversation_errors[0]
            reader_started = False
            return 0
        finally:
            startup.cancel(self._startup_token)
            self._startup_installed = False
            if self._http_server is not None:
                self._http_server.should_exit = True
            if self._thread is not None:
                self._thread.join(timeout=5)
            if self._listener is not None:
                self._listener.close()
            self._remove_owned_lock()
            # A fatal handler failure can leave a blocked reader. Let process
            # exit release that descriptor instead of blocking while closing it.
            if not reader_started:
                bridge_input.close()
            self._conversation = None
            self._http_server = None
            self._listener = None
            self._thread = None
            self._owns_lock = False
            self._port = None


_runtime = ServerRuntime(app)


class RestartRequest(BaseModel):
    """Options controlling the replacement child process."""

    show_terminal: bool = Field(
        default=False,
        description="Launch the replacement child with a visible Windows terminal.",
    )


def _status_unavailable(error: Exception) -> JSONResponse:
    """Return the stable public response for an unavailable Fusion status."""
    return JSONResponse(
        {
            "status": "error",
            "error": "Fusion status unavailable",
            "exception": str(error),
        },
        status_code=503,
    )


@app.middleware("http")
async def reject_requests_during_restart(request: Any, call_next: Callable[..., Any]) -> Any:
    """Fail closed once a replacement has been accepted by Fusion."""
    if _runtime.restarting:
        return JSONResponse(
            {"status": "error", "error": "Restart in progress"},
            status_code=503,
            headers={"Retry-After": "1"},
        )
    return await call_next(request)


@app.get("/status")
def status() -> Any:
    try:
        details = _invoke_fusion_operation(routes.fusion_status, {})
    except Exception as error:
        return _status_unavailable(error)
    result = {
        **details,
        "status": "Server is running",
        "uptime": _uptime(),
        "routes": sorted(
            {route.path for route in app.routes if isinstance(route, APIRoute)}
        ),
    }
    return {"status": "ok", "result": result}


def _uptime() -> str:
    seconds = int(time.monotonic() - _startup_time)
    if seconds >= 86400:
        return f"{seconds // 86400} days, {(seconds % 86400) // 3600} hours, {(seconds % 3600) // 60} minutes"
    elif seconds >= 3600:
        return f"{seconds // 3600} hours, {(seconds % 3600) // 60} minutes"
    elif seconds >= 60:
        return f"{seconds // 60} minutes, {seconds % 60} seconds"
    else:
        return f"{seconds} seconds"


def _invoke_fusion_operation(operation: Callable[..., Any], query: dict[str, Any]) -> Any:
    """Invoke one registered Fusion operation through the child-side seam."""
    return FusionOperationInvoker(_fusion_call).invoke(operation, query)


def _model_values(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    return value.dict(exclude_unset=True)


def _request_model(definition: RouteDefinition) -> type[Any]:
    fields = {}
    for parameter in route_parameters(definition.operation):
        default = ... if parameter.required else parameter.default
        fields[parameter.name] = (
            parameter.annotation,
            Field(default, description=parameter.description),
        )
    return create_model(f"{definition.operation.__name__}Request", **fields)


def _route_handler(definition: RouteDefinition, method: str) -> tuple[Callable[..., Any], dict[str, Any]]:
    parameters = route_parameters(definition.operation)
    request_model = _request_model(definition) if method == "POST" else None
    prepare_response, route_options = compile_delivery(definition, parameters)

    async def handle(**values: Any) -> Any:
        request = values.pop("request")
        if request_model is None:
            arguments = values
        else:
            body = values["body"]
            arguments = _model_values(body)
        try:
            respond = prepare_response(request, arguments)
            result = await run_in_threadpool(
                _invoke_fusion_operation, definition.operation, arguments,
            )
            return respond(result)
        except HTTPException as error:
            return JSONResponse({"status": "error", "error": error.detail}, status_code=error.status_code)
        except Exception as error:
            return JSONResponse({"status": "error", "error": str(error)}, status_code=500)

    handle.__name__ = f"{definition.operation.__name__}_{method.lower()}"
    handle.__doc__ = definition.operation.__doc__
    if request_model is None:
        exposed = [] if len(definition.methods) > 1 else [
            inspect.Parameter(
                parameter.name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=parameter.annotation,
                default=Query(
                    ... if parameter.required else parameter.default,
                    description=parameter.description,
                ),
            )
            for parameter in parameters
        ]
    else:
        exposed = [inspect.Parameter(
            "body",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=request_model,
            default=Body(...),
        )]
    exposed.append(inspect.Parameter("request", inspect.Parameter.KEYWORD_ONLY,
                                     annotation=Request))
    handle.__signature__ = inspect.Signature(exposed)  # type: ignore[attr-defined]
    setattr(handle, "__fusionheadless_route__", definition)
    return handle, route_options


for definition in route_definitions():
    for method in definition.methods:
        handler, route_options = _route_handler(definition, method)
        app.add_api_route(
            definition.path,
            handler,
            methods=[method],
            summary=(definition.operation.__doc__ or definition.operation.__name__)
            .strip().splitlines()[0],
            **route_options,
        )


@app.post("/restart")
async def restart(
    background: BackgroundTasks,
    options: Annotated[RestartRequest, Body()] = RestartRequest(),
) -> Any:
    try:
        await run_in_threadpool(_runtime.request_restart, show_terminal=options.show_terminal)
        _runtime.stop_accepting()
        await run_in_threadpool(_runtime.activate_replacement)
        return {"status": "ok", "result": {"server": "Restarted"}}
    except Exception as error:
        return JSONResponse({"status": "error", "error": str(error)}, status_code=500)
    finally:
        if _runtime.restarting:
            background.add_task(_runtime.complete_restart)


def _fusion_call(code: str) -> Any:
    """Execution seam shared by HTTP, MCP, and registered server callbacks."""
    return _runtime.execute_fusion(code)


@app.post("/exec")
async def execute(
    code: Annotated[
        str,
        Body(embed=True, description="Python function body to execute in Fusion."),
    ],
) -> Any:
    try:
        return await run_in_threadpool(_fusion_call, code)
    except Exception as error:
        status = 400 if isinstance(error, SyntaxError) else 500
        return JSONResponse({"error": str(error)}, status_code=status)


app.state.fusion_invoker = FusionOperationInvoker(_fusion_call)
app.include_router(mcp_router)
app.include_router(downloads_router)


def _handle_server_command(message: dict[str, Any]) -> ConversationResult:
    """Serve one inbound command while the adapter is in Fusion code."""
    if message.get("command") == "quit":
        return ConversationResult(close=True)
    if message.get("command") == "start_http_server":
        return ConversationResult(_runtime.start_http_server())
    if message.get("command") == "retire_startup":
        _runtime.retire_startup()
        return ConversationResult({"retired": True})
    if message.get("command") == "shutdown":
        try:
            _runtime.uninstall_startup()
            return ConversationResult({"action": "stopped"}, close=True)
        except Exception as error:
            return ConversationResult(
                error=str(error), error_type=type(error).__name__, close=True
            )
    if message.get("command") != "call":
        raise RuntimeError(f"unexpected server command: {message!r}")
    name = message.get("name")
    definition = registry.server.get(name)
    if definition is None:
        raise RuntimeError(f"unregistered server definition: {name!r}")
    return ConversationResult(
        definition.value(*message.get("args", []), **message.get("kwargs", {}))
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--standby", action="store_true")
    args = parser.parse_args()
    return _runtime.run(args.port, standby=args.standby)


if __name__ == "__main__":
    raise SystemExit(main())
