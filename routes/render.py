"""Render helpers and operations for FusionHeadless."""

from __future__ import annotations

import asyncio
import math
import os
import re
from typing import Annotated, Any
from routing import ApiParameter, api_route, BinaryResponse
from fusion_support import _value
from routes._bodies import _all_bodies_and_occurrences
from routes._temporary import TemporaryEffects


class Visibility:
    HIDE = 0
    SHOW = 1


class _RenderVisibility:
    """Group temporary display changes and restore them through Fusion history."""

    def __init__(self, app: Any, adsk: Any) -> None:
        self._app = app
        self._adsk = adsk
        self._history: list[tuple[Any, str, Any]] = []
        self._initial: dict[tuple[int, str], tuple[Any, str, Any]] = {}
        self._transaction = False
        self._committed = False

    def __enter__(self) -> _RenderVisibility:
        return self

    def _start_transaction(self) -> None:
        if self._transaction:
            return
        execute = _value(self._app, "executeTextCommand")
        if callable(execute):
            result = execute("Transaction.Start FusionHeadlessRender")
            if str(result) != "1":
                raise RuntimeError(
                    f"Fusion could not start the render visibility transaction: {result!r}"
                )
            self._transaction = True

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            self.restore()
        except Exception as cleanup_error:
            message = f"Render visibility rollback failed: {cleanup_error}"
            if exc is not None:
                message = f"Render failed: {exc}; {message}"
            raise RuntimeError(message) from (exc if exc is not None else cleanup_error)
        return False

    def set_attributes(self, changes: Any) -> None:
        for item, attribute, value in changes:
            current = getattr(item, attribute)
            if current == value:
                continue
            key = (id(item), attribute)
            self._initial.setdefault(key, (item, attribute, current))
            if attribute != "isIsolated":
                self._start_transaction()
            setattr(item, attribute, value)
            self._history.append((item, attribute, current))

    def commit_for_capture(self) -> None:
        """Commit once so Fusion redraws the scene; restore it with one Undo."""
        if not self._transaction:
            return
        result = self._app.executeTextCommand("Transaction.Commit")
        if str(result) != "1":
            raise RuntimeError(
                f"Fusion could not commit the render visibility transaction: {result!r}"
            )
        self._transaction = False
        self._committed = True
        self._adsk.doEvents()

    def restore(self) -> None:
        if self._transaction:
            result = self._app.executeTextCommand("Transaction.Abort")
            self._transaction = False
            if str(result) != "1":
                raise RuntimeError(
                    f"Fusion could not abort the render visibility transaction: {result!r}"
                )
            self._adsk.doEvents()
        elif self._committed:
            self._app.executeTextCommand("Commands.Start UndoCommand")
            self._committed = False
            self._adsk.doEvents()
        if callable(_value(self._app, "executeTextCommand")):
            # Occurrence isolation is UI state outside Fusion's document
            # transaction/history, so restore it explicitly afterward.
            for item, attribute, value in reversed(self._history):
                if attribute == "isIsolated":
                    setattr(item, attribute, value)
        elif not self._history:
            return
        else:
            # Lightweight test hosts do not emulate Fusion transactions.
            for item, attribute, value in reversed(self._history):
                setattr(item, attribute, value)
        mismatches = [
            f"{type(item).__name__} '{_value(item, 'name', '')}'.{attribute}"
            for item, attribute, value in self._initial.values()
            if getattr(item, attribute) != value
        ]
        self._history.clear()
        if mismatches:
            raise RuntimeError("Fusion did not restore " + ", ".join(mismatches))


def _occurrence_name_matches(occurrence: Any, name: str) -> bool:
    occurrence_name = str(_value(occurrence, "name", ""))
    match = re.match(r"^(?:(.+)( v\d+)|(.+))(:\d+)$", occurrence_name)
    normalized_name = (match.group(1) or match.group(3)) if match else occurrence_name
    return name in (occurrence_name, normalized_name)


def _occurrence_bodies(occurrence: Any) -> list[Any]:
    bodies = _value(occurrence, "bRepBodies")
    if bodies is None:
        bodies = _value(_value(occurrence, "component"), "bRepBodies", [])
    return list(bodies or [])


def _set_visibility(
    design: Any, name: str, mode: int, changes: _RenderVisibility,
) -> None:
    if name == "all":
        for _ in range(2):
            for body in _all_bodies_and_occurrences(design):
                changes.set_attributes(((body, "isLightBulbOn", mode == Visibility.SHOW),))
            for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
                changes.set_attributes(((
                    occurrence, "isLightBulbOn", mode == Visibility.SHOW,
                ),))
        return
    for _ in range(2):
        for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
            if _occurrence_name_matches(occurrence, name):
                changes.set_attributes(((
                    occurrence, "isLightBulbOn", mode != Visibility.HIDE,
                ),))
            else:
                for body in _occurrence_bodies(occurrence):
                    if _value(body, "name") == name:
                        changes.set_attributes(((
                            body, "isLightBulbOn", mode != Visibility.HIDE,
                        ),))


def _set_isolation(
    design: Any, names: list[str], changes: _RenderVisibility,
) -> None:
    """Display every requested item together without Fusion's single-item isolation."""
    root = _value(design, "rootComponent")
    occurrences = list(_value(root, "allOccurrences", []) or [])
    stack = list(occurrences)
    known = {id(item) for item in occurrences}
    while stack:
        for child in _value(stack.pop(), "childOccurrences", []) or []:
            if id(child) not in known:
                known.add(id(child))
                occurrences.append(child)
                stack.append(child)
    parents: dict[int, Any] = {}
    for occurrence in occurrences:
        for child in _value(occurrence, "childOccurrences", []) or []:
            parents[id(child)] = occurrence

    selected_occurrences: list[Any] = []
    selected_bodies: set[int] = set()
    occurrence_selector_matched = False
    root_bodies = list(_value(root, "bRepBodies", []) or [])
    for name in names:
        if name == "all":
            selected_occurrences.extend(occurrences)
            selected_bodies.update(id(body) for body in root_bodies)
            occurrence_selector_matched = True
            continue
        for body in root_bodies:
            if _value(body, "name") == name:
                selected_bodies.add(id(body))
        for occurrence in occurrences:
            if _occurrence_name_matches(occurrence, name):
                selected_occurrences.append(occurrence)
                occurrence_selector_matched = True
            for body in _occurrence_bodies(occurrence):
                if _value(body, "name") == name:
                    selected_occurrences.append(occurrence)
                    selected_bodies.add(id(body))

    # Fusion documents isIsolated as exclusive. Clear an existing isolation and
    # emulate group isolation with temporary light-bulb states instead.
    for occurrence in occurrences:
        if _value(occurrence, "isIsolated", False):
            changes.set_attributes(((occurrence, "isIsolated", False),))

    keep: set[int] = set()
    stack = list(selected_occurrences)
    while stack:
        occurrence = stack.pop()
        if id(occurrence) in keep:
            continue
        keep.add(id(occurrence))
        stack.extend(_value(occurrence, "childOccurrences", []) or [])
    for occurrence in list(selected_occurrences):
        parent = parents.get(id(occurrence))
        while parent is not None:
            keep.add(id(parent))
            parent = parents.get(id(parent))

    # The same Fusion occurrence can be exposed through allOccurrences and
    # childOccurrences as different Python proxy objects. Use its assembly path
    # to relate those proxies; retain object identity for lightweight hosts.
    selected_paths = {
        str(path)
        for occurrence in selected_occurrences
        if (path := _value(occurrence, "fullPathName", ""))
    }

    def occurrence_is_kept(occurrence: Any) -> bool:
        if id(occurrence) in keep:
            return True
        path = str(_value(occurrence, "fullPathName", ""))
        return bool(path) and any(
            path == selected
            or path.startswith(selected + "+")
            or selected.startswith(path + "+")
            for selected in selected_paths
        )

    changes.set_attributes(
        (occurrence, "isLightBulbOn", occurrence_is_kept(occurrence))
        for occurrence in occurrences
    )
    if occurrence_selector_matched:
        changes.set_attributes(
            (body, "isLightBulbOn", id(body) in selected_bodies)
            for body in root_bodies
        )
    else:
        changes.set_attributes(
            (body, "isLightBulbOn", id(body) in selected_bodies)
            for body in _all_bodies_and_occurrences(design)
        )


@api_route(
    "/render",
    methods=("POST",),
    binary=BinaryResponse("image/png", "render.png", disposition="inline"),
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
    with TemporaryEffects() as effects:
        path = effects.temporary_file(".png")

        async def wait_for_file() -> None:
            while not os.path.exists(path):
                adsk.doEvents(); await asyncio.sleep(1)

        async def wait_for_file_with_timeout() -> None:
            try:
                await asyncio.wait_for(wait_for_file(), timeout=180)
            except asyncio.TimeoutError as error:
                raise RuntimeError("Failed to render within 180 seconds.") from error

        effects.preserve(viewport, "visualStyle")
        if focalLength is not None:
            effects.set_control(
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
            effects.set_control(
                ui, "ViewCameraCommand", camera
            )
        # Explicit exclusions win over children revealed by isolation.
        with _RenderVisibility(app, adsk) as changes:
            for item in show or []:
                _set_visibility(product, str(item), Visibility.SHOW, changes)
            if isolate:
                _set_isolation(product, [str(item) for item in isolate], changes)
            for item in hide or []:
                _set_visibility(product, str(item), Visibility.HIDE, changes)
            selections = _value(ui, "activeSelections")
            if selections is not None:
                selections.clear()
            changes.commit_for_capture()
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
            adsk.doEvents()
            if visual_style is not None:
                effects.set_control(
                    ui, "VisibilityOverrideCommand", False
                )
                options = adsk.core.SaveImageFileOptions.create(path)
                options.width = width
                options.height = height
                options.isBackgroundTransparent = isBackgroundTransparent
                options.isAntiAliased = isAntiAliased
                viewport.visualStyle = visual_style
                viewport.saveAsImageFileWithOptions(options)
                # Fusion queues viewport capture. Keep temporary visibility until
                # the PNG exists, then undo the transaction before returning.
                asyncio.run(wait_for_file_with_timeout())
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
                # Let Fusion consume the configured scene before visibility is
                # rolled back; the potentially long render continues afterward.
                adsk.doEvents()
        if not os.path.exists(path):
            asyncio.run(wait_for_file_with_timeout())
        with open(path, "rb") as file:
            return file.read()
