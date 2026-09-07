"""Projects helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Any
from routing import api_route
from routes._files import _simple_folder
from routes._files import _simple_object
from fusion_support import _value


@api_route("/projects")
def projects_route(context: Any) -> list[dict[str, Any]]:
    app = context.app
    return [
        _simple_object(project, rootFolder=_simple_folder(_value(project, "rootFolder")))
        for project in _value(_value(app, "data"), "dataProjects", []) or []
    ]
