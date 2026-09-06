"""Own the loaded extension set, its replacement, and its shared fingerprint.

This module uses only built-in dependencies. Reset must run on Fusion's UI
thread while execution is quiescent; the adapter owns that scheduling.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
from typing import Any

from context import FusionContext, registry
import fusion_routes
import mcp_tools
import routing


# Retain module objects across failed imports so existing module references
# also see the next successful replacement. This is the reload membership.
_modules = {module.__name__: module for module in (fusion_routes, mcp_tools)}


def reset_extensions() -> str:
    """Replace all extensions and return their fingerprint, without rollback.

    Runtime declarations and deleted module attributes are discarded. Any
    import or fingerprint failure leaves no extension registrations installed;
    callers may retry the whole reset after correcting the failure.
    """
    try:
        _clear_definitions()
        importlib.invalidate_caches()
        for name in _modules:
            sys.modules.pop(name, None)
        for name, previous in _modules.items():
            fresh = importlib.import_module(name)
            # reload() retains deleted attributes. Publish a fresh import
            # through the old object so held module references remain usable.
            previous.__dict__.clear()
            previous.__dict__.update(fresh.__dict__)
            sys.modules[name] = previous
        return extension_fingerprint()
    except Exception as error:
        _clear_definitions()
        for name in _modules:
            sys.modules.pop(name, None)
        raise RuntimeError(f"Fusion extension reset failed: {error}") from error


def _clear_definitions() -> None:
    registry.reset()
    routing.clear_route_definitions()
    mcp_tools.clear_tool_definitions()


def extension_fingerprint() -> str:
    """Return the canonical extension inventory shared by Fusion and its child."""
    def identity(value: Any) -> str:
        return f"{value.__module__}.{value.__qualname__}"

    def source_hash(name: str) -> dict[str, str]:
        module = sys.modules.get(name)
        path = getattr(module, "__file__", None)
        if not isinstance(path, str):
            raise RuntimeError(f"extension module has no source path: {name}")
        return {"module": name, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}

    manifest = {
        "sources": [source_hash(name) for name in _modules],
        "routes": [
            {
                "path": definition.path,
                "methods": sorted(definition.methods),
                "operation": identity(definition.operation),
                "binary": None if definition.binary is None else {
                    "media_type": definition.binary.media_type,
                    "content_disposition": definition.binary.content_disposition,
                    "defaults": definition.binary.defaults,
                },
            }
            for definition in sorted(routing.route_definitions(), key=lambda item: item.path)
        ],
        "tools": [
            {
                "name": definition.name,
                "description": definition.description,
                "input_schema": definition.input_schema,
                "required": definition.required,
                "operation": identity(definition.operation),
            }
            for definition in mcp_tools.tool_definitions()
        ],
        "definitions": [
            {
                "target": definition.target,
                "name": definition.name,
                "identity": identity(definition.value),
                "class_identity": identity(definition.value)
                if isinstance(definition.value, type) else None,
            }
            for definitions in (registry.fusion, registry.server)
            for definition in sorted(definitions.values(), key=lambda item: item.name)
            if getattr(definition.value, "__module__", None)
            in {FusionContext.__module__, *_modules}
        ],
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
