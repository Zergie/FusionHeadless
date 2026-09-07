"""Self-contained HTTP route definitions shared across the process seam."""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from typing import Annotated, Any, Callable, get_args, get_origin, get_type_hints

from context import fusion


@dataclass(frozen=True)
class BinaryResponse:
    media_type: str
    filename: str
    defaults: dict[str, str] = field(default_factory=dict)
    disposition: str = "attachment"

    def resolve_filename(self, query: dict[str, Any]) -> str:
        values = {
            **self.defaults,
            **{key: str(value).lower() for key, value in query.items()},
        }
        return self.filename.format_map(values)


@dataclass(frozen=True)
class RedirectURL:
    """Mark an optional URL template parameter consumed by the HTTP child."""


@dataclass(frozen=True)
class ApiParameter:
    """Transport-neutral documentation for one public route parameter."""

    description: str


@dataclass(frozen=True)
class RouteParameter:
    """One typed public parameter derived from a route operation."""

    name: str
    annotation: Any
    default: Any
    description: str | None = None
    redirect: bool = False

    @property
    def required(self) -> bool:
        return self.default is inspect.Parameter.empty


@dataclass(frozen=True)
class RouteDefinition:
    path: str
    methods: tuple[str, ...]
    operation: Callable[..., Any]
    binary: BinaryResponse | None


_routes: dict[str, RouteDefinition] = {}


def api_route(
    path: str,
    *,
    methods: tuple[str, ...] = ("GET",),
    binary: BinaryResponse | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare and register one Fusion-backed HTTP route in one place."""
    def decorate(operation: Callable[..., Any]) -> Callable[..., Any]:
        definition = RouteDefinition(path, methods, operation, binary)
        _routes[path] = definition
        fusion(operation)
        return operation

    return decorate


def route_parameters(operation: Callable[..., Any]) -> tuple[RouteParameter, ...]:
    """Derive the public HTTP contract from a context-first operation."""
    signature = inspect.signature(operation)
    parameters = tuple(signature.parameters.values())
    if not parameters or parameters[0].name != "context":
        raise TypeError(
            f"route operation '{operation.__name__}' must declare context first"
        )
    hints = get_type_hints(operation, include_extras=True)
    result = []
    for parameter in parameters[1:]:
        annotation = hints.get(parameter.name, parameter.annotation)
        description = None
        redirect = False
        if get_origin(annotation) is Annotated:
            annotation, *metadata = get_args(annotation)
            documentation = next(
                (item for item in metadata if isinstance(item, ApiParameter)), None
            )
            if documentation is not None:
                description = documentation.description
            redirect = any(isinstance(item, RedirectURL) for item in metadata)
        result.append(RouteParameter(
            parameter.name,
            annotation,
            parameter.default,
            description,
            redirect,
        ))
    return tuple(result)


def route_definitions() -> tuple[RouteDefinition, ...]:
    return tuple(_routes.values())


def clear_route_definitions() -> None:
    """Discard all extension routes before a fresh Fusion-side import."""
    _routes.clear()
