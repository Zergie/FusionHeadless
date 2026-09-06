"""Builtin-only read routes executed through the Fusion-side context."""

from __future__ import annotations

import datetime
import hashlib
import asyncio
import math
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from typing import Annotated, Any, Callable, Literal

from context import fusion, server
from routing import ApiParameter, api_route, BinaryResponse


def _eval_attribute(value: Any, attribute: str) -> Any:
    if attribute in ("this", "objectType"):
        return None
    try:
        return getattr(value, attribute)
    except Exception:
        return None


def _eval_sort_attribute(attribute: str) -> str:
    order = {"id": 0, "name": 1, "description": 2}
    return f"{order.get(attribute, 3):02d}_{attribute}"


def _eval_to_json(value: Any, max_depth: int, depth: int = 0) -> Any:
    if type(value).__name__ in ("method", "function", "NoneType") or value is None:
        result = None
    elif isinstance(value, (int, float, str, bool)):
        result = value
    elif isinstance(value, (list, tuple)):
        result = ([_eval_to_json(item, max_depth, depth + 1) for item in value]
                  if depth < max_depth else [])
    elif isinstance(value, dict):
        result = ({key: _eval_to_json(item, max_depth, depth + 1)
                   for key, item in value.items()} if depth < max_depth else {})
    elif hasattr(value, "asArray") and callable(value.asArray):
        result = ([_eval_to_json(item, max_depth, depth + 1) for item in value.asArray()]
                  if depth < max_depth else [])
    elif hasattr(value, "asDict") and callable(value.asDict):
        result = ({key: _eval_to_json(item, max_depth, depth + 1)
                   for key, item in value.asDict().items()} if depth < max_depth else {})
    elif hasattr(value, "__iter__") and callable(value.__iter__):
        result = ({key: _eval_to_json(item, max_depth, depth + 1) for key, item in value}
                  if depth < max_depth else {})
    else:
        result = ({key: _eval_to_json(_eval_attribute(value, key), max_depth, depth + 1)
                   for key in sorted(dir(value), key=_eval_sort_attribute)
                   if not key.startswith("_")} if depth < max_depth else {})

    if isinstance(type(value), type) and type(value).__module__ == "builtins":
        return result
    elif isinstance(result, (list, tuple)):
        return {"items": [item for item in result if item is not None],
                "objectType": f"https://help.autodesk.com/view/fusion360/ENU/?cg=Developer%27s%20Documentation&query={type(value).__name__}%20Object"}
    elif isinstance(result, dict):
        result["objectType"] = f"https://help.autodesk.com/view/fusion360/ENU/?cg=Developer%27s%20Documentation&query={type(value).__name__}%20Object"
        return {key: item for key, item in result.items() if item is not None}
    else:
        return result


@api_route("/eval", methods=("POST",))
def fusion_eval(
    context: Any,
    code: Annotated[str, ApiParameter("Python expression to evaluate in Fusion.")],
    depth: Annotated[
        int | None,
        ApiParameter("Optional depth for serializing Fusion objects."),
    ] = None,
) -> Any:
    app, ui, adsk = context.app, context.ui, context.adsk
    namespace = {"__builtins__": __builtins__, "app": app, "ui": ui, "adsk": adsk}
    result = eval(code, namespace)
    if depth is not None:
        result = _eval_to_json(result, int(depth))
    return result


class GenericParameter:
    """Adapter for Fusion properties that expose parameter-like values."""

    def __init__(self, name: str, parent: Any, prop: str) -> None:
        self.name = name
        self.parent = parent
        self.property = prop

    @property
    def expression(self) -> Any:
        return getattr(self.parent, self.property)

    @expression.setter
    def expression(self, value: Any) -> None:
        prop_type = type(self.expression)
        if isinstance(value, str):
            if prop_type is bool:
                value = value.lower() in ("true", "1", "yes", "on")
            elif prop_type is int:
                value = int(value)
            elif prop_type is float:
                value = float(value)
            elif prop_type is not str:
                try:
                    value = prop_type(value)
                except Exception:
                    pass
        try:
            limits = getattr(self.parent, f"{self.property[:-5]}Limits", None)
            if limits is not None and limits.minimumValue != limits.maximumValue:
                value = max(limits.minimumValue, min(limits.maximumValue, value))
        except Exception:
            pass
        setattr(self.parent, self.property, value)


def _iter_parameters_in_component(design: Any, component: Any):
    for sketch in _value(component, "sketches", []) or []:
        for dimension in _value(sketch, "sketchDimensions", []) or []:
            yield _value(dimension, "parameter")
        for index, text in enumerate(_value(sketch, "sketchTexts", []) or []):
            yield GenericParameter(f"{_value(sketch, 'name', '')}-{index}", text, "text")
    for joint in _value(component, "joints", []) or []:
        motion = _value(joint, "jointMotion")
        if _value(motion, "jointType") == 0:
            continue
        for prop in sorted(name for name in dir(motion)
                           if not name.startswith("_") and name.endswith("Value")):
            yield GenericParameter(f"{_value(joint, 'name', '')}-{prop[:-5]}", motion, prop)
    if _value(design, "designType") == 1:
        yield from (_value(component, "modelParameters", []) or [])


def _iter_parameters(design: Any):
    if _value(design, "designType") == 1:
        yield from (_value(design, "userParameters", []) or [])
    yield from _iter_parameters_in_component(design, _value(design, "rootComponent"))
    for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
        yield from _iter_parameters_in_component(design, _value(occurrence, "component"))


def _parameter_sort(item: tuple[str, Any]) -> tuple[Any, ...]:
    match = re.match(r"^d(\d+)", item[0])
    if match:
        return (2, int(match.group(1)))
    elif match := re.match(r"^([^\d]+)(\d+)", item[0]):
        return (1, match.group(1), int(match.group(2)))
    else:
        return (0, item[0].lower())


def _value(item: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(item, name)
    except Exception:
        return default


def _round(value: Any, places: int) -> float:
    result = round(value, places)
    return 0.0 if -10 ** -places < result < 10 ** -places else result


def _uuid_hash(value: str) -> str:
    digest = hashlib.md5(value.encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:]}"


def _body_orientation(body: Any) -> list[tuple[float, ...]]:
    orientations: set[tuple[float, ...]] = set()
    for face in _value(body, "faces", []) or []:
        appearance_name = _value(_value(face, "appearance"), "name")
        if not isinstance(appearance_name, str) or "Build Plate" not in appearance_name:
            continue
        normal_array = _value(_value(_value(face, "geometry"), "normal"), "asArray")
        if not callable(normal_array):
            continue
        try:
            values = normal_array()
            reversed_normal = bool(_value(face, "isParamReversed", False))
            orientations.add(tuple(
                _round(-value if reversed_normal else value, 5)
                for value in values
            ))
        except Exception:
            continue
    return list(orientations)


def _body_dict(body: Any, **extra: Any) -> dict[str, Any]:
    parent = _value(body, "parentComponent")
    name = str(_value(body, "name", ""))
    parent_id = str(_value(parent, "id", ""))
    identifier = _uuid_hash(f"{name}-{parent_id}")
    physical = _value(body, "physicalProperties")
    center = _value(_value(physical, "centerOfMass"), "asArray")
    center = center() if callable(center) else []
    bounding = _value(body, "boundingBox")
    minimum = _value(_value(bounding, "minPoint"), "asArray")
    maximum = _value(_value(bounding, "maxPoint"), "asArray")
    minimum = minimum() if callable(minimum) else []
    maximum = maximum() if callable(maximum) else []
    appearance = _value(body, "appearance")
    properties = _value(appearance, "appearanceProperties", []) or []
    color = "00000000"
    for prop in properties:
        if _value(prop, "name") == "Color":
            value = _value(prop, "value")
            if value is not None:
                color = "%0.2X%0.2X%0.2XFF" % (
                    _value(value, "red", 0), _value(value, "green", 0),
                    _value(value, "blue", 0),
                )
            break
    result: dict[str, Any] = {
        "id": identifier, "hash": None, "name": name,
        "volume": _round(_value(physical, "volume", 0), 5),
        "mass": _round(_value(physical, "mass", 0), 5),
        "area": _round(_value(physical, "area", 0), 5), "color": color,
        "centerOfMass": [_round(value, 3) for value in center],
        "material": _value(_value(body, "material"), "name"),
        "orientation": _body_orientation(body),
        "boundingBox": {"min": [_round(value, 3) for value in minimum],
                         "max": [_round(value, 3) for value in maximum]},
    }
    result["hash"] = _uuid_hash(str(result))
    result.update(extra)
    return result


def _all_bodies(design: Any) -> list[Any]:
    root = _value(design, "rootComponent")
    if root is None:
        raise RuntimeError("Design does not have a rootComponent.")
    result = list(_value(root, "bRepBodies", []) or [])
    for occurrence in _value(root, "allOccurrences", []) or []:
        result.extend(_value(_value(occurrence, "component"), "bRepBodies", []) or [])
    return result


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


@api_route("/bodies")
def bodies_route(context: Any) -> dict[str, Any]:
    app = context.app
    result: dict[str, Any] = {}
    for body in _all_bodies(_value(app, "activeProduct")):
        item = _body_dict(body, count=0)
        result.setdefault(item["id"], item)["count"] += 1
    return result


@api_route("/components")
def components_route(context: Any) -> dict[str, Any]:
    app = context.app
    result: dict[str, Any] = {}
    design = _value(app, "activeProduct")
    root = _value(design, "rootComponent")
    for occurrence in _value(root, "allOccurrences", []) or []:
        component = _value(occurrence, "component")
        item = {
            "id": _value(component, "id"),
            "name": _value(component, "name"),
            "bodies": [
                _body_dict(body)
                for body in _value(component, "bRepBodies", []) or []
            ],
            "count": 0,
        }
        result.setdefault(item["id"], item)["count"] += 1
    return {key: value for key, value in result.items() if value["bodies"]}


@api_route("/projects")
def projects_route(context: Any) -> list[dict[str, Any]]:
    app = context.app
    return [
        _simple_object(project, rootFolder=_simple_folder(_value(project, "rootFolder")))
        for project in _value(_value(app, "data"), "dataProjects", []) or []
    ]


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


class Visibility:
    HIDE = 0
    SHOW = 1
    ISOLATE = 2


def _set_control_definition(ui: Any, identity: str, value: Any) -> Any:
    """Apply a Fusion list control value and return its previous selection."""
    if value is None:
        return None
    definitions = _value(ui, "commandDefinitions")
    command = _value(definitions, "itemById")(identity)
    items = _value(_value(command, "controlDefinition"), "listItems")
    if items is None:
        raise RuntimeError(f"Fusion control '{identity}' does not expose list items")
    count = int(_value(items, "count", 0))
    if isinstance(value, list):
        if len(value) != count:
            raise ValueError(
                f"Fusion control '{identity}' requires {count} selection values"
            )
        old = [bool(_value(items.item(index), "isSelected", False))
               for index in range(count)]
        for index in range(count):
            items.item(index).isSelected = bool(value[index])
    elif isinstance(value, bool):
        old = [bool(_value(items.item(index), "isSelected", False))
               for index in range(count)]
        for index in range(count):
            items.item(index).isSelected = value
    elif isinstance(value, int):
        selected = [index for index in range(count)
                    if bool(_value(items.item(index), "isSelected", False))]
        old = selected[0] if len(selected) == 1 else None
        if not 0 <= value < count:
            raise ValueError(
                f"Fusion control '{identity}' selection {value} is outside 0..{count - 1}"
            )
        items.item(value).isSelected = True
    else:
        raise ValueError(
            f"Fusion control '{identity}' requires a boolean, integer, or list"
        )
    return old


def _all_bodies_and_occurrences(design: Any):
    root = _value(design, "rootComponent")
    for body in _value(root, "bRepBodies", []) or []:
        yield body
    for occurrence in _value(root, "allOccurrences", []) or []:
        for body in _value(_value(occurrence, "component"), "bRepBodies", []) or []:
            yield body


def _set_visibility(design: Any, name: str, mode: int) -> None:
    if name == "all":
        for _ in range(2):
            for body in _all_bodies_and_occurrences(design):
                body.isLightBulbOn = mode == Visibility.SHOW
            for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
                occurrence.isLightBulbOn = mode == Visibility.SHOW
        return
    for _ in range(2):
        for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
            occurrence_name = str(_value(occurrence, "name", ""))
            match = re.match(r"^(?:(.+)( v\d+)|(.+))(:\d+)$", occurrence_name)
            normalized_name = (match.group(1) or match.group(3)) if match else occurrence_name
            if name in (occurrence_name, normalized_name):
                if mode == Visibility.ISOLATE:
                    occurrence.isIsolated = True
                    stack = [occurrence]
                    while stack:
                        item = stack.pop()
                        stack.extend(_value(item, "childOccurrences", []) or [])
                        if not _value(item, "isVisible", True):
                            item.isLightBulbOn = True
                occurrence.isLightBulbOn = mode != Visibility.HIDE
            else:
                bodies = _value(occurrence, "bRepBodies")
                if bodies is None:
                    bodies = _value(_value(occurrence, "component"), "bRepBodies", [])
                for body in bodies or []:
                    if _value(body, "name") == name:
                        if mode == Visibility.ISOLATE:
                            occurrence.isIsolated = True
                        body.isLightBulbOn = mode != Visibility.HIDE


@server
def _orient_export_file(path: str, planes: list[dict[str, Any]]) -> None:
    """Postprocess Fusion's temporary STL using dependencies in the child only."""
    from pathlib import Path
    from stl_orientation import orient_stl

    file = Path(path)
    file.write_bytes(orient_stl(file.read_bytes(), planes))


def _export_file(
    export_manager: Any, options: Any, description: str,
    postprocess: Callable[[str], None] | None = None,
) -> bytes:
    """Return a successful export, cleaning its temporary file on every exit."""
    path = options.filename
    try:
        try:
            succeeded = export_manager.execute(options)
        except Exception as error:
            raise RuntimeError(f"Fusion failed to export {description}: {error}") from error
        if not succeeded:
            raise RuntimeError(f"Fusion failed to export {description}")
        if postprocess is not None:
            postprocess(path)
        with open(path, "rb") as output:
            return output.read()
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _export_selection(product: Any, component: str | None, names: list[str] | None):
    """Resolve and validate export selectors before changing Fusion state."""
    root = product.rootComponent
    target = root
    if component is not None:
        target = next((occ.component for occ in root.allOccurrences
                       if _value(occ.component, "name") == component
                       or _value(occ.component, "id") == component), None)
        if target is None:
            raise ValueError(f"Component '{component}' not found")
    available = list(target.bRepBodies)
    if names is None:
        selected = available
    else:
        missing = set(names) - {item.name for item in available}
        if missing:
            raise ValueError(f"Bodies {sorted(missing)!r} not found in component '{target.name}'")
        selected = [item for item in available if item.name in names]
    return target, available, selected


@contextmanager
def _export_visibility(changes: list[tuple[Any, bool]]):
    """Snapshot all affected items before mutation and restore on every exit."""
    visibility = [(item, item.isLightBulbOn) for item, _ in changes]
    try:
        for item, state in changes:
            item.isLightBulbOn = state
        yield
    finally:
        for item, state in visibility:
            item.isLightBulbOn = state


def _export_oriented_stl(
    context: Any, target: Any, available: list[Any], selected: list[Any],
    appearance_marker: str,
) -> bytes:
    """Validate contact planes and export with temporary visibility changes."""
    if not appearance_marker.strip():
        raise ValueError("orient appearance name must not be empty or whitespace-only")
    product, adsk = context.app.activeProduct, context.adsk
    if not selected:
        raise ValueError("Oriented STL export requires at least one body")

    planes = []
    for item in selected:
        marked = 0
        for face in item.faces:
            appearance = _value(_value(face, "appearance"), "name", "")
            if not isinstance(appearance, str) or appearance_marker not in appearance:
                continue
            label = f"Component '{target.name}', body '{item.name}', contact face appearance {appearance!r}"
            plane = adsk.core.Plane.cast(face.geometry)
            if plane is None:
                raise ValueError(f"{label}: contact face must be planar")
            normal = list(plane.normal.asArray())
            if face.isParamReversed:
                normal = [-value for value in normal]
            planes.append({"normal": normal,
                           "point": [value * 10 for value in plane.origin.asArray()],
                           "label": label})
            marked += 1
        if not marked:
            raise ValueError(f"Component '{target.name}', body '{item.name}': no planar face marked with an appearance containing {appearance_marker!r}")

    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.stl")
    # Export one body directly; for groups, temporarily expose only the chosen
    # native bodies and hide child occurrences. Never transform the CAD model.
    changes = []
    if len(selected) == 1:
        geometry = selected[0]
    else:
        geometry = target
        selected_names = {item.name for item in selected}
        changes = [(item, item.name in selected_names) for item in available]
        changes.extend((item, False) for item in _value(target, "occurrences", []) or [])
    with _export_visibility(changes):
        options = product.exportManager.createSTLExportOptions(geometry, path)
        options.isBinaryFormat = True
        options.unitType = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
        return _export_file(
            product.exportManager, options, f"oriented STL for component '{target.name}'",
            postprocess=lambda filename: context.call_server(_orient_export_file, filename, planes),
        )


@api_route(
    "/export",
    methods=("POST",),
    binary=BinaryResponse(
        "application/octet-stream",
        'attachment; filename="export.{format}"',
        {"format": "step"},
    ),
)
def export_route(
    context: Any,
    format: Annotated[
        Literal["f3d", "step", "stl", "3mf", "obj"],
        ApiParameter("Fusion export format."),
    ] = "step",
    component: Annotated[
        str | None,
        ApiParameter("Component name or identifier to export."),
    ] = None,
    body: Annotated[
        list[str] | None,
        ApiParameter("One or more body names to export."),
    ] = None,
    orient: Annotated[
        str | None,
        ApiParameter("STL contact-face appearance substring (case-sensitive). Point matching faces down, center XY, and place the contact plane on Z=0. Omit or use null to keep the original orientation. Ignored for other formats."),
    ] = None,
) -> bytes:
    """Export the requested Fusion design item and return its raw file bytes."""
    app = context.app
    product = _value(app, "activeProduct")
    export_manager = _value(product, "exportManager")
    if export_manager is None:
        raise RuntimeError("Active product does not support exportManager")
    format_name = format.lower()
    if format_name not in {"f3d", "step", "stl", "3mf", "obj"}:
        raise ValueError(f"Unsupported export format: {format_name}")
    target, available, selected = _export_selection(product, component, body)
    if format_name == "stl" and orient is not None:
        if body is None and list(_value(target, "occurrences", []) or []):
            raise ValueError("Oriented STL export of an assembly requires explicit body names in one component")
        return _export_oriented_stl(context, target, available, selected, orient)
    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.{format_name}")
    geometry = selected[0] if body is not None and len(body) == 1 else target
    # Preserve ordinary export's geometry/visibility during execution, but
    # restore every affected native body and occurrence when it finishes.
    changes = [(item, True) for item in _all_bodies_and_occurrences(product)]
    changes.extend((item, True) for item in product.rootComponent.allOccurrences)
    # Fusion may require a second pass after revealing parent occurrences.
    changes *= 2
    if body is not None and len(body) != 1:
        selected_names = {item.name for item in selected}
        changes.extend((item, item.name in selected_names) for item in available)
    with _export_visibility(changes):
        if format_name == "f3d":
            options = export_manager.createFusionArchiveExportOptions(path, geometry)
        elif format_name == "step":
            options = export_manager.createSTEPExportOptions(path, geometry)
        elif format_name == "stl":
            options = export_manager.createSTLExportOptions(geometry, path)
        elif format_name == "3mf":
            options = export_manager.createC3MFExportOptions(geometry, path)
        else:
            options = export_manager.createOBJExportOptions(geometry, path)
        return _export_file(export_manager, options, f"{format_name} for '{_value(geometry, 'name', 'active design')}'")


@api_route(
    "/render",
    methods=("POST",),
    binary=BinaryResponse("image/png", 'inline; filename="render.png"'),
)
def render_route(
    context: Any,
    quality: Annotated[
        str | int,
        ApiParameter("Visual style name or local-render quality from 25 to 100."),
    ] = "ShadedWithVisibleEdgesOnly",
    focalLength: Annotated[
        float | None,
        ApiParameter("Perspective camera focal length in millimeters."),
    ] = None,
    camera: Annotated[
        int | None,
        ApiParameter("Fusion camera-mode control selection."),
    ] = None,
    show: Annotated[
        list[str] | None,
        ApiParameter("Occurrence or body names to show."),
    ] = None,
    hide: Annotated[
        list[str] | None,
        ApiParameter("Occurrence or body names to hide."),
    ] = None,
    isolate: Annotated[
        list[str] | None,
        ApiParameter("Occurrence or body names to isolate."),
    ] = None,
    view: Annotated[
        str | None,
        ApiParameter("Home or a named Fusion view to apply."),
    ] = None,
    width: Annotated[int, ApiParameter("Output width in pixels.")] = 1280,
    height: Annotated[int, ApiParameter("Output height in pixels.")] = 1024,
    isBackgroundTransparent: Annotated[
        bool,
        ApiParameter("Render with a transparent background."),
    ] = False,
    isAntiAliased: Annotated[
        bool,
        ApiParameter("Enable anti-aliasing for viewport captures."),
    ] = True,
    exposure: Annotated[
        float | None,
        ApiParameter("Local-render camera exposure."),
    ] = None,
) -> bytes:
    """Render the active viewport and return an exact PNG byte payload."""
    app, ui, adsk = context.app, context.ui, context.adsk
    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.png")
    quality, visual_style = {
        "Shaded": (None, 0), "ShadedWithHiddenEdges": (None, 1),
        "ShadedWithVisibleEdgesOnly": (None, 2), "Wireframe": (None, 3),
        "WireframeWithHiddenEdges": (None, 4), "WireframeWithVisibleEdgesOnly": (None, 5),
    }.get(quality, (quality, None))
    quality = int(quality) if quality is not None else None
    visual_style = int(visual_style) if visual_style is not None else None
    if quality is not None and not 25 <= quality <= 100:
        raise ValueError("Quality must be between 25 and 100, or a valid visual style must be specified.")
    product = _value(app, "activeProduct")
    viewport = _value(app, "activeViewport")
    old_style = _value(viewport, "visualStyle")
    old_camera_control = None
    old_visibility_control = None
    try:
        if focalLength is not None:
            old_camera_control = _set_control_definition(
                ui, "ViewCameraCommand", 1
            )
            camera = viewport.camera
            camera.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
            camera.isSmoothTransition = False
            camera.perspectiveAngle = 2.0 * math.atan(
                12.0 / focalLength
            )
            viewport.camera = camera
            viewport.refresh()
        else:
            old_camera_control = _set_control_definition(
                ui, "ViewCameraCommand", camera
            )
        # Explicit exclusions win over children revealed by isolation.
        for values, mode in ((show, Visibility.SHOW), (isolate, Visibility.ISOLATE),
                             (hide, Visibility.HIDE)):
            for item in values or []:
                _set_visibility(product, str(item), mode)
        if view is not None:
            if view.lower() == "home":
                viewport.goHome()
                viewport.fit()
            else:
                named_views = _value(_value(_value(app, "activeDocument"), "design"), "namedViews")
                named_view = _value(named_views, "itemByName")(view)
                if named_view is None:
                    raise RuntimeError(f"Named view '{view}' not found")
                named_view.apply()
        selections = _value(ui, "activeSelections")
        if selections is not None:
            selections.clear()
        adsk.doEvents()
        if visual_style is not None:
            old_visibility_control = _set_control_definition(
                ui, "VisibilityOverrideCommand", False
            )
            options = adsk.core.SaveImageFileOptions.create(path)
            options.width = width
            options.height = height
            options.isBackgroundTransparent = isBackgroundTransparent
            options.isAntiAliased = isAntiAliased
            viewport.visualStyle = visual_style
            viewport.saveAsImageFileWithOptions(options)
        elif quality is not None:
            camera = viewport.camera
            target = camera.target
            direction = target.vectorTo(camera.eye)
            direction.normalize()
            direction.scaleBy(camera.eye.distanceTo(target) * 0.455)
            eye = target.copy()
            eye.translateBy(direction)
            camera.eye = eye
            camera.target = target
            camera.isSmoothTransition = False
            camera.cameraType = adsk.core.CameraTypes.PerspectiveCameraType

            manager = product.renderManager
            scene = manager.sceneSettings
            scene.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
            if exposure is not None:
                scene.cameraExposure = exposure

            rendering = manager.rendering
            rendering.aspectRatio = adsk.fusion.RenderAspectRatios.CustomRenderAspectRatio
            rendering.resolution = adsk.fusion.RenderResolutions.CustomRenderResolution
            rendering.resolutionWidth = width
            rendering.resolutionHeight = height
            rendering.isBackgroundTransparent = isBackgroundTransparent
            rendering.renderQuality = quality
            rendering.startLocalRender(path, camera)
        async def wait_for_file() -> None:
            while not os.path.exists(path):
                adsk.doEvents(); await asyncio.sleep(1)
        asyncio.run(asyncio.wait_for(wait_for_file(), timeout=180))
        with open(path, "rb") as file:
            return file.read()
    except asyncio.TimeoutError as error:
        raise RuntimeError("Failed to render within 180 seconds.") from error
    finally:
        viewport.visualStyle = old_style
        _set_control_definition(
            ui, "VisibilityOverrideCommand", old_visibility_control
        )
        _set_control_definition(ui, "ViewCameraCommand", old_camera_control)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


@api_route("/document", methods=("POST",))
def document_route(
    context: Any,
    open: Annotated[
        str | None,
        ApiParameter("Fusion data-file identifier to open."),
    ] = None,
    close: Annotated[
        bool | None,
        ApiParameter("Close the active document and optionally save changes."),
    ] = None,
) -> Any:
    """Perform the legacy document operation on Fusion's UI thread."""
    app, adsk = context.app, context.adsk
    if open is not None:
        identity = open.strip()
        active = _value(app, "activeDocument")
        if (_value(_value(active, "dataFile"), "id") == identity):
            return "File is already active."
        file = _value(_value(app, "data"), "findFileById")(identity)
        if not file:
            raise RuntimeError(f"File with ID '{identity}' not found.")
        _value(app, "documents").open(file)

        async def wait_until_active() -> None:
            while _value(_value(_value(app, "activeDocument"), "dataFile"), "id") != identity:
                adsk.doEvents()
                await asyncio.sleep(0.5)

        try:
            asyncio.run(asyncio.wait_for(wait_until_active(), timeout=30))
            return "File opened successfully."
        except asyncio.TimeoutError as error:
            raise RuntimeError(
                f"Failed to open file with ID '{identity}' within 30 seconds."
            ) from error
    elif close is not None:
        active = _value(app, "activeDocument")
        if active is not None and _value(active, "dataFile") is not None:
            active.close(close)
            return "File closed successfully."
        return "No active document to close."
    else:
        raise ValueError("Document operation must specify open or close.")


@api_route("/parameter", methods=("GET", "POST"))
def parameter_route(
    context: Any,
    set: Annotated[
        list[str] | None,
        ApiParameter("Repeated NAME=EXPRESSION design-parameter updates."),
    ] = None,
) -> dict[str, Any]:
    """List or update design parameters on Fusion's UI thread."""
    app = context.app
    design = _value(app, "activeProduct")
    updates: dict[str, str] = {}
    if set is not None:
        if not set:
            raise ValueError("'set' must contain at least one NAME=EXPRESSION value")
        for assignment in set:
            if "=" not in assignment:
                raise ValueError(
                    f"Invalid parameter update '{assignment}'; expected NAME=EXPRESSION"
                )
            name, expression = assignment.split("=", 1)
            name = name.strip()
            if not name:
                raise ValueError(
                    f"Invalid parameter update '{assignment}'; name must not be empty"
                )
            updates[name] = expression
    requested = list(updates)
    result: dict[str, Any] = {}
    for parameter in _iter_parameters(design):
        if parameter is None:
            continue
        if not requested:
            result[parameter.name] = parameter.expression
        elif parameter.name in requested:
            requested.remove(parameter.name)
            parameter.expression = updates[parameter.name]
            result[parameter.name] = parameter.expression
        if requested == [] and updates:
            break
    for name in requested:
        result[name] = f"Parameter '{name}' not found."
    return dict(sorted(result.items(), key=_parameter_sort))


def _find_occurrence(identity: Any, design: Any) -> Any:
    identities = [identity] if isinstance(identity, str) else identity
    for item in identities or []:
        for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
            component = _value(occurrence, "component")
            if _value(component, "name") == item or _value(component, "id") == item:
                return occurrence
    return None


def _assembly_contexts(occurrence: Any) -> list[Any]:
    contexts: list[Any] = []
    context = _value(occurrence, "assemblyContext")
    while context is not None:
        contexts.append(context)
        context = _value(context, "assemblyContext")
    contexts.reverse()
    return contexts


@api_route("/select", methods=("POST",))
def select_route(
    context: Any,
    id: Annotated[
        str | list[str] | None,
        ApiParameter("Component identifier to select."),
    ] = None,
    name: Annotated[
        str | list[str] | None,
        ApiParameter("Component name to select."),
    ] = None,
    focus: Annotated[
        bool,
        ApiParameter("Bring the Fusion window to the foreground on Windows."),
    ] = True,
) -> dict[str, Any]:
    """Select and isolate a component occurrence on Fusion's UI thread."""
    app, ui = context.app, context.ui
    design = _value(app, "activeProduct")
    identity = id if id is not None else name
    occurrence = _find_occurrence(identity, design)
    if occurrence is None:
        raise RuntimeError(f"Occurrence with id or name '{identity}' not found.")
    contexts = _assembly_contexts(occurrence)
    if contexts:
        for context in contexts:
            context.isLightBulbOn = True
            context.isIsolated = True
        context_ids = {_value(_value(context, "component"), "id") for context in contexts}
        for context in contexts:
            for item in _value(context, "childOccurrences", []) or []:
                if (_value(item, "isVisible", True)
                        and _value(_value(item, "component"), "id") != _value(_value(occurrence, "component"), "id")
                        and _value(_value(item, "component"), "id") not in context_ids):
                    item.isLightBulbOn = False
    else:
        occurrence.isIsolated = True
    if not contexts and not _value(occurrence, "isVisible", True):
        for item in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
            item.isLightBulbOn = False
        occurrence.isLightBulbOn = True
        _value(occurrence, "component").isLightBulbOn = True
    selections = _value(ui, "activeSelections")
    selections.clear()
    selections.add(occurrence)
    command = _value(_value(ui, "commandDefinitions"), "itemById")("FindInBrowser")
    _value(command, "execute")()
    selections.clear()
    viewport = _value(app, "activeViewport")
    _value(viewport, "goHome")()
    _value(viewport, "fit")()
    if focus:
        try:
            import win32gui  # type: ignore
            windows: list[tuple[Any, str]] = []
            win32gui.EnumWindows(
                lambda hwnd, _: windows.append((hwnd, win32gui.GetWindowText(hwnd)))
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd)
                and "Fusion" in win32gui.GetWindowText(hwnd) else None,
                None,
            )
            if windows:
                hwnd, _ = sorted(windows, key=lambda item: len(item[1]))[-1]
                win32gui.ShowWindow(hwnd, 6)
                win32gui.ShowWindow(hwnd, 9)
        except Exception:
            pass
    return {"id": _value(_value(occurrence, "component"), "id"),
            "name": _value(_value(occurrence, "component"), "name")}


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


def _scripts(app: Any) -> dict[str, Any]:
    """Return Fusion scripts and add-ins indexed by their unique Script IDs."""
    scripts = _value(app, "scripts")
    item = _value(scripts, "item")
    count = _value(scripts, "count", 0)
    if not callable(item) or not isinstance(count, int):
        return {}
    return {
        str(_value(script, "id")): script
        for index in range(count)
        if (script := item(index)) is not None
    }


def _programming_language(value: Any) -> str:
    """Return Fusion's programming-language enum as a readable name."""
    return {
        0: "Prompt",
        1: "Python",
        2: "C++",
        3: "TypeScript",
    }.get(value, str(value))


def _script_details(scripts: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize Fusion scripts consistently after listing or changing them."""
    result = [
        {
            "id": _value(addin, "id"),
            "name": _value(addin, "name"),
            "author": _value(addin, "author"),
            "description": _value(addin, "description"),
            "folder": _value(addin, "folder"),
            "programmingLanguage": _programming_language(
                _value(addin, "programmingLanguage")
            ),
            "enabled": bool(_value(addin, "isRunOnStartup", False)),
            "running": bool(_value(addin, "isRunning", False)),
        }
        for addin in scripts.values()
    ]
    result.sort(key=lambda addin: (str(addin["name"]).lower(), str(addin["id"])))
    return result


@api_route("/scripts", methods=("GET", "POST"))
def scripts_route(
    context: Any,
    enable: Annotated[
        list[str] | None,
        ApiParameter("Add-in Script IDs to enable and start."),
    ] = None,
    disable: Annotated[
        list[str] | None,
        ApiParameter("Add-in Script IDs to stop and disable at startup."),
    ] = None,
) -> dict[str, list[dict[str, Any]]]:
    """List Fusion scripts and add-ins, or change add-ins in batches."""
    enable_ids = enable or []
    disable_ids = disable or []
    conflicting_ids = sorted(set(enable_ids) & set(disable_ids))
    if conflicting_ids:
        raise ValueError(
            "An add-in cannot be both enabled and disabled: "
            + ", ".join(repr(identifier) for identifier in conflicting_ids)
        )

    scripts = _scripts(context.app)
    addins = {
        identifier: script
        for identifier, script in scripts.items()
        if _value(script, "isAddIn", False)
    }
    requested_ids = [*enable_ids, *disable_ids]
    unknown_ids = sorted({identifier for identifier in requested_ids if identifier not in addins})
    if unknown_ids:
        raise ValueError(
            "Unknown add-in Script ID: "
            + ", ".join(repr(identifier) for identifier in unknown_ids)
        )

    for identifier in enable_ids:
        addin = addins[identifier]
        addin.isRunOnStartup = True
        if not _value(addin, "isRunning", False) and not addin.run(False):
            raise RuntimeError(f"Failed to start add-in {identifier!r}.")
    for identifier in disable_ids:
        addin = addins[identifier]
        addin.isRunOnStartup = False
        if _value(addin, "isRunning", False) and not addin.stop():
            raise RuntimeError(f"Failed to stop add-in {identifier!r}.")
    return {
        "scripts": _script_details({
            identifier: script
            for identifier, script in scripts.items()
            if not _value(script, "isAddIn", False)
        }),
        "addons": _script_details(addins),
    }
