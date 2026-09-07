"""Search components helpers and operations for FusionHeadless."""

from __future__ import annotations

import re
from typing import Any
from fusion_support import _value
from mcp.registry import mcp_tool


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
