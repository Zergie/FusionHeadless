"""Fusion support helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Any


def _value(item: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(item, name)
    except Exception:
        return default
