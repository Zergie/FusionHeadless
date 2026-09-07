"""Components helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Any
from routing import api_route
from routes._bodies import _body_dict
from fusion_support import _value


@api_route("/components")
def components_route(context: Any) -> dict[str, Any]:
    app = context.app
    result: dict[str, Any] = {}
    design = _value(app, "activeProduct")
    root = _value(design, "rootComponent")
    for occurrence in _value(root, "allOccurrences", []) or []:
        component = _value(occurrence, "component")
        item = {
            "id": _value(component, "id"),
            "name": _value(component, "name"),
            "bodies": [
                _body_dict(body)
                for body in _value(component, "bRepBodies", []) or []
            ],
            "count": 0,
        }
        result.setdefault(item["id"], item)["count"] += 1
    return {key: value for key, value in result.items() if value["bodies"]}
