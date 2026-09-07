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
    ISOLATE = 2


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
        try:
            asyncio.run(asyncio.wait_for(wait_for_file(), timeout=180))
        except asyncio.TimeoutError as error:
            raise RuntimeError("Failed to render within 180 seconds.") from error
        with open(path, "rb") as file:
            return file.read()
