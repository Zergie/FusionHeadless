"""Invoke registered Fusion operations through one child-side module."""

from __future__ import annotations

import json
import inspect
from typing import Any, Callable

from context import registry


class FusionInvocationError(RuntimeError):
    """Base error for registered Fusion-operation invocation."""


class UnregisteredFusionOperationError(FusionInvocationError):
    """Raised before execution when an operation is not registered for Fusion."""


FusionExecutor = Callable[[str], Any]


class FusionOperationInvoker:
    """Validate and dispatch one registered operation through an executor."""

    def __init__(self, executor: FusionExecutor) -> None:
        self._executor = executor

    def invoke(self, operation: Callable[..., Any], query: dict[str, Any]) -> Any:
        """Return an operation's native value using the bound Fusion context."""
        definition = registry.fusion.get(getattr(operation, "__name__", ""))
        if definition is None or definition.value is not operation:
            name = getattr(operation, "__name__", repr(operation))
            raise UnregisteredFusionOperationError(
                f"unregistered Fusion operation: {name}"
            )
        if not isinstance(query, dict):
            raise FusionInvocationError("Fusion operation query must be an object")
        try:
            # The generated source runs in Python, so normalize through JSON
            # and then emit a Python literal (with True/False/None names).
            encoded_query = ascii(json.loads(json.dumps(query)))
        except (TypeError, ValueError) as error:
            raise FusionInvocationError("Fusion operation query must be JSON serializable") from error
        try:
            parameters = tuple(inspect.signature(operation).parameters)
            if parameters and parameters[0] == "context":
                code = f"return {definition.name}(fusion_context, **{encoded_query})"
            elif parameters[:2] == ("query", "context"):
                code = f"return {definition.name}({encoded_query}, fusion_context)"
            else:
                raise FusionInvocationError(
                    f"unsupported Fusion operation interface: {definition.name}"
                )
            return self._executor(code)
        except Exception as error:
            if isinstance(error, FusionInvocationError):
                raise
            raise FusionInvocationError(str(error)) from error
