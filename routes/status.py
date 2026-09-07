"""Status helpers and operations for FusionHeadless."""

from __future__ import annotations

import sys
from typing import Any
from context import fusion
from fusion_support import _value


@fusion
def fusion_status(context: Any) -> dict[str, Any]:
    app = context.app
    folders = _value(app, "applicationFolders")
    paths = {}
    for name in dir(folders) if folders is not None else []:
        if not name.startswith("_") and "path" in name.lower():
            paths[name] = _value(folders, name)
    return {"version": f"Autodesk Fusion v{_value(app, 'version')}",
            "python": sys.version, "paths": paths}
