from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request as HttpRequest, urlopen

from fastapi import Request
from fastapi.routing import APIRoute
import uvicorn

import server
from mcp.endpoint import mcp
import routes
from tests.harness import route_path


class FastApiServerTests(unittest.TestCase):
    def test_http_remains_responsive_while_waiting_for_fusion(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        instance = uvicorn.Server(
            uvicorn.Config(server.app, log_config=None, access_log=False)
        )
        thread = threading.Thread(
            target=instance.run, kwargs={"sockets": [listener]}, daemon=True,
        )

        def request(path, payload=None, timeout=5):
            data = None if payload is None else json.dumps(payload).encode()
            request = HttpRequest(
                origin + path, data=data, headers={"Content-Type": "application/json"},
            )
            try:
                response = urlopen(request, timeout=timeout)
            except HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        cases = (
            (route_path(routes.bodies_route), None, 200),
            (route_path(server.execute), {"code": "return {}"}, 200),
            (route_path(mcp), {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "list_open_documents", "arguments": {}},
            }, 200),
            (route_path(server.restart), {}, 503),
        )
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not instance.started:
                if time.monotonic() >= deadline:
                    self.fail("Uvicorn did not start within five seconds")
                time.sleep(0.01)
            for path, payload, expected_status in cases:
                with self.subTest(path=path):
                    entered, release = threading.Event(), threading.Event()

                    def wait_for_fusion(*args, **kwargs):
                        entered.set()
                        if not release.wait(5):
                            raise TimeoutError("test did not release Fusion")
                        return {}

                    conversation = Mock()
                    conversation.execute_fusion.side_effect = wait_for_fusion
                    conversation.restart.side_effect = wait_for_fusion
                    runtime = server.ServerRuntime(server.app, conversation)
                    with (
                        patch.object(server, "_runtime", runtime),
                        patch.object(server, "_invoke_fusion_operation", side_effect=wait_for_fusion),
                        ThreadPoolExecutor() as pool,
                    ):
                        pending = pool.submit(request, path, payload)
                        try:
                            self.assertTrue(entered.wait(2), "request never reached Fusion")
                            status, result = request(route_path(mcp), {
                                "jsonrpc": "2.0", "id": 2, "method": "ping",
                            }, timeout=1)
                            self.assertEqual(status, expected_status)
                            if expected_status == 200:
                                self.assertEqual(result, {"jsonrpc": "2.0", "id": 2, "result": {}})
                            else:
                                self.assertEqual(result["error"], "Restart in progress")
                            self.assertFalse(pending.done(), "Fusion should still be waiting")
                        finally:
                            release.set()
                            self.assertEqual(pending.result(timeout=3)[0], 200)
        finally:
            instance.should_exit = True
            thread.join(timeout=5)
            listener.close()
        self.assertFalse(thread.is_alive())

    def test_lifecycle_routes_expose_only_their_supported_methods(self) -> None:
        routes = {
            route.path: route
            for route in server.app.routes
            if isinstance(route, APIRoute)
        }

        self.assertNotIn("/reload", routes)
        self.assertEqual(routes["/restart"].methods, {"POST"})
        self.assertEqual(routes["/status"].methods, {"GET"})

    def test_requests_are_rejected_while_a_restart_is_in_progress(self) -> None:
        request = Request({
            "type": "http",
            "method": "GET",
            "path": "/status",
            "headers": [],
        })

        async def call_next(_: Request):
            self.fail("a restarting child must not serve new requests")

        runtime = server.ServerRuntime(server.app, Mock())
        runtime.request_restart()
        with patch.object(server, "_runtime", runtime):
            response = asyncio.run(server.reject_requests_during_restart(request, call_next))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "1")

    def test_openapi_exposes_typed_query_and_json_body_contracts(self) -> None:
        document = server.app.openapi()

        self.assertEqual(document["info"]["version"], "0.2.0")
        self.assertEqual(set(document["paths"]["/files"]), {"get"})
        self.assertEqual(set(document["paths"]["/render"]), {"post"})
        self.assertEqual(set(document["paths"]["/parameter"]), {"get", "post"})
        files = document["paths"]["/files"]["get"]["parameters"]
        self.assertEqual([parameter["name"] for parameter in files],
                         ["active", "id", "name"])
        render = document["paths"]["/render"]["post"]
        self.assertIn("application/json", render["requestBody"]["content"])
        self.assertIn("image/png", render["responses"]["200"]["content"])
        restart_schema = document["paths"]["/restart"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        if "$ref" in restart_schema:
            restart_schema = document["components"]["schemas"][
                restart_schema["$ref"].rsplit("/", 1)[1]
            ]
        self.assertEqual(restart_schema["properties"]["show_terminal"]["type"], "boolean")

    def test_uptime_boundaries(self) -> None:
        cases = {
            59: "59 seconds",
            60: "1 minutes, 0 seconds",
            3599: "59 minutes, 59 seconds",
            3600: "1 hours, 0 minutes",
            86400: "1 days, 0 hours, 0 minutes",
        }
        for seconds, expected in cases.items():
            with (
                self.subTest(seconds=seconds),
                patch.object(server, "_startup_time", 0),
                patch("server.time.monotonic", return_value=seconds),
            ):
                self.assertEqual(server._uptime(), expected)

    def test_unknown_mcp_method_returns_method_not_found(self) -> None:
        result = asyncio.run(mcp({
            "jsonrpc": "2.0", "id": 7, "method": "unknown"
        }, Request({"type": "http", "app": server.app})))

        self.assertEqual(result["error"], {
            "code": -32601,
            "message": "Method not found: unknown",
        })

    def test_status_returns_stable_error_when_fusion_bridge_is_unavailable(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        instance = uvicorn.Server(
            uvicorn.Config(server.app, log_config=None, access_log=False)
        )
        thread = threading.Thread(
            target=instance.run,
            kwargs={"sockets": [listener]},
            daemon=True,
        )
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    with urlopen(
                        f"http://127.0.0.1:{port}{route_path(server.status)}"
                    ):
                        self.fail("status must not report healthy without Fusion")
                except HTTPError as error:
                    self.assertEqual(error.code, 503)
                    self.assertEqual(json.load(error), {
                        "status": "error",
                        "error": "Fusion status unavailable",
                        "exception": "Fusion bridge is not connected",
                    })
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        self.fail("Uvicorn did not start within five seconds")
                    time.sleep(0.01)
        finally:
            instance.should_exit = True
            thread.join(timeout=5)
            listener.close()

        self.assertFalse(thread.is_alive())

    def test_connected_status_preserves_main_shape_with_v2_values(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        instance = uvicorn.Server(
            uvicorn.Config(server.app, log_config=None, access_log=False)
        )
        thread = threading.Thread(
            target=instance.run,
            kwargs={"sockets": [listener]},
            daemon=True,
        )
        expected_routes = [
            "/bodies", "/components", "/document", "/eval", "/exec",
            "/export", "/files", "/mcp", "/parameter", "/projects",
            "/render", "/restart", "/scripts", "/select", "/status",
        ]
        from binary_downloads import download_binary
        expected_routes = sorted([*expected_routes, route_path(download_binary)])

        with (
            patch.object(server, "_uptime", return_value="12 seconds"),
            patch.object(server, "_invoke_fusion_operation", return_value={
                "version": "Autodesk Fusion v2.0",
                "python": "3.14.0",
                "paths": {"applicationPath": "C:/Fusion"},
            }),
        ):
            thread.start()
            try:
                with urlopen(
                    f"http://127.0.0.1:{port}{route_path(server.status)}",
                    timeout=5,
                ) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), {
                        "status": "ok",
                        "result": {
                            "status": "Server is running",
                            "uptime": "12 seconds",
                            "version": "Autodesk Fusion v2.0",
                            "python": "3.14.0",
                            "paths": {"applicationPath": "C:/Fusion"},
                            "routes": expected_routes,
                        },
                    })
            finally:
                instance.should_exit = True
                thread.join(timeout=5)
                listener.close()

        self.assertFalse(thread.is_alive())

    def test_status_returns_stable_error_with_fusion_exception(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.setblocking(False)
        port = listener.getsockname()[1]
        instance = uvicorn.Server(
            uvicorn.Config(server.app, log_config=None, access_log=False)
        )
        thread = threading.Thread(
            target=instance.run,
            kwargs={"sockets": [listener]},
            daemon=True,
        )

        with (
            patch.object(
                server,
                "_invoke_fusion_operation",
                side_effect=RuntimeError("Fusion API is busy"),
            ),
        ):
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        urlopen(
                            f"http://127.0.0.1:{port}{route_path(server.status)}",
                            timeout=5,
                        )
                        self.fail("status must not hide a failed Fusion query")
                    except HTTPError as error:
                        self.assertEqual(error.code, 503)
                        self.assertEqual(json.load(error), {
                            "status": "error",
                            "error": "Fusion status unavailable",
                            "exception": "Fusion API is busy",
                        })
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self.fail("Uvicorn did not start within five seconds")
                        time.sleep(0.01)
            finally:
                instance.should_exit = True
                thread.join(timeout=5)
                listener.close()

        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
