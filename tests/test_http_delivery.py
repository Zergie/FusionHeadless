from __future__ import annotations

import unittest
from typing import Annotated

from fastapi import HTTPException, Request

from http_delivery import compile_delivery
from routing import BinaryResponse, RedirectURL, RouteDefinition, route_parameters


class DeliveryContractTests(unittest.TestCase):
    def test_marker_identifies_server_parameter_without_matching_its_name(self):
        def operation(context, launch: Annotated[str | None, RedirectURL()] = None):
            pass

        definition = RouteDefinition("/example", ("POST",), operation,
                                     BinaryResponse("model/stl", "Bracket plate.stl"))
        prepare, options = compile_delivery(definition, route_parameters(operation))
        arguments = {"launch": None}
        respond = prepare(Request({"type": "http"}), arguments)
        self.assertEqual(arguments, {})
        response = respond(b"mesh")
        self.assertEqual(response.body, b"mesh")
        self.assertEqual(response.headers["Content-Disposition"],
                         'attachment; filename="Bracket plate.stl"')
        self.assertIn(303, options["responses"])
        with self.assertRaises(HTTPException) as raised:
            prepare(Request({"type": "http"}), {"launch": "relative/{url}"})
        self.assertEqual(raised.exception.status_code, 422)

    def test_invalid_server_parameter_contracts_fail_at_registration(self):
        def wrong_type(context, launch: Annotated[int, RedirectURL()] = None):
            pass

        def wrong_default(context, launch: Annotated[str | None, RedirectURL()] = "custom:{url}"):
            pass

        def multiple(context, first: Annotated[str | None, RedirectURL()] = None,
                     second: Annotated[str | None, RedirectURL()] = None):
            pass

        def nonbinary(context, launch: Annotated[str | None, RedirectURL()] = None):
            pass

        for operation, binary in (
            (wrong_type, BinaryResponse("model/stl", "mesh.stl")),
            (wrong_default, BinaryResponse("model/stl", "mesh.stl")),
            (multiple, BinaryResponse("model/stl", "mesh.stl")),
            (nonbinary, None),
        ):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(TypeError, "RedirectURL"):
                compile_delivery(RouteDefinition("/example", ("POST",), operation, binary),
                                 route_parameters(operation))
