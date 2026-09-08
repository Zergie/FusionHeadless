"""Components helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Annotated, Any
from routing import ApiParameter, api_route
from routes._bodies import _body_dict
from fusion_support import _value


def _component_body(body: Any, details: bool) -> dict[str, Any]:
    result = {"name": str(_value(body, "name", ""))}
    if details:
        complete = _body_dict(body, include_orientation=False)
        result.update({
            key: complete[key]
            for key in ("hash", "material")
        })
    return result


def _occurrence_dict(occurrence: Any, include_transform: bool) -> dict[str, Any]:
    path = str(_value(occurrence, "fullPathName") or _value(occurrence, "name", ""))
    parent, separator, _ = path.rpartition("+")
    result = {
        "name": str(_value(occurrence, "name", "")),
        "path": path,
        "parent": parent if separator else None,
        "depth": path.count("+"),
        "visible": bool(_value(
            occurrence, "isVisible", _value(occurrence, "isLightBulbOn", True)
        )),
    }
    if include_transform:
        transform = _value(occurrence, "transform2", _value(occurrence, "transform"))
        values = _value(transform, "asArray")
        result["transform"] = list(values()) if callable(values) else []
    return result


@api_route("/components")
def components_route(
    context: Any,
    name: Annotated[
        str | None,
        ApiParameter("Case-insensitive substring matched against occurrence paths and component names."),
    ] = None,
    root: Annotated[
        str | None,
        ApiParameter("Exact occurrence path whose subtree should be returned."),
    ] = None,
    max_depth: Annotated[
        int | None,
        ApiParameter("Maximum occurrence depth, relative to root when one is supplied."),
    ] = None,
    visible: Annotated[
        bool | None,
        ApiParameter("Optionally include only effectively visible or hidden occurrences."),
    ] = None,
    details: Annotated[
        bool,
        ApiParameter("Include body hashes and materials for export workflows."),
    ] = False,
    include_transform: Annotated[
        bool,
        ApiParameter("Include each occurrence's 4x4 transform matrix."),
    ] = False,
) -> dict[str, Any]:
    if max_depth is not None and max_depth < 0:
        raise ValueError("max_depth must be zero or greater.")

    app = context.app
    result: dict[str, Any] = {}
    design = _value(app, "activeProduct")
    root_component = _value(design, "rootComponent")
    occurrences = list(_value(root_component, "allOccurrences", []) or [])
    root_path = str(root) if isinstance(root, str) else None
    if root_path and not any(
        str(_value(item, "fullPathName") or _value(item, "name", "")) == root_path
        for item in occurrences
    ):
        raise ValueError(f"Occurrence root path {root_path!r} was not found.")
    root_depth = root_path.count("+") if root_path else 0
    query = name.casefold() if name else None

    for occurrence in occurrences:
        occurrence_item = _occurrence_dict(occurrence, include_transform)
        path = occurrence_item["path"]
        if root_path and path != root_path and not path.startswith(root_path + "+"):
            continue
        if max_depth is not None and occurrence_item["depth"] - root_depth > max_depth:
            continue
        component = _value(occurrence, "component")
        component_name = str(_value(component, "name", ""))
        if query and query not in f"{path} {component_name}".casefold():
            continue
        if visible is not None and occurrence_item["visible"] is not visible:
            continue
        component_id = _value(component, "id")
        if component_id not in result:
            result[component_id] = {
                "id": component_id,
                "name": component_name,
                "bodies": [
                    _component_body(body, details)
                    for body in _value(component, "bRepBodies", []) or []
                ],
                "occurrences": [],
            }
        result[component_id]["occurrences"].append(occurrence_item)
    return result
