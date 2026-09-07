"""Files helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Annotated, Any
from routing import ApiParameter, api_route
from routes._files import _file_dict
from fusion_support import _value
from routes._files import _walk_folder


@api_route("/files")
def files_route(
    context: Any,
    active: Annotated[
        bool,
        ApiParameter("Return the active document's data file."),
    ] = False,
    id: Annotated[
        str | None,
        ApiParameter("Return the data file with this Fusion identifier."),
    ] = None,
    name: Annotated[
        str | None,
        ApiParameter("Filter data files by case-insensitive name."),
    ] = None,
) -> Any:
    app = context.app
    if active:
        return [_file_dict(_value(_value(app, "activeDocument"), "dataFile"))]
    elif id is not None:
        return _file_dict(_value(_value(app, "data"), "findFileById")(id))
    else:
        files = [item for project in _value(_value(app, "data"), "dataProjects", []) or []
                 for item in _walk_folder(_value(project, "rootFolder"))]
        if name is not None:
            return [item for item in files
                    if item["name"].lower() == name.lower()]
        else:
            return files
