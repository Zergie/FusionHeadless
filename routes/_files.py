""" files helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Any
from fusion_support import _value


def _file_dict(file: Any) -> dict[str, Any]:
    parent_folder = _value(file, "parentFolder")
    parent_project = _value(file, "parentProject")
    return {
        "id": str(_value(file, "id")), "name": str(_value(file, "name")),
        "dateModified": str(_value(file, "dateModified")),
        "versionNumber": str(_value(file, "versionNumber")),
        "latestVersionNumber": str(_value(file, "latestVersionNumber")),
        "parentFolder": {"id": _value(parent_folder, "id"), "name": _value(parent_folder, "name")},
        "parentProject": {"id": _value(parent_project, "id"), "name": _value(parent_project, "name")},
    }


def _walk_folder(folder: Any):
    for file in _value(folder, "dataFiles", []) or []:
        yield _file_dict(file)
    for child in _value(folder, "dataFolders", []) or []:
        yield from _walk_folder(child)


def _simple_file(file: Any) -> dict[str, Any]:
    return {name: _value(file, name) for name in
            ("id", "name", "dateModified", "versionNumber", "latestVersionNumber")}


def _simple_object(item: Any, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in sorted(dir(item)):
        if name.startswith("_"):
            continue
        value = _value(item, name)
        if isinstance(value, (str, int, float, bool)):
            result[name] = str(value)
    result.update(extra)
    return result


def _simple_folder(folder: Any) -> dict[str, Any]:
    return _simple_object(
        folder,
        dataFolders=[_simple_folder(x) for x in _value(folder, "dataFolders", []) or []],
        dataFiles=[_simple_file(x) for x in _value(folder, "dataFiles", []) or []],
    )
