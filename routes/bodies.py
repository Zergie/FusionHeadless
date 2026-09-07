"""Bodies helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Any
from routing import api_route
from routes._bodies import _all_bodies
from routes._bodies import _body_dict
from fusion_support import _value


@api_route("/bodies")
def bodies_route(context: Any) -> dict[str, Any]:
    app = context.app
    result: dict[str, Any] = {}
    for body in _all_bodies(_value(app, "activeProduct")):
        item = _body_dict(body, count=0)
        result.setdefault(item["id"], item)["count"] += 1
    return result
