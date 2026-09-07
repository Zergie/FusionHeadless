"""Export helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Annotated, Any, Callable, Literal
from context import server
from routing import ApiParameter, api_route, BinaryResponse, RedirectURL
from routes._bodies import _all_bodies_and_occurrences
from routes._temporary import TemporaryEffects
from fusion_support import _value


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
    """Execute and read an export whose temporary file is owned by the caller."""
    try:
        succeeded = export_manager.execute(options)
    except Exception as error:
        raise RuntimeError(f"Fusion failed to export {description}: {error}") from error
    if not succeeded:
        raise RuntimeError(f"Fusion failed to export {description}")
    if postprocess is not None:
        postprocess(options.filename)
    with open(options.filename, "rb") as output:
        return output.read()


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
    with TemporaryEffects() as effects:
        path = effects.temporary_file(".stl")
        effects.set_attributes((item, "isLightBulbOn", state) for item, state in changes)
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
        "export.{format}",
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
    redirect_url: Annotated[
        str | None,
        RedirectURL(),
        ApiParameter("Optional absolute URL template containing exactly one {url}. Redirects to it with the encoded, single-use download URL; expires after five minutes. Omit or use null for raw bytes."),
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
    with TemporaryEffects() as effects:
        path = effects.temporary_file(f".{format_name}")
        effects.set_attributes((item, "isLightBulbOn", state) for item, state in changes)
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
