"""Read the FusionHeadless release version from its manifest."""

from __future__ import annotations

import json
from pathlib import Path


MANIFEST_PATH = Path(__file__).resolve().with_name("FusionHeadless.manifest")


def manifest_version(path: str | Path = MANIFEST_PATH) -> str:
    """Return the single authoritative application/API version."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"FusionHeadless manifest has no valid version: {path}")
    return version.strip()
