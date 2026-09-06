"""Colocated MCP tool definitions and Fusion-side implementations."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
import re
from types import FunctionType, ModuleType
from typing import Any, Callable

from context import fusion
from fusion_invocation import FusionOperationInvoker


PROTOCOL_VERSION = "2024-11-05"


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


def _value(item: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(item, name)
    except Exception:
        return default


@mcp_tool(
    "list_open_documents",
    description="List all currently open Fusion 360 documents.",
    input_schema={"type": "object", "properties": {}},
)
def mcp_list_open_documents(query: dict[str, Any], context: Any) -> dict[str, Any]:
    app = context.app
    documents = []
    for index in range(_value(_value(app, "documents"), "count", 0)):
        doc = app.documents.item(index)
        try:
            _ = doc.documentReferences
        except Exception:
            continue
        data_file = _value(doc, "dataFile")
        documents.append({
            "name": _value(doc, "name"),
            "is_active": bool(_value(doc, "isActive", False)),
            "id": _value(data_file, "id") if data_file else None,
        })
    active = _value(app, "activeDocument")
    return {"count": len(documents), "active_document": _value(active, "name"),
            "documents": documents}


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


def _search_document(app: Any, selector: Any) -> Any:
    """Resolve an open document by id before considering versionless names."""
    if selector is None:
        return _value(app, "activeDocument")
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("'document' must be a non-empty string when provided")
    selector = selector.strip()
    normalized = re.sub(r"\s+v\d+$", "", selector, flags=re.IGNORECASE).strip().lower()
    documents = _value(app, "documents")
    matches = []
    for index in range(_value(documents, "count", 0)):
        doc = documents.item(index)
        if _value(_value(doc, "dataFile"), "id") == selector:
            return doc
        name = _value(doc, "name")
        if (isinstance(name, str)
                and re.sub(r"\s+v\d+$", "", name.strip(), flags=re.IGNORECASE).strip().lower() == normalized):
            matches.append(doc)
    if len(matches) == 1:
        return matches[0]
    elif matches:
        names = [_value(doc, "name") for doc in matches]
        raise ValueError(f"Ambiguous document selector '{selector}'. Multiple open documents matched by name: {names}")
    else:
        raise ValueError(f"Open document not found for selector '{selector}'")


def _search_name_variants(name: Any) -> list[str]:
    """Include original names and names without instance, version, or material tails."""
    if not isinstance(name, str) or not name.strip():
        return []
    original = name.strip()
    instance_free = re.sub(r":\d+$", "", original).strip()
    version_free = re.sub(r"\s+v\d+$", "", instance_free, flags=re.IGNORECASE).strip()
    variants = [original, instance_free, version_free]
    material = re.search(r"\s+(?:steel|stainless|brass|aluminum|alloy)\s+", version_free, re.IGNORECASE)
    if material:
        variants.append(version_free[:material.start()].strip())
    return list(dict.fromkeys(value for value in variants if value))


@mcp_tool(
    "search_components",
    description="Search and count matching components/occurrences in an open Fusion document (active by default).",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search text or regex pattern."},
            "use_regex": {"type": "boolean", "description": "Use case-insensitive regex matching."},
            "exact": {"type": "boolean", "description": "Use case-insensitive exact matching."},
            "exclude_material": {"type": "string", "description": "Material exclusion regex."},
            "document": {"type": "string", "description": "Open document name or data-file id."},
        },
        "required": ["query"],
    },
)
def mcp_search_components(query: dict[str, Any], context: Any) -> dict[str, Any]:
    app = context.app
    raw = query.get("query")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("'query' is required and must be a non-empty string")
    raw = raw.strip()
    excluded = query.get("exclude_material")
    if excluded is not None and not isinstance(excluded, str):
        raise ValueError("'exclude_material' must be a string when provided")
    if isinstance(excluded, str):
        excluded = excluded.strip() or None
    use_regex = query.get("use_regex", False)
    exact = query.get("exact", False)
    if not isinstance(use_regex, bool) or not isinstance(exact, bool):
        raise ValueError("'use_regex' and 'exact' must be booleans")
    try:
        pattern = re.compile(raw, re.IGNORECASE) if use_regex else None
    except re.error as error:
        raise ValueError(f"Invalid regex pattern '{raw}': {error}") from error
    try:
        material_pattern = re.compile(excluded, re.IGNORECASE) if excluded else None
    except re.error as error:
        raise ValueError(f"Invalid regex pattern for 'exclude_material' ('{excluded}'): {error}") from error
    doc = _search_document(app, query.get("document"))
    if doc is None:
        raise ValueError("No document currently open")
    products = _value(doc, "products")
    design = None
    by_type = _value(products, "itemByProductType")
    if callable(by_type):
        try:
            design = by_type("DesignProductType")
        except Exception:
            pass
    if design is None:
        for index in range(_value(products, "count", 0)):
            candidate = products.item(index)
            if hasattr(candidate, "rootComponent"):
                design = candidate
                break
    cast = _value(_value(_value(context.adsk, "fusion"), "Design"), "cast")
    if design is not None and callable(cast):
        try:
            design = cast(design) or design
        except Exception:
            pass
    if _value(design, "rootComponent") is None:
        raise ValueError(f"No Fusion design in document '{_value(doc, 'name')}'")
    groups: dict[str, dict[str, Any]] = {}
    scanned = 0
    for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
        scanned += 1
        component = _value(occurrence, "component")
        component_name = _value(component, "name")
        occurrence_name = _value(occurrence, "name")
        candidates = _search_name_variants(component_name) + _search_name_variants(occurrence_name)
        if pattern is not None:
            matched = any(pattern.search(name) for name in candidates)
        elif exact:
            matched = any(name.lower() == raw.lower() for name in candidates)
        else:
            matched = any(raw.lower() in name.lower() for name in candidates)
        if not matched:
            continue
        name = component_name or occurrence_name
        key = re.sub(r"(\(\d\)\s*)+$", "", name).strip()
        material = _value(_value(component, "material"), "name")
        if not material:
            clean_name = re.sub(r":\d+$", "", key).strip()
            clean_name = re.sub(r"\s+v\d+$", "", clean_name, flags=re.IGNORECASE).strip()
            material_match = re.search(r"\b(stainless\s+steel|steel|brass|aluminum|alloy)\b.*$", clean_name, re.IGNORECASE)
            material = material_match.group() if material_match else None
        if material_pattern is not None and material and material_pattern.search(material):
            continue
        group = groups.setdefault(key, {"name": key, "material": material, "count": 0})
        if not group["material"] and material:
            group["material"] = material
        group["count"] += 1
    matches = sorted(groups.values(), key=lambda item: (-item["count"], item["name"].lower()))
    return {"query": raw.strip(), "document": query.get("document"), "resolved_document": _value(doc, "name"),
            "exclude_material": excluded, "use_regex": use_regex, "exact": exact,
            "total_component_scanned": scanned, "total_component_matches": sum(item["count"] for item in matches),
            "unique_component_matches": len(matches), "matches": matches}
