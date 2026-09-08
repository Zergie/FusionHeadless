#!/usr/bin/env python3
"""Prepare local STL export manifests from FusionHeadless component JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


def str2hash(string: str) -> str:
    """Keep the legacy path-based manifest identifiers."""
    digest = hashlib.md5(string.encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:]}"


def _compare_key(name: str) -> str:
    name = name.replace(" ", "_").lower()
    if name.endswith(".stl"):
        name = name[:-4]
    return "_".join(part for part in name.split("_")
                    if part != "[a]" and not re.fullmatch(r"x\d+", part)) + ".stl"


def _suggested_name(component: dict, body: dict, accent_material: str) -> str:
    def clean(name: str) -> str:
        return re.sub(r"(^\[a\]_|_x\d+( \(\d+\))?$|( \(\d+\))$)", "", name).replace(" ", "_").lower()

    component_name, body_name = clean(component["name"]), clean(body["name"])
    name = ("[a]_" if body["material"] == accent_material else "") + component_name
    if body_name != component_name and not body_name.startswith("body"):
        name = f"{body_name}/{name}"
    if component["count"] > 1:
        name += f"_x{component['count']}"
    name += ".stl"
    if Path(name).is_absolute() or ".." in name.replace("\\", "/").split("/"):
        raise ValueError(f"Invalid STL output name: {name!r}")
    return name


def match_with_files(data: dict, folder: str, base_material: str, accent_material: str) -> dict:
    """Match printed bodies to local paths without changing input or STL files.

    Return the legacy mapping of UUID.json names to export records. Ambiguous
    matches and incompatible grouped bodies fail before any output is written.
    Naming and unused-file diagnostics go to stderr.
    """
    if not isinstance(data, dict):
        raise ValueError("Components must be a JSON object keyed by component ID")
    if not os.path.isdir(folder):
        raise ValueError(f"STL folder does not exist: {folder}")
    if not base_material or not accent_material or base_material == accent_material:
        raise ValueError("Base and accent materials must be distinct nonempty names")
    paths = []
    for root, directories, files in os.walk(folder):
        directories.sort()
        paths.extend(os.path.join(root, name) for name in sorted(files)
                     if name.lower().endswith(".stl"))
    existing_paths = set(paths)
    assigned: set[str] = set()
    result: dict[str, Any] = {}
    for component in data.values():
        if not isinstance(component, dict) or not all(
            key in component for key in ("id", "name", "occurrences", "bodies")
        ):
            raise ValueError("Each component requires id, name, occurrences and bodies")
        occurrences = component["occurrences"]
        if not isinstance(occurrences, list):
            raise ValueError(f"Component {component['name']!r}: occurrences must be a list")
        if re.search(r" \(\d+\)$", component["name"]):
            continue
        for body in component["bodies"]:
            label = f"Component {component['name']!r}, body {body.get('name')!r}"
            if "material" not in body:
                raise ValueError(f"{label}: missing material")
            if body["material"] not in (base_material, accent_material):
                continue
            for key in ("name", "hash"):
                if key not in body:
                    raise ValueError(f"{label}: missing {key}")
            component_with_count = {**component, "count": len(occurrences)}
            suggested = _suggested_name(component_with_count, body, accent_material)
            fallback = _suggested_name(
                {**component_with_count, "name": body["name"]}, body, accent_material
            )
            candidates = (suggested, suggested.rsplit("/", 1)[-1], fallback)
            matches = []
            for candidate in candidates:
                parent, _, filename = candidate.rpartition("/")
                matches = [path for path in paths
                           if _compare_key(os.path.basename(path)) == _compare_key(filename)
                           and (not parent or os.path.basename(os.path.dirname(path)).lower() == parent)]
                if matches:
                    break
            if len(matches) > 1:
                raise ValueError(f"{label}: multiple matching STL files: {matches}")
            elif matches:
                path = matches[0]
            else:
                path = os.path.join(folder, suggested)
                paths.append(path)
                print(f"Warning: {label}: no existing STL; using {path}", file=sys.stderr)
            assigned.add(path)
            key = str2hash(path) + ".json"
            item = {
                "id": key[:-5], "path": path, "bodies": [body["name"]],
                "body_hashes": [body["hash"]],
                "component_id": component["id"], "component_name": component["name"],
                "suggested_name": suggested,
            }
            if key in result:
                previous = result[key]
                if previous["component_id"] != item["component_id"]:
                    raise ValueError(f"{path}: matched different components {previous['component_name']!r} and {component['name']!r}")
                if previous["suggested_name"] != suggested:
                    raise ValueError(f"{label}: bodies sharing {path} have different suggested names or materials")
                previous["bodies"].append(body["name"])
                previous["body_hashes"].append(body["hash"])
            else:
                result[key] = item
            if os.path.basename(path).lower() != suggested.rsplit("/", 1)[-1]:
                print(f"Warning: {path}: suggested name is {suggested}", file=sys.stderr)
    for path in sorted(existing_paths - assigned):
        print(f"Warning: STL is not assigned to a printed body: {path}", file=sys.stderr)
    return result


def _write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", "-f", required=True, help="Component JSON file, or '-' for stdin.")
    parser.add_argument("--match-with-files", "--folder", dest="folder", required=True, help="Existing STL tree to match.")
    parser.add_argument("--base-material", required=True)
    parser.add_argument("--accent-material", required=True)
    parser.add_argument("--output", "-o", help="Write the combined manifest here.")
    parser.add_argument("--outdir", "-O", help="Write individual UUID.json manifests here too.")
    args = parser.parse_args(arguments)
    try:
        source = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        data = json.loads(source)
        if isinstance(data, dict) and data.get("status") == "ok" and "result" in data:
            data = data["result"]
        result = match_with_files(data, args.folder, args.base_material, args.accent_material)
        if args.output:
            _write_json(Path(args.output), result)
        if args.outdir:
            for name, item in result.items():
                _write_json(Path(args.outdir) / name, item)
        if not args.output and not args.outdir:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"match_with_files: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
