from __future__ import annotations

import json
import socket
from types import SimpleNamespace
import unittest
from urllib.request import urlopen

from adapter import FusionAdapter
import fusion_routes
from tests.harness import FakeFusionHost, route_path


class Vector:
    def __init__(self, *values: float) -> None:
        self.values = values

    def asArray(self) -> list[float]:
        return list(self.values)


class UnreadableVector:
    def asArray(self) -> list[float]:
        raise RuntimeError("Fusion geometry is unavailable")


EXPECTED_BODY = {
    "id": "95a20093-c8f7-05d1-0dea-71cbafe1cbaa",
    "hash": "b921cdb0-4734-e28f-644d-e220dea1158c",
    "name": "Bracket",
    "volume": 1.23457,
    "mass": 0.0,
    "area": 9.87654,
    "color": "0102FFFF",
    "centerOfMass": [1.235, 0.0, 9.876],
    "material": "ABS",
    "orientation": [(0.0, -1.0, 0.0)],
    "boundingBox": {
        "min": [-1.235, 0.0, 2.346],
        "max": [4.567, 5.678, 6.789],
    },
}


def expected_json_body(**extra: object) -> dict[str, object]:
    return {
        **EXPECTED_BODY,
        "orientation": [[0.0, -1.0, 0.0]],
        **extra,
    }


def body_fixture() -> SimpleNamespace:
    build_plate_face = SimpleNamespace(
        appearance=SimpleNamespace(name="YAMMU Build Plate"),
        geometry=SimpleNamespace(normal=Vector(0.0, 1.0, 0.0)),
        isParamReversed=True,
    )
    ignored_face = SimpleNamespace(
        appearance=SimpleNamespace(name="Default"),
        geometry=SimpleNamespace(normal=Vector(1.0, 0.0, 0.0)),
        isParamReversed=False,
    )
    return SimpleNamespace(
        name="Bracket",
        parentComponent=SimpleNamespace(id="component-1"),
        physicalProperties=SimpleNamespace(
            volume=1.234567,
            mass=0.000001,
            area=9.876543,
            centerOfMass=Vector(1.2346, -0.0004, 9.8764),
        ),
        appearance=SimpleNamespace(appearanceProperties=[
            SimpleNamespace(
                name="Color",
                value=SimpleNamespace(red=1, green=2, blue=255),
            )
        ]),
        material=SimpleNamespace(name="ABS"),
        faces=[build_plate_face, ignored_face],
        boundingBox=SimpleNamespace(
            minPoint=Vector(-1.2346, 0.0, 2.3456),
            maxPoint=Vector(4.5674, 5.6784, 6.7894),
        ),
    )


class BodySerializationTests(unittest.TestCase):
    def test_body_payload_matches_main_contract(self) -> None:
        self.assertEqual(fusion_routes._body_dict(body_fixture()), EXPECTED_BODY)

    def test_unreadable_build_plate_normal_is_ignored(self) -> None:
        body = body_fixture()
        body.faces = [SimpleNamespace(
            appearance=SimpleNamespace(name="Build Plate"),
            geometry=SimpleNamespace(normal=UnreadableVector()),
            isParamReversed=False,
        )]

        self.assertEqual(fusion_routes._body_dict(body)["orientation"], [])


class BodyRouteHost(FakeFusionHost):
    def __init__(self) -> None:
        super().__init__()
        component = SimpleNamespace(
            id="component-1", name="Bracket Component", bRepBodies=[]
        )
        body = body_fixture()
        body.parentComponent = component
        component.bRepBodies.append(body)
        occurrence = SimpleNamespace(component=component)
        root = SimpleNamespace(bRepBodies=[], allOccurrences=[occurrence])
        self.app.activeProduct = SimpleNamespace(rootComponent=root)


class BodyRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = BodyRouteHost()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.adapter = FusionAdapter(host=self.host, port=self.port)
        self.assertTrue(self.adapter.start(timeout=5))
        self.addCleanup(self.adapter.stop)

    def request(self, endpoint: object) -> dict[str, object]:
        path = route_path(endpoint)
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def test_bodies_endpoint_matches_main_body_contract(self) -> None:
        response = self.request(fusion_routes.bodies_route)

        self.assertEqual(response, {
            "status": "ok",
            "result": {
                EXPECTED_BODY["id"]: expected_json_body(count=1),
            },
        })

    def test_components_endpoint_matches_main_body_contract(self) -> None:
        response = self.request(fusion_routes.components_route)

        self.assertEqual(response, {
            "status": "ok",
            "result": {
                "component-1": {
                    "id": "component-1",
                    "name": "Bracket Component",
                    "bodies": [expected_json_body()],
                    "count": 1,
                },
            },
        })


if __name__ == "__main__":
    unittest.main()
