from __future__ import annotations

from pathlib import Path
import socket
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json

from startup.stl_export_contract import BodySelection
from adapter import FusionAdapter
import routes
from tests.harness import FakeFusionHost, route_path
from tests.test_stl_orientation import box_stl, read_stl


class Body:
    def __init__(self, token, offset):
        self.entityToken = token
        self.name = "Body"
        self.offset = offset
        self.isValid = True
        self.faces = []
        self.isLightBulbOn = True
        self.parentComponent = NS(name="Component", id=token, bRepBodies=[self], occurrences=[])


class BatchHost(FakeFusionHost):
    def __init__(self):
        super().__init__()
        self.bodies = [Body("first", (0, 0, 10)), Body("second", (20, 0, 30))]
        self.exported = []
        host = self

        class Manager:
            def createSTLExportOptions(self, body, path):
                return NS(filename=path, body=body)

            def execute(self, options):
                if not options.body.isValid:
                    raise RuntimeError("Selected body is no longer available")
                host.exported.append(options)
                Path(options.filename).write_bytes(box_stl(options.body.offset))
                return True

        self.app.activeDocument = NS(name="Batch", dataFile=NS(id="batch-document"))
        self.app.activeProduct = NS(
            exportManager=Manager(),
            rootComponent=NS(
                bRepBodies=[],
                allOccurrences=[
                    NS(component=b.parentComponent, isLightBulbOn=True) for b in self.bodies
                ],
            ),
            findEntityByToken=lambda token: [
                body for body in self.bodies if body.entityToken == token
            ],
        )
        self.adsk = NS(fusion=NS(
            BRepBody=NS(cast=lambda entity: entity if isinstance(entity, Body) else None),
            DistanceUnits=NS(MillimeterDistanceUnits="mm")))

    def context(self):
        return {**super().context(), "adsk": self.adsk}


class StlExportFixture:
    def setUp(self):
        self.endpoint = routes.export_route
        self.host = BatchHost()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.origin = f"http://127.0.0.1:{port}"
        self.adapter = FusionAdapter(host=self.host, port=port)
        self.addCleanup(self.adapter.stop)
        self.assertTrue(self.adapter.start(timeout=5))

    def export(self, **arguments):
        request = Request(self.origin + route_path(self.endpoint),
            data=json.dumps(arguments).encode(), headers={"Content-Type": "application/json"})
        return urlopen(request, timeout=10)

    def mark_bodies(self):
        if not hasattr(self.host.adsk, "core"):
            self.host.adsk.core = NS()
        self.host.adsk.core.Plane = NS(cast=lambda geometry: geometry)
        for body in self.host.bodies:
            plane = NS(normal=NS(asArray=lambda: [0, 0, -1]),
                       origin=NS(asArray=lambda body=body: [x / 10 for x in body.offset]))
            body.faces = [NS(appearance=NS(id="bed", name="Print bed"),
                             geometry=plane, isParamReversed=False)]


class StlBatchTests(StlExportFixture, unittest.TestCase):

    def test_same_body_name_in_different_components_exports_separately(self):
        for token, z in [("second", 30), ("first", 10)]:
            with self.export(format="stl", component=token, body=["Body"]) as response:
                self.assertAlmostEqual(read_stl(response.read()).vectors.min(axis=(0, 1))[2], z)
        for options in self.host.exported:
            self.assertFalse(Path(options.filename).exists())

    def test_button_prepares_each_body_through_export_and_returns_one_redirect_each(self):
        from startup.stl_export_job import prepare_exports
        from urllib.parse import unquote
        results = prepare_exports(self.origin, [BodySelection("second", "Body"), BodySelection("first", "Body")],
                                  redirect_url="orcaslicer://open?file={url}")
        self.assertEqual(len(results), 2)
        for result, z in zip(results, [30, 10]):
            self.assertTrue(result.startswith("orcaslicer://open?file="))
            url = unquote(result.split("file=", 1)[1])
            with urlopen(url, timeout=5) as response:
                self.assertAlmostEqual(read_stl(response.read()).vectors.min(axis=(0, 1))[2], z)
            with self.assertRaises(HTTPError):
                urlopen(url, timeout=5)

    def test_each_body_is_oriented_independently_using_existing_orient_parameter(self):
        from startup.stl_export_job import prepare_exports
        self.mark_bodies()
        for payload in prepare_exports(self.origin, [BodySelection("first", "Body"), BodySelection("second", "Body")], orient="Print bed"):
            model = read_stl(payload)
            minimum, maximum = model.vectors.min(axis=(0, 1)), model.vectors.max(axis=(0, 1))
            self.assertAlmostEqual(minimum[2], 0)
            self.assertAlmostEqual(minimum[0] + maximum[0], 0)
            self.assertAlmostEqual(minimum[1] + maximum[1], 0)

    def test_unknown_component_fails_without_export(self):
        with self.assertRaises(HTTPError) as caught:
            self.export(format="stl", component="gone", body=["Body"])
        caught.exception.close()
        self.assertEqual(self.host.exported, [])

    def test_queued_identity_rejects_a_different_active_document(self):
        from startup.stl_export_job import prepare_exports

        self.host.app.activeDocument = NS(name="Other", dataFile=NS(id="other-document"))
        selection = BodySelection(
            "first", "Body", "batch-document", self.host.bodies[0].entityToken
        )
        with self.assertRaisesRegex(RuntimeError, "Active document changed"):
            prepare_exports(self.origin, [selection])
        self.assertEqual(self.host.exported, [])

    def test_expired_redirect_batch_is_rejected_before_handoff(self):
        from startup.stl_export_job import prepare_exports
        with patch("startup.stl_export_job.monotonic", side_effect=[0, 301]):
            with self.assertRaisesRegex(RuntimeError, "expired"):
                prepare_exports(self.origin, [BodySelection("first", "Body"), BodySelection("second", "Body")],
                                redirect_url="cura://open?file={url}")
