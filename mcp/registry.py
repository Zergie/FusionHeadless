"""MCP declaration, inventory, validation, and dispatch policy."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from context import fusion
from fusion_invocation import FusionOperationInvoker


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    required: tuple[str, ...]
    operation: Callable[..., Any]


_tools: dict[str, ToolDefinition] = {}


def mcp_tool(
    name: str,
    *,
    description: str,
    input_schema: dict[str, Any],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare one built-in MCP tool and its Fusion operation together."""
    def decorate(operation: Callable[..., Any]) -> Callable[..., Any]:
        existing = _tools.get(name)
        identity = (operation.__module__, operation.__qualname__)
        if existing is not None and (
            existing.operation.__module__, existing.operation.__qualname__
        ) != identity:
            raise ValueError(f"MCP tool '{name}' is already registered")
        fusion(operation)
        _tools[name] = ToolDefinition(
            name,
            description,
            input_schema,
            tuple(input_schema.get("required", ())),
            operation,
        )
        return operation

    return decorate


def tool_definitions() -> tuple[ToolDefinition, ...]:
    """Return an immutable, deterministic view of the built-in tools."""
    return tuple(_tools[name] for name in sorted(_tools))


def clear_tool_definitions() -> None:
    """Discard all extension tools before a fresh Fusion-side import."""
    _tools.clear()


def tool_inventory() -> list[dict[str, Any]]:
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "inputSchema": definition.input_schema,
        }
        for definition in tool_definitions()
    ]


def call_tool(name: Any, arguments: Any, invoker: FusionOperationInvoker) -> dict[str, Any]:
    definition = _tools.get(name)
    if definition is None:
        raise ValueError(f"Tool '{name}' not found")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    for required in definition.required:
        if required not in arguments:
            raise ValueError(f"Missing required argument '{required}'")
    value = invoker.invoke(definition.operation, arguments)
    if isinstance(value, dict) and "content" in value:
        return value
    text = value if isinstance(value, str) else json.dumps(value, indent=2)
    return {"content": [{"type": "text", "text": text}]}

