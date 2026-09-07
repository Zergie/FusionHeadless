"""Api documentation helpers and operations for FusionHeadless."""

from __future__ import annotations

import inspect
from types import FunctionType, ModuleType
from typing import Any
from mcp.registry import mcp_tool


def _doc_result(member: Any, name: str) -> dict[str, Any]:
    doc = getattr(member, "__doc__", None) or ""
    return {"name": name, "doc": doc[:doc.find(".")].strip() if "." in doc else doc.strip()}


def _class_result(cls: type[Any], namespace: str) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "class", "name": cls.__name__,
                              "namespace": f"adsk.{namespace}", "doc": cls.__doc__}
    properties, functions = [], []
    for name, member in cls.__dict__.items():
        if name.startswith("_") or name in ("thisown", "cast"):
            continue
        if isinstance(member, property):
            properties.append(_doc_result(member, name))
        elif isinstance(member, FunctionType):
            functions.append(_doc_result(member, name))
    if properties:
        result["properties"] = properties
    if functions:
        result["functions"] = functions
    return result


@mcp_tool(
    "get_api_documentation",
    description="Search Fusion API documentation by class/member names and docstrings.",
    input_schema={
        "type": "object",
        "properties": {
            "search_term": {"type": "string", "description": "Search text."},
            "category": {"type": "string", "enum": ["class_name", "member_name", "description", "all"]},
        },
        "required": ["search_term"],
    },
)
def mcp_get_api_documentation(query: dict[str, Any], context: Any) -> dict[str, Any]:
    adsk = context.adsk
    term = query.get("search_term")
    category = str(query.get("category", "all")).lower().strip()
    allowed = ("class_name", "member_name", "description", "all")
    if not isinstance(term, str) or not term.strip():
        return {"error": True, "message": "Missing or empty 'search_term'", "matches": [], "count": 0}
    if category not in allowed:
        return {"error": True, "message": f"Invalid category '{category}'. Allowed: class_name, member_name, description, all", "matches": [], "count": 0}
    normalized = term.lower().strip()
    if normalized.startswith("adsk."):
        normalized = normalized[5:]
    parts = normalized.split(".")
    namespace_prefix = parts[0] if len(parts) > 1 else None
    class_prefix = parts[1] if len(parts) > 2 else None
    needle = parts[-1].split(None, 1)[0]
    exact, partial = [], []
    for namespace, module in getattr(adsk, "__dict__", {}).items():
        if namespace.startswith("_") or not isinstance(module, ModuleType) or (namespace_prefix and namespace != namespace_prefix):
            continue
        for class_name, cls in getattr(module, "__dict__", {}).items():
            if class_name.startswith("_") or not isinstance(cls, type) or (class_prefix and class_name.lower() != class_prefix):
                continue
            class_lower = class_name.lower()
            class_doc = (cls.__doc__ or "").lower()
            if category in ("class_name", "all") and needle == class_lower:
                exact.append((namespace, cls, None))
            elif category in ("class_name", "all") and needle in class_lower:
                partial.append((namespace, cls, None))
            if category in ("description", "all") and needle in class_doc:
                partial.append((namespace, cls, None))
            for member_name, member in cls.__dict__.items():
                if member_name.startswith("_") or not isinstance(member, (property, FunctionType)):
                    continue
                member_lower = member_name.lower()
                member_doc = (member.__doc__ or "").lower()
                if category in ("member_name", "all") and needle == member_lower:
                    exact.append((namespace, cls, member))
                elif category in ("member_name", "all") and needle in member_lower:
                    partial.append((namespace, cls, member))
                if category in ("description", "all") and needle in member_doc:
                    partial.append((namespace, cls, member))
            if len(exact) >= 3:
                break
        if len(exact) >= 3:
            break
    matches = []
    for namespace, cls, member in (exact + partial)[:3]:
        if member is None:
            matches.append(_class_result(cls, namespace))
        elif isinstance(member, property):
            matches.append({"type": "property", "name": next((n for n, v in cls.__dict__.items() if v is member), "unknown"), "class": cls.__name__, "namespace": f"adsk.{namespace}", "doc": member.__doc__, "readonly": member.fset is None})
        else:
            signature = str(inspect.signature(member)).replace("'", "").replace("::", ".")
            matches.append({"type": "function", "name": member.__name__, "class": cls.__name__, "namespace": f"adsk.{namespace}", "doc": member.__doc__, "signature": signature})
    return {"error": False, "message": f"Found {len(matches)} result{'s' if len(matches) != 1 else ''}",
            "count": len(matches), "category": category, "search_term": needle, "matches": matches}
