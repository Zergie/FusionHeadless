"""Explicit definitions that may cross the FusionHeadless process boundary."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable


@dataclass(frozen=True)
class FusionContext:
    """Live Fusion values bound once for a registered Fusion operation."""

    app: Any
    ui: Any
    adsk: Any

    def call_server(self, operation: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call an explicitly registered child operation from a Fusion operation."""
        name = getattr(operation, "__name__", None)
        definition = registry.server.get(name)
        if definition is None or definition.value is not operation:
            raise ValueError(f"Unregistered server operation: {name!r}")
        factory = _server_callbacks.get()
        if factory is None:
            raise RuntimeError("Server callbacks require an active Fusion invocation")
        return factory(name)(*args, **kwargs)


_server_callbacks: ContextVar[Any] = ContextVar("fusion_server_callbacks", default=None)


@contextmanager
def server_callback_scope(factory: Callable[..., Any]):
    """Bind callbacks to this UI-thread invocation and clear them on every exit."""
    token = _server_callbacks.set(factory)
    try:
        yield
    finally:
        _server_callbacks.reset(token)


@dataclass(frozen=True)
class Definition:
    name: str
    value: Any
    target: str


class DefinitionRegistry:
    def __init__(self) -> None:
        self.fusion: dict[str, Definition] = {}
        self.server: dict[str, Definition] = {}

    def add(self, value: Any, target: str) -> Any:
        name = getattr(value, "__name__", None)
        if not name:
            raise TypeError("context definitions must have a name")
        definition = Definition(name, value, target)
        getattr(self, target)[name] = definition
        setattr(value, "__fusionheadless_context__", target)
        return value

    def register_decorated(self, target: str, *values: Any) -> None:
        """Register existing exports without allowing a change of process target."""
        for value in values:
            if getattr(value, "__fusionheadless_context__", None) != target:
                raise ValueError(f"only @context.{target} definitions may be registered")
            self.add(value, target)

    def class_for_identity(self, identity: str) -> type[Any] | None:
        """Return a decorated class registered in either context namespace."""
        for definitions in (self.fusion, self.server):
            for definition in definitions.values():
                value = definition.value
                if isinstance(value, type) and _class_identity(value) == identity:
                    return value
        return None

    def reset(self) -> None:
        """Discard process-boundary registrations while retaining the context."""
        self.fusion.clear()
        self.server.clear()
        self.add(FusionContext, "fusion")


registry = DefinitionRegistry()


_TYPE_KEY = "__fusionheadless_type__"


def _class_identity(value: type[Any]) -> str:
    return f"{value.__module__}.{value.__qualname__}"


def serialize_value(value: Any) -> Any:
    """Convert supported cross-context values into a JSON-compatible tree.

    Decorated objects are represented by identity and state.  The active-path
    set detects cycles while still allowing equal or repeated values to be
    copied independently.
    """
    active: set[int] = set()

    def convert(item: Any) -> Any:
        if isinstance(item, (bytes, bytearray, memoryview)):
            raise TypeError("binary values are supported only as a top-level bridge payload")
        elif item is None or isinstance(item, (str, int, float, bool)):
            return item
        item_id = id(item)
        if item_id in active:
            raise TypeError("cyclic object graphs are not supported by the bridge")
        if isinstance(item, list):
            active.add(item_id)
            try:
                return [convert(child) for child in item]
            finally:
                active.remove(item_id)
        elif isinstance(item, tuple):
            active.add(item_id)
            try:
                return {_TYPE_KEY: "tuple", "items": [convert(child) for child in item]}
            finally:
                active.remove(item_id)
        elif isinstance(item, dict):
            active.add(item_id)
            try:
                return {key: convert(child) for key, child in item.items()}
            finally:
                active.remove(item_id)
        elif isinstance(item, type):
            raise TypeError(f"unregistered custom type: {type(item).__name__}")
        item_type = type(item)
        identity = _class_identity(item_type)
        if registry.class_for_identity(identity) is not item_type:
            raise TypeError(f"unregistered custom type: {identity}")
        state = getattr(item, "__dict__", None)
        if not isinstance(state, dict):
            raise TypeError(f"decorated class {identity} must expose a __dict__")
        active.add(item_id)
        try:
            return {
                _TYPE_KEY: "object",
                "class": identity,
                "state": convert(state),
            }
        finally:
            active.remove(item_id)

    return convert(value)


def deserialize_value(value: Any) -> Any:
    """Reconstruct a supported value tree without invoking object constructors."""
    if isinstance(value, list):
        return [deserialize_value(child) for child in value]
    elif not isinstance(value, dict):
        return value
    marker = value.get(_TYPE_KEY)
    if marker == "tuple" and set(value) == {_TYPE_KEY, "items"}:
        items = value["items"]
        if not isinstance(items, list):
            raise TypeError("invalid serialized tuple payload")
        return tuple(deserialize_value(child) for child in items)
    elif marker == "object" and set(value) == {_TYPE_KEY, "class", "state"}:
        identity = value["class"]
        if not isinstance(identity, str):
            raise TypeError("invalid serialized class identity")
        cls = registry.class_for_identity(identity)
        if cls is None:
            raise TypeError(f"unregistered custom type: {identity}")
        state = deserialize_value(value["state"])
        if not isinstance(state, dict):
            raise TypeError(f"invalid state for serialized class: {identity}")
        instance = cls.__new__(cls)
        instance.__dict__.update(state)
        return instance
    else:
        return {key: deserialize_value(child) for key, child in value.items()}


def fusion(value: Any) -> Any:
    """Mark a function or class for execution/installation in Fusion."""
    return registry.add(value, "fusion")


def server(value: Any) -> Any:
    """Export a function or class for calls originating in Fusion."""
    return registry.add(value, "server")


def generated_function(code: str) -> Callable[..., Any]:
    """Compile user code as a function so normal ``return`` is meaningful."""
    lines = code.splitlines() or ["pass"]
    source = "def __fusionheadless_exec__():\n" + "\n".join(
        "    " + line for line in lines
    )
    namespace: dict[str, Any] = {}
    exec(compile(source, "<fusionheadless-exec>", "exec"), namespace)
    return namespace["__fusionheadless_exec__"]


# FusionContext is constructed in the adapter process, so generated Fusion
# code can use it without the child ever handling live Fusion objects.
fusion(FusionContext)
