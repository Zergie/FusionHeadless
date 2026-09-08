"""Explicit child-owned startup features."""

from __future__ import annotations

from typing import Any

from startup import stl_export


_FEATURES = (stl_export,)


def install(runtime: Any, origin: str, owner_token: str) -> bool:
    """Install every startup feature before an active child reports ready."""
    installed = []
    try:
        for feature in _FEATURES:
            if feature.install(runtime, origin, owner_token):
                installed.append(feature)
    except Exception:
        for feature in reversed(installed):
            feature.uninstall(runtime, owner_token)
        raise
    return bool(installed)


def uninstall(runtime: Any, owner_token: str) -> None:
    """Remove features owned by this child, in reverse installation order."""
    errors = []
    for feature in reversed(_FEATURES):
        try:
            feature.uninstall(runtime, owner_token)
        except Exception as error:
            errors.append(error)
    if errors:
        raise RuntimeError("; ".join(str(error) for error in errors))


def cancel(owner_token: str) -> None:
    """Cancel child-side work without calling back into Fusion."""
    for feature in reversed(_FEATURES):
        feature.cancel(owner_token)


def close_fusion_ui() -> None:
    """Close retained Fusion UI before startup modules are reloaded."""
    for feature in reversed(_FEATURES):
        feature.close_fusion_ui()
