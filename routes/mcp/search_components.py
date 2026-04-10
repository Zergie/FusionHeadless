"""Search and count matching components/occurrences in the active Fusion document.

Supports plain-text and regex matching. Results are grouped by component identity when
available and returned with stable aggregate counts.
"""

import re


MATERIAL_TOKENS = (" steel ", " stainless ", " brass ", " aluminum ", " alloy ")


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search text or regex pattern."
            },
            "use_regex": {
                "type": "boolean",
                "description": "Use Python regex matching (case-insensitive). Default false."
            },
            "exact": {
                "type": "boolean",
                "description": "When not using regex: case-insensitive exact match. Default false."
            },
            "exclude_material": {
                "type": "string",
                "description": "Optional regex (case-insensitive). Excludes matches whose material string matches this pattern."
            },
            "document": {
                "type": "string",
                "description": "Optional open-document selector by dataFile id or document name. When matching by name, trailing version suffix like ' v127' is ignored."
            }
        },
        "required": ["query"]
    }


def _material_from_name(name: str | None) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None

    # Strip common suffixes before material parsing.
    clean_name = re.sub(r":\d+$", "", name).strip()
    clean_name = re.sub(r"\s+v\d+$", "", clean_name, flags=re.IGNORECASE).strip()

    match = re.search(r"\b(stainless\s+steel|steel|brass|aluminum|alloy)\b.*$", clean_name, re.IGNORECASE)
    if not match:
        return None
    return clean_name[match.start():].strip()


def _component_material_name(component) -> str | None:
    if not component:
        return None
    try:
        material = getattr(component, "material", None)
        if material and hasattr(material, "name") and material.name:
            return material.name
    except Exception:
        pass
    return None


def _parse_bool(query: dict, key: str, default: bool) -> bool:
    value = query.get(key, default)
    if isinstance(value, bool):
        return value
    raise Exception(f"'{key}' must be a boolean")


def _matches(text: str, raw_query: str, use_regex: bool, exact: bool, pattern) -> bool:
    if use_regex:
        return bool(pattern.search(text))

    left = text.lower()
    right = raw_query.lower()
    if exact:
        return left == right
    return right in left


def _normalized_variants(name: str) -> list[str]:
    """Return searchable variants for versioned/instance/materialized names."""
    variants = []
    seen = set()

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    add(name)

    # Remove trailing occurrence instance suffixes like ':1'.
    without_instance = re.sub(r":\d+$", "", name).strip()
    add(without_instance)

    # Remove trailing version suffixes like ' v3'.
    without_version = re.sub(r"\s+v\d+$", "", without_instance, flags=re.IGNORECASE).strip()
    add(without_version)

    # Remove common material tail in Fastener names.
    lower = without_version.lower()
    cut_index = -1
    for token in MATERIAL_TOKENS:
        idx = lower.find(token)
        if idx != -1 and (cut_index == -1 or idx < cut_index):
            cut_index = idx
    if cut_index != -1:
        add(without_version[:cut_index])

    return variants


def _strip_doc_version(name: str | None) -> str:
    if not isinstance(name, str):
        return ""
    # Ignore trailing version suffixes like " v127" when matching document names.
    return re.sub(r"\s+v\d+$", "", name.strip(), flags=re.IGNORECASE).strip()


def _resolve_document(app, selector: str | None):
    if selector is None:
        return app.activeDocument

    if not isinstance(selector, str) or not selector.strip():
        raise Exception("'document' must be a non-empty string when provided")

    selector = selector.strip()
    selector_normalized = _strip_doc_version(selector).lower()

    id_matches = []
    name_matches = []

    for i in range(app.documents.count):
        doc = app.documents.item(i)

        data_file = getattr(doc, "dataFile", None)
        data_file_id = getattr(data_file, "id", None) if data_file else None
        if isinstance(data_file_id, str) and data_file_id == selector:
            id_matches.append(doc)
            continue

        doc_name = getattr(doc, "name", None)
        if isinstance(doc_name, str) and _strip_doc_version(doc_name).lower() == selector_normalized:
            name_matches.append(doc)

    if id_matches:
        return id_matches[0]

    if len(name_matches) == 1:
        return name_matches[0]

    if len(name_matches) > 1:
        names = [getattr(d, "name", "(unnamed)") for d in name_matches]
        raise Exception(f"Ambiguous document selector '{selector}'. Multiple open documents matched by name: {names}")

    raise Exception(f"Open document not found for selector '{selector}'")


def _resolve_design_for_document(doc, adsk):
    products = getattr(doc, "products", None)
    if not products:
        return None

    # Prefer canonical Fusion design product type when available.
    design_product = None
    if hasattr(products, "itemByProductType"):
        try:
            design_product = products.itemByProductType("DesignProductType")
        except Exception:
            design_product = None

    if not design_product:
        try:
            for i in range(products.count):
                product = products.item(i)
                if hasattr(product, "rootComponent"):
                    design_product = product
                    break
        except Exception:
            design_product = None

    if not design_product:
        return None

    if hasattr(adsk, "fusion") and hasattr(adsk.fusion, "Design"):
        try:
            casted = adsk.fusion.Design.cast(design_product)
            if casted:
                return casted
        except Exception:
            pass

    return design_product if hasattr(design_product, "rootComponent") else None


def handle(query: dict, app, adsk) -> dict:
    doc_selector = query.get("document")
    doc = _resolve_document(app, doc_selector)
    design = _resolve_design_for_document(doc, adsk)

    if not doc:
        raise Exception("No document currently open")
    if not design or not hasattr(design, "rootComponent"):
        raise Exception("No active Fusion design")

    raw_query = query.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise Exception("'query' is required and must be a non-empty string")

    raw_query = raw_query.strip()
    raw_exclude_material = query.get("exclude_material")
    if raw_exclude_material is not None and not isinstance(raw_exclude_material, str):
        raise Exception("'exclude_material' must be a string when provided")

    if isinstance(raw_exclude_material, str):
        raw_exclude_material = raw_exclude_material.strip()
        if not raw_exclude_material:
            raw_exclude_material = None

    use_regex = _parse_bool(query, "use_regex", False)
    exact = _parse_bool(query, "exact", False)

    pattern = None
    if use_regex:
        try:
            pattern = re.compile(raw_query, re.IGNORECASE)
        except re.error as exc:
            raise Exception(f"Invalid regex pattern '{raw_query}': {exc}")

    exclude_material_pattern = None
    if raw_exclude_material:
        try:
            exclude_material_pattern = re.compile(raw_exclude_material, re.IGNORECASE)
        except re.error as exc:
            raise Exception(f"Invalid regex pattern for 'exclude_material' ('{raw_exclude_material}'): {exc}")

    groups = {}
    total_scanned = 0
    total_matches = 0

    for occurrence in design.rootComponent.allOccurrences:
        total_scanned += 1

        component_name = None
        component_material = None
        if hasattr(occurrence, "component") and occurrence.component:
            component_name = occurrence.component.name
            component_material = _component_material_name(occurrence.component)

        occurrence_name = occurrence.name if hasattr(occurrence, "name") else None

        candidates = []
        if isinstance(component_name, str) and component_name:
            for name_variant in _normalized_variants(component_name):
                candidates.append(("component", name_variant))
        if isinstance(occurrence_name, str) and occurrence_name:
            for name_variant in _normalized_variants(occurrence_name):
                candidates.append(("occurrence", name_variant))

        matched_field = None
        for field_name, candidate_name in candidates:
            if _matches(candidate_name, raw_query, use_regex, exact, pattern):
                matched_field = field_name
                break

        if not matched_field:
            continue

        display_name = component_name or occurrence_name or "(unnamed)"
        display_name = re.sub(r"(\(\d\)\s*)+$", "", display_name).strip()
        material_value = component_material or _material_from_name(display_name)

        if exclude_material_pattern and material_value and exclude_material_pattern.search(material_value):
            continue

        total_matches += 1

        if display_name not in groups:
            groups[display_name] = {
                "name": display_name,
                "material": material_value,
                "count": 0,
            }

        if not groups[display_name]["material"] and material_value:
            groups[display_name]["material"] = material_value

        groups[display_name]["count"] += 1

    matches = sorted(groups.values(), key=lambda item: (-item["count"], item["name"].lower()))

    return {
        "query": raw_query,
        "document": doc_selector,
        "resolved_document": getattr(doc, "name", None),
        "exclude_material": raw_exclude_material,
        "use_regex": use_regex,
        "exact": exact,
        "total_component_scanned": total_scanned,
        "total_component_matches": total_matches,
        "unique_component_matches": len(groups),
        "matches": matches,
    }


if __name__ == "__main__":
    from _client_ import test
    test(__file__, {"query": ".*Threaded.*", "use_regex": True}, timeout=30)
