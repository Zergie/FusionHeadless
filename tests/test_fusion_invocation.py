from __future__ import annotations

import unittest

from context import fusion
from fusion_invocation import (FusionInvocationError, FusionOperationInvoker,
                               UnregisteredFusionOperationError)


@fusion
def registered_probe(query: dict[str, object], context: object) -> object:
    return query, context


@fusion
def registered_route(context: object, name: str, count: int = 1) -> object:
    return context, name, count


class FusionOperationInvokerTests(unittest.TestCase):
    def setUp(self) -> None:
        fusion(registered_probe)
        fusion(registered_route)

    def test_invokes_registered_operation_with_the_bound_context_name(self) -> None:
        commands: list[str] = []
        invoker = FusionOperationInvoker(lambda code: commands.append(code) or {"ok": True})

        self.assertEqual(invoker.invoke(registered_probe, {"name": "Grüße"}), {"ok": True})
        self.assertEqual(
            commands,
            ["return registered_probe({'name': 'Gr\\xfc\\xdfe'}, fusion_context)"],
        )

    def test_invokes_context_first_route_with_keyword_arguments(self) -> None:
        commands: list[str] = []
        invoker = FusionOperationInvoker(lambda code: commands.append(code) or "done")

        self.assertEqual(invoker.invoke(registered_route, {"name": "part", "count": 2}),
                         "done")
        self.assertEqual(commands, [
            "return registered_route(fusion_context, **{'name': 'part', 'count': 2})"
        ])

    def test_rejects_unregistered_operations_and_non_object_queries(self) -> None:
        def unregistered(query: object, context: object) -> None:
            return None

        invoker = FusionOperationInvoker(lambda code: code)
        with self.assertRaises(UnregisteredFusionOperationError):
            invoker.invoke(unregistered, {})
        with self.assertRaises(FusionInvocationError):
            invoker.invoke(registered_probe, [])  # type: ignore[arg-type]

    def test_preserves_execution_failure_as_the_cause(self) -> None:
        original = RuntimeError("Fusion failed")

        def fail(_: str) -> None:
            raise original

        with self.assertRaisesRegex(FusionInvocationError, "Fusion failed") as caught:
            FusionOperationInvoker(fail).invoke(registered_probe, {})
        self.assertIs(caught.exception.__cause__, original)


if __name__ == "__main__":
    unittest.main()
