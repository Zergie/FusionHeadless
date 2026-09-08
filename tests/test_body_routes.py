from __future__ import annotations

import json
import socket
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode
from urllib.request import urlopen

from adapter import FusionAdapter
import routes
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
    "hash": "94b3a57e-0981-60eb-4aa4-3d0adac74338",
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
        geometry=SimpleNamespace(
            normal=Vector(0.0, 1.0, 0.0), origin=Vector(0.0, 0.0, 0.0),
        ),
        isParamReversed=True,
    )
    ignored_face = SimpleNamespace(
        appearance=SimpleNamespace(name="Default"),
        geometry=SimpleNamespace(
            normal=Vector(0.0, 1.0, 0.0), origin=Vector(0.0, 0.0, 5.0),
        ),
        isParamReversed=True,
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
        self.assertEqual(routes._bodies._body_dict(body_fixture()), EXPECTED_BODY)

    def test_unreadable_face_geometry_reports_hash_context(self) -> None:
        body = body_fixture()
        body.faces = [SimpleNamespace(
            appearance=SimpleNamespace(name="Build Plate"),
            geometry=SimpleNamespace(normal=UnreadableVector()),
            isParamReversed=False,
        )]

        with self.assertRaisesRegex(RuntimeError, "body 'Bracket' face 0 normal"):
            routes._bodies._body_dict(body)


class BodyRouteHost(FakeFusionHost):
    def __init__(self) -> None:
        super().__init__()
        component = SimpleNamespace(
            id="component-1", name="Bracket Component", bRepBodies=[]
        )
        body = body_fixture()
        self.body = body
        body.parentComponent = component
        component.bRepBodies.append(body)
        assembly = SimpleNamespace(id="assembly-1", name="Assembly", bRepBodies=[])
        occurrences = [
            SimpleNamespace(
                component=assembly, name="Assembly:1", fullPathName="Assembly:1",
                isVisible=True,
            ),
            SimpleNamespace(
                component=component, name="Bracket:1",
                fullPathName="Assembly:1+Bracket:1", isVisible=True,
            ),
            SimpleNamespace(
                component=component, name="Bracket:2",
                fullPathName="Assembly:1+Bracket:2", isVisible=False,
            ),
        ]
        root = SimpleNamespace(bRepBodies=[], allOccurrences=occurrences)
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

    def request(self, endpoint: object, **query: object) -> dict[str, object]:
        path = route_path(endpoint)
        if query:
            path += "?" + urlencode(query)
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def test_bodies_endpoint_matches_main_body_contract(self) -> None:
        response = self.request(routes.bodies_route)

        self.assertEqual(response, {
            "status": "ok",
            "result": {
                EXPECTED_BODY["id"]: expected_json_body(count=2),
            },
        })

    def test_components_endpoint_matches_main_body_contract(self) -> None:
        response = self.request(routes.components_route)

        self.assertEqual(response, {
            "status": "ok",
            "result": {
                "assembly-1": {
                    "id": "assembly-1",
                    "name": "Assembly",
                    "bodies": [],
                    "occurrences": [{
                        "name": "Assembly:1", "path": "Assembly:1",
                        "parent": None, "depth": 0, "visible": True,
                    }],
                },
                "component-1": {
                    "id": "component-1",
                    "name": "Bracket Component",
                    "bodies": [{"name": "Bracket"}],
                    "occurrences": [
                        {
                            "name": "Bracket:1", "path": "Assembly:1+Bracket:1",
                            "parent": "Assembly:1", "depth": 1, "visible": True,
                        },
                        {
                            "name": "Bracket:2", "path": "Assembly:1+Bracket:2",
                            "parent": "Assembly:1", "depth": 1, "visible": False,
                        },
                    ],
                },
            },
        })

    def test_components_details_return_only_export_metadata(self) -> None:
        response = self.request(routes.components_route, details="true", name="bracket")

        body = expected_json_body()
        self.assertEqual(response["result"], {
            "component-1": {
                "id": "component-1",
                "name": "Bracket Component",
                "bodies": [{key: body[key] for key in (
                    "name", "hash", "material",
                )}],
                "occurrences": [
                    {
                        "name": "Bracket:1", "path": "Assembly:1+Bracket:1",
                        "parent": "Assembly:1", "depth": 1, "visible": True,
                    },
                    {
                        "name": "Bracket:2", "path": "Assembly:1+Bracket:2",
                        "parent": "Assembly:1", "depth": 1, "visible": False,
                    },
                ],
            },
        })

    def test_components_hash_tracks_face_appearance_assignment(self) -> None:
        before = self.request(routes.components_route, details="true")
        faces = self.host.body.faces
        faces[0].appearance, faces[1].appearance = (
            faces[1].appearance, faces[0].appearance,
        )

        after = self.request(routes.components_route, details="true")

        self.assertNotEqual(
            before["result"]["component-1"]["bodies"][0]["hash"],
            after["result"]["component-1"]["bodies"][0]["hash"],
        )

    def test_components_filter_subtree_depth_and_visibility(self) -> None:
        response = self.request(
            routes.components_route,
            root="Assembly:1", max_depth=1, visible="false",
        )

        self.assertEqual(
            [item["path"] for item in response["result"]["component-1"]["occurrences"]],
            ["Assembly:1+Bracket:2"],
        )


if __name__ == "__main__":
    unittest.main()
