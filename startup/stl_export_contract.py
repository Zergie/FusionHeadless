"""Shared values for the Export STL startup feature."""

from __future__ import annotations

from dataclasses import dataclass


BUILD_PLATE_APPEARANCE = "Build Plate"
APPLICATIONS = {
    "Export only": None,
    "Cura": "cura://open?file={url}",
    "OrcaSlicer": "orcaslicer://open?file={url}",
}


@dataclass(frozen=True)
class BodySelection:
    component: str | None
    name: str
    document: str | None = None
    entity_token: str | None = None
