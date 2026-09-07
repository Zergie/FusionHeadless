from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
import socket
import weakref
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from adapter import FusionAdapter
from fastapi import FastAPI, HTTPException, Request as ASGIRequest

from binary_downloads import Download, DownloadStore, download_binary, redirect_download, router
import routes
from tests.harness import route_path
from tests.test_binary_routes import BinaryHost


class ExportRedirectTests(unittest.TestCase):
    def setUp(self):
        self.host = BinaryHost()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.adapter = FusionAdapter(host=self.host, port=self.port)
        self.assertTrue(self.adapter.start(timeout=5))
        self.addCleanup(self.adapter.stop)

    def export(self, template):
        request = Request(
            self.origin + route_path(routes.export_route),
            data=json.dumps({"format": "stl", "redirect_url": template}).encode(),
            headers={"Content-Type": "application/json", "Host": "untrusted.example"},
        )
        try:
            return urlopen(request, timeout=5)
        except HTTPError as error:
            # urllib intentionally refuses to follow custom URL schemes.
            return error

    def test_generic_redirect_downloads_exact_export_once(self):
        for scheme in ("orcaslicer", "prusaslicer", "custom-app"):
            with self.subTest(scheme=scheme):
                with self.export(scheme + "://open?file={url}") as response:
                    self.assertEqual(response.status, 303)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    location = response.headers["Location"]
                self.assertTrue(location.startswith(scheme + "://open?file=http%3A%2F%2F"))
                download_url = unquote(location.split("file=", 1)[1])
                self.assertTrue(download_url.startswith(self.origin + "/"))
                self.assertTrue(urlsplit(download_url).path.endswith("/export.stl"))
                with urlopen(download_url, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Content-Disposition"], 'attachment; filename="export.stl"')
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.read(), b"\x00Fusion\nstl" + bytes(range(256)))
                with self.assertRaises(HTTPError) as raised:
                    urlopen(download_url, timeout=5)
                self.assertEqual(raised.exception.code, 404)
                raised.exception.close()

    def test_invalid_template_fails_before_fusion_export(self):
        for template in ("", "relative/{url}", "custom://open", "custom:{url}{url}",
                         "custom:{other}/{url}", "custom:{url}\r\nInjected:yes"):
            with self.subTest(template=template), self.export(template) as response:
                self.assertEqual(response.status, 422)
                self.assertIn("redirect_url", json.load(response)["error"])
                self.assertIsNone(self.host.app.activeProduct.exportManager.format)

    def test_null_redirect_preserves_binary_response(self):
        with self.export(None) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"\x00Fusion\nstl" + bytes(range(256)))

    def test_concurrent_http_downloads_have_exactly_one_winner(self):
        with self.export("custom://open?file={url}") as response:
            download_url = unquote(response.headers["Location"].split("file=", 1)[1])

        def retrieve(_):
            try:
                response = urlopen(download_url, timeout=5)
            except HTTPError as error:
                response = error
            with response:
                return response.status

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(retrieve, range(8)))
        self.assertEqual(sorted(statuses), [200] + [404] * 7)

    def test_schema_documents_template_and_redirect(self):
        with urlopen(self.origin + "/openapi.json", timeout=5) as response:
            schema = json.load(response)
        operation = schema["paths"][route_path(routes.export_route)]["post"]
        self.assertIn("303", operation["responses"])
        model = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
        self.assertIn("{url}", schema["components"]["schemas"][model]["properties"]["redirect_url"]["description"])


class DownloadLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_lifetime_is_five_minutes(self):
        store = DownloadStore()
        self.addCleanup(store.clear)
        file = Download(b"data", "application/octet-stream", "model.stl")
        loop = asyncio.get_running_loop()
        with patch.object(loop, "time", return_value=100) as clock:
            first = store.add(file)
            second = store.add(file)
            clock.return_value = 399.999
            self.assertIs(store.take(first, file.filename), file)
            clock.return_value = 400
            self.assertIsNone(store.take(second, file.filename))

    async def test_expiry_releases_unclaimed_export_without_another_request(self):
        store = DownloadStore(ttl=0.01)
        self.addCleanup(store.clear)
        file = Download(b"data", "application/octet-stream", "model.stl")
        retained = weakref.ref(file)
        store.add(file)
        del file
        self.assertEqual(len(store), 1)
        self.assertIsNotNone(retained())
        await asyncio.sleep(0.05)
        # Neither observation calls take() or performs opportunistic cleanup.
        self.assertEqual(len(store), 0)
        self.assertIsNone(retained())

    async def test_concurrent_downloads_have_exactly_one_winner(self):
        store = DownloadStore()
        self.addCleanup(store.clear)
        file = Download(b"data", "application/octet-stream", "model.stl")
        token = store.add(file)
        self.assertIsNone(store.take(token, "wrong.stl"))

        async def claim():
            return store.take(token, file.filename)

        results = await asyncio.gather(*(claim() for _ in range(8)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(store), 0)

    async def test_shutdown_releases_outstanding_downloads(self):
        store = DownloadStore()
        file = Download(b"data", "application/octet-stream", "model.stl")
        retained = weakref.ref(file)
        store.add(file)
        del file
        store.clear()
        self.assertEqual(len(store), 0)
        self.assertIsNone(retained())

    async def test_filename_metadata_survives_redirect_and_interrupted_download(self):
        app = FastAPI()
        app.include_router(router)
        app.state.downloads = DownloadStore()
        self.addCleanup(app.state.downloads.clear)
        request = ASGIRequest({"type": "http", "app": app, "server": ("127.0.0.1", 5000)})
        filename = "Bracket plate ü.stl"
        file = Download(b"file bytes", "application/octet-stream", filename)
        redirect = redirect_download(request, "custom://open?file={url}", file)
        url = unquote(redirect.headers["Location"].split("file=", 1)[1])
        path = unquote(urlsplit(url).path)
        token, stored_filename = path.rsplit("/", 2)[1:]
        self.assertEqual(stored_filename, filename)
        self.assertNotIn("Bracket", token)
        response = await download_binary(request, token, stored_filename)
        self.assertEqual(response.body, b"file bytes")
        self.assertIn("Bracket%20plate%20%C3%BC.stl", response.headers["Content-Disposition"])
        self.assertEqual(len(app.state.downloads), 0)

        async def disconnected(message=None):
            raise ConnectionError("client disconnected")

        with self.assertRaises(ConnectionError):
            await response({"type": "http"}, disconnected, disconnected)
        with self.assertRaises(HTTPException) as raised:
            await download_binary(request, token, stored_filename)
        self.assertEqual(raised.exception.status_code, 404)
