from __future__ import annotations

import asyncio
import json
import socket
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from adapter import FusionAdapter
import routes
from tests.harness import FakeFusionHost, route_path


class Collection(list):
    def itemById(self, identity):
        return next(item for item in self if item.id == identity)


class FakeParameter:
    def __init__(self, name, expression):
        self.name = name
        self.expression = expression


class FakeData:
    def __init__(self, file):
        self.dataProjects = []
        self.file = file

    def findFileById(self, identity):
        return self.file if identity == self.file.id else None


class FakeDocument:
    def __init__(self, file):
        self.dataFile = file
        self.name = "Active design v3"
        self.isModified = False
        self.isSaved = True
        self.closed_with = None
        self.saved = False

    def close(self, save):
        self.closed_with = save

    def save(self):
        self.saved = True


class FakeDocuments(Collection):
    def __init__(self, app, document):
        super().__init__([document])
        self.app = app
        self.defer_open = False
        self.pending_file = None

    def open(self, file):
        if self.defer_open:
            self.pending_file = file
        else:
            self.app.activeDocument = FakeDocument(file)

    def complete_open(self):
        if self.pending_file is not None:
            self.app.activeDocument = FakeDocument(self.pending_file)
            self.pending_file = None


class MutationAdsk:
    def __init__(self, app):
        self.app = app
        self.do_events_calls = 0

    def doEvents(self):
        self.do_events_calls += 1
        self.app.documents.complete_open()


class FakeSelection(Collection):
    def clear(self):
        del self[:]

    def add(self, item):
        self.append(item)


class FakeCommand:
    def __init__(self, ui):
        self.ui = ui

    def execute(self):
        self.ui.command_executed = True


class FakeUI:
    def __init__(self):
        self.activeSelections = FakeSelection()
        self.command_executed = False
        self.commandDefinitions = self

    def itemById(self, identity):
        assert identity == "FindInBrowser"
        return FakeCommand(self)


class FakeViewport:
    def __init__(self):
        self.home_called = False
        self.fit_called = False

    def goHome(self):
        self.home_called = True

    def fit(self):
        self.fit_called = True


class FakeComponent:
    def __init__(self):
        self.id = "component-1"
        self.name = "Bracket"
        self.isLightBulbOn = True


class FakeOccurrence:
    def __init__(self, component):
        self.component = component
        self.isVisible = True
        self.isIsolated = False
        self.isLightBulbOn = True


class MutationHost(FakeFusionHost):
    def __init__(self):
        super().__init__()
        self.ui = FakeUI()
        file = type("File", (), {"id": "file-1"})()
        initial = FakeDocument(file)
        component = FakeComponent()
        occurrence = FakeOccurrence(component)
        root = type("Root", (), {"allOccurrences": [occurrence]})()
        design = type("Design", (), {
            "designType": 1,
            "rootComponent": root,
            "userParameters": [FakeParameter("d1", 2.0)],
        })()
        self.app.activeDocument = initial
        self.app.activeProduct = design
        self.app.data = FakeData(file)
        self.app.documents = FakeDocuments(self.app, initial)
        self.app.activeViewport = FakeViewport()
        self.adsk = MutationAdsk(self.app)
        self.occurrence = occurrence

    def context(self):
        return {"app": self.app, "ui": self.ui, "adsk": self.adsk}


class MutationRouteTests(unittest.TestCase):
    def setUp(self):
        self.host = MutationHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.adapter = FusionAdapter(host=self.host, port=self.port)
        self.assertTrue(self.adapter.start(timeout=5))
        self.addCleanup(self.adapter.stop)

    def request(self, path, values, method="POST"):
        request = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(values).encode() if method == "POST" else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def request_error(self, path, values, method="POST"):
        request = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(values).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=5)
        return raised.exception.code, json.loads(raised.exception.read())

    def test_document_open_and_close_cross_boundary(self):
        status, opened = self.request(
            route_path(routes.document_route), {"open": "file-1"}
        )
        self.assertEqual((status, opened["result"]), (200, "File is already active."))
        self.host.app.activeDocument = None
        status, opened = self.request(
            route_path(routes.document_route), {"open": "file-1"}
        )
        self.assertEqual((status, opened["result"]), (200, "File opened successfully."))
        status, closed = self.request(
            route_path(routes.document_route), {"close": True}
        )
        self.assertEqual((status, closed["result"]), (200, "File closed successfully."))
        self.assertTrue(self.host.app.activeDocument.closed_with)

    def test_document_get_returns_active_document_state(self):
        status, payload = self.request(
            route_path(routes.document_route), {}, method="GET"
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {
            "status": "ok",
            "result": {
                "id": "file-1",
                "name": "Active design v3",
                "isModified": False,
                "isSaved": True,
            },
        })

        self.host.app.activeDocument = None
        status, payload = self.request(
            route_path(routes.document_route), {}, method="GET"
        )
        self.assertEqual((status, payload), (200, {"status": "ok", "result": None}))

    def test_document_open_takes_precedence_over_close(self):
        active = self.host.app.activeDocument

        status, result = self.request(
            route_path(routes.document_route),
            {"open": "file-1", "close": True},
        )

        self.assertEqual((status, result["result"]), (200, "File is already active."))
        self.assertIsNone(active.closed_with)

    def test_document_open_waits_until_fusion_activates_the_file(self):
        self.host.app.activeDocument = None
        self.host.app.documents.defer_open = True

        status, opened = self.request(
            route_path(routes.document_route), {"open": "file-1"}
        )

        self.assertEqual((status, opened["result"]), (200, "File opened successfully."))
        self.assertGreaterEqual(self.host.adsk.do_events_calls, 1)
        self.assertEqual(self.host.app.activeDocument.dataFile.id, "file-1")

    def test_document_open_reports_activation_timeout_without_waiting_30_seconds(self):
        self.host.app.activeDocument = None
        self.host.app.documents.defer_open = True
        observed_timeouts = []

        async def timeout_immediately(awaitable, timeout):
            observed_timeouts.append(timeout)
            awaitable.close()
            raise asyncio.TimeoutError()

        with patch.object(routes.documents.asyncio, "wait_for", timeout_immediately):
            status, payload = self.request_error(
                route_path(routes.document_route), {"open": "file-1"}
            )

        self.assertEqual(observed_timeouts, [30])
        self.assertEqual(status, 500)
        self.assertEqual(
            payload,
            {
                "status": "error",
                "error": "Failed to open file with ID 'file-1' within 30 seconds.",
            },
        )

    def test_parameter_update_returns_coerced_value(self):
        status, result = self.request(
            route_path(routes.parameter_route), {"set": ["d1=3.5"]}
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["result"], {"d1": "3.5"})
        self.assertEqual(self.host.app.activeProduct.userParameters[0].expression, "3.5")

    def test_select_changes_observable_fusion_state(self):
        status, result = self.request(
            route_path(routes.select_route), {"id": "component-1"}
        )
        self.assertEqual((status, result["result"]),
                         (200, {"id": "component-1", "name": "Bracket"}))
        self.assertTrue(self.host.occurrence.isIsolated)
        self.assertTrue(self.host.ui.command_executed)
        self.assertTrue(self.host.app.activeViewport.home_called)
        self.assertTrue(self.host.app.activeViewport.fit_called)
        self.assertEqual(self.host.ui.activeSelections, [])


if __name__ == "__main__":
    unittest.main()
