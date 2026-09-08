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
import routes
import mcp.tools as mcp_tools
import startup
from mcp import registry as mcp_registry
import routing


# Keep the public package objects stable; their leaf modules are replaced as a
# unit so deleted helpers and removed imports cannot survive a restart.
_packages = {module.__name__: module for module in (routes, mcp_tools, startup)}
_ROOT = Path(__file__).resolve().parent


def _unload_extensions() -> None:
    for name in tuple(sys.modules):
        if (name == "fusion_support" or any(
            name == package or name.startswith(package + ".")
            for package in _packages
        )):
            sys.modules.pop(name, None)
    # Python also caches child modules on their parent package.
    parent = sys.modules.get("mcp")
    if parent is not None:
        parent.__dict__.pop("tools", None)


def reset_extensions() -> str:
    """Replace all extensions and return their fingerprint, without rollback.

    Runtime declarations and deleted module attributes are discarded. Any
    import or fingerprint failure leaves no extension registrations installed;
    callers may retry the whole reset after correcting the failure.
    """
    try:
        close_startup_ui()
        _clear_definitions()
        importlib.invalidate_caches()
        _unload_extensions()
        for name, previous in _packages.items():
            fresh = importlib.import_module(name)
            # reload() retains deleted attributes. Publish a fresh import
            # through the old object so held module references remain usable.
            previous.__dict__.clear()
            previous.__dict__.update(fresh.__dict__)
            sys.modules[name] = previous
            if "." in name:
                parent, attribute = name.rsplit(".", 1)
                setattr(sys.modules[parent], attribute, previous)
        return extension_fingerprint()
    except Exception as error:
        _clear_definitions()
        _unload_extensions()
        raise RuntimeError(f"Fusion extension reset failed: {error}") from error


def close_startup_ui() -> None:
    """Close retained startup UI while already on Fusion's UI thread."""
    startup.close_fusion_ui()


def _clear_definitions() -> None:
    registry.reset()
    routing.clear_route_definitions()
    mcp_registry.clear_tool_definitions()


def extension_fingerprint() -> str:
    """Return the canonical extension inventory shared by Fusion and its child."""
    def identity(value: Any) -> str:
        return f"{value.__module__}.{value.__qualname__}"

    for name in _packages:
        if name not in sys.modules:
            raise RuntimeError(f"extension module has no source path: {name}")
    # Hash package sources, including helper files and package import lists.
    # This is source coverage, not route discovery: __init__.py owns imports.
    sources = {_ROOT / "fusion_support.py"}
    for name in _packages:
        sources.update((_ROOT / name.replace(".", "/")).rglob("*.py"))

    manifest = {
        "sources": [
            {"path": path.relative_to(_ROOT).as_posix(),
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(sources)
        ],
        "routes": [
            {
                "path": definition.path,
                "methods": sorted(definition.methods),
                "operation": identity(definition.operation),
                "binary": None if definition.binary is None else {
                    "media_type": definition.binary.media_type,
                    "filename": definition.binary.filename,
                    "disposition": definition.binary.disposition,
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
            for definition in mcp_registry.tool_definitions()
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
            and (definition.value.__module__ == FusionContext.__module__ or any(
                definition.value.__module__ == name
                or definition.value.__module__.startswith(name + ".")
                for name in _packages
            ))
        ],
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
