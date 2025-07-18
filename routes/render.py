"""
Render a PNG image of the current Fusion 360 viewport or a specified named view.

This function processes rendering requests by generating a PNG image of the active viewport in Fusion 360.
It supports various visual styles, rendering qualities, camera settings (including focal length), and visibility
controls (show, hide, isolate). The rendered image is saved to a temporary file and returned as a binary response.
Options include image resolution, background transparency, anti-aliasing, exposure, and view selection (home or named view).
After rendering, the viewport's visual style, camera, and visibility settings are restored to their original state.

Args:
    query (dict): Rendering options such as 'quality', 'visualStyle', 'width', 'height',
                  'isBackgroundTransparent', 'isAntiAliased', 'view', 'focalLength', 'exposure',
                  and visibility controls ('show', 'hide', 'isolate').
    app: The Fusion 360 application object.
    ui: The Fusion 360 user interface object.
    adsk: The Fusion 360 API module.

Returns:
    PngResponse: The rendered image as a PNG response.

Raises:
    ValueError: If the quality value is out of the allowed range.
    Exception: If rendering does not complete within the specified timeout.
"""

import asyncio
import math
import os
import re
import tempfile
import uuid
from _utils_ import PngResponse, setControlDefinition, get_allBodies, setVisibility, Visibility

    
def handle(query:dict, app, ui, adsk) -> any:
    path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.png")
    if os.path.exists(path):
        os.remove(path)

    async def render_finished(path):
        while not os.path.exists(path):
            adsk.doEvents()
            await asyncio.sleep(1)

    quality, visualStyle = {
        'Shaded'                        : (None, 0),
        'ShadedWithHiddenEdges'         : (None, 1),
        'ShadedWithVisibleEdgesOnly'    : (None, 2),
        'Wireframe'                     : (None, 3),
        'WireframeWithHiddenEdges'      : (None, 4),
        'WireframeWithVisibleEdgesOnly' : (None, 5),
    }.get(query.get('quality', 'ShadedWithVisibleEdgesOnly'), (query.get('quality', 2), None))
    quality = int(quality) if quality is not None else None
    visualStyle = int(visualStyle) if visualStyle is not None else None
    design = app.activeProduct
    viewport = app.activeViewport
    old = {
        'visualStyle': viewport.visualStyle,
    }

    # validate settings
    if quality is not None and not (25 <= quality <= 100):
        raise ValueError("Quality must be between 25 and 100, or a valid visual style must be specified.")
    
    if 'focalLength' in query:
        old['camera'] = setControlDefinition('ViewCameraCommand', 1, adsk, ui)
        camera = viewport.camera
        camera.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
        camera.isSmoothTransition = False
        camera.perspectiveAngle = 2.0 * math.atan((24.0 / 2.0) / float(query.get('focalLength', 50.0)))
        viewport.camera = camera
        viewport.refresh()
    else:
        old['camera'] = setControlDefinition('ViewCameraCommand', query.get('camera', None), adsk, ui)

    lookup = {
        'show': Visibility.SHOW,
        'hide': Visibility.HIDE,
        'isolate': Visibility.ISOLATE
    }
    for key in query.keys():
        if key in lookup:
            value = lookup[key]
            if isinstance(query[key], str):
                setVisibility(design, query[key], value)
            elif isinstance(query[key], list):
                for item in query[key]:
                    setVisibility(design, item, value)
    
    if 'view' in query:
        if query['view'].lower() == 'home':
            viewport.goHome()
            viewport.fit()
        else:
            app.activeDocument.design.namedViews.itemByName(query['view']).apply()

    ui.activeSelections.clear()
    adsk.doEvents()

    if visualStyle is not None:    
        old['visibility'] = setControlDefinition('VisibilityOverrideCommand', False, adsk, ui)
        options = adsk.core.SaveImageFileOptions.create(path)
        options.width = int(query.get('width', 1280))
        options.height = int(query.get('height', 1024))
        options.isBackgroundTransparent = bool(query.get('isBackgroundTransparent', False))
        options.isAntiAliased = bool(query.get('isAntiAliased', True))
        viewport.saveAsImageFileWithOptions(options) 

    elif quality is not None:
        camera = viewport.camera
        eye = camera.eye
        target = camera.target
        upVector = camera.upVector
        perspectiveAngle = camera.perspectiveAngle

        direction = target.vectorTo(eye)
        direction.normalize()
        distance = eye.distanceTo(target)
        # fov = 2.0 * math.atan((24.0 / 2.0) / float(query.get('focalLength', 50.0)))
        # distance_multiplier = (1.0 / fov) / 2.1227368058100704
        # direction.scaleBy(distance * .45 * distance_multiplier)
        direction.scaleBy(distance * .455)
        
        eye = camera.target.copy()
        eye.translateBy(direction)

        camera.eye = eye
        camera.target = target
        camera.upVector = upVector
        camera.perspectiveAngle = perspectiveAngle
        camera.isSmoothTransition = False
        camera.cameraType = adsk.core.CameraTypes.PerspectiveCameraType

        rm = app.activeProduct.renderManager
        scene = rm.sceneSettings
        scene.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
        if 'exposure' in query:
            scene.cameraExposure = float(query['exposure'])

        render = rm.rendering
        render.aspectRatio = adsk.fusion.RenderAspectRatios.CustomRenderAspectRatio
        render.resolution = adsk.fusion.RenderResolutions.CustomRenderResolution
        render.resolutionWidth = int(query.get('width', 1280))
        render.resolutionHeight = int(query.get('height', 1024))
        render.isBackgroundTransparent = bool(query.get('isBackgroundTransparent', False))
        render.renderQuality = quality

        frame = render.startLocalRender(path, camera)
    
    try:
        asyncio.run(asyncio.wait_for(render_finished(path), timeout=180))
    except asyncio.TimeoutError:
        raise Exception(f"Failed to render within 180 seconds.")
    
    viewport.visualStyle = old['visualStyle']
    setControlDefinition('VisibilityOverrideCommand', old.get('visibility'), adsk, ui)
    setControlDefinition('ViewCameraCommand', old.get('camera'), adsk, ui)

    with open(path, 'rb') as file:
        content = file.read()
    os.remove(path)
    return PngResponse(content)

if __name__ == "__main__":
    import _client_
    # _client_.test(__file__, {"view": "MotionStudy_Latch", "isolate": "Direct Drive x4", "hide": "Filament Spools", "focalLength": 200, "quality": "ShadedWithVisibleEdgesOnly", "width": 400, "height": 400}, output=f"C:\\GIT\\YAMMU\\obj\\new.png", timeout=180)
    _client_.test(__file__, {'view': 'MotionStudy_Latch', 'isolate': 'Direct Drive x4', 'hide': "['Filament Spools', 'latch_a', 'latch_b', 'latch_mirror_a', 'latch_mirror_b']", 'focalLength': '200', 'quality': 'ShadedWithVisibleEdgesOnly', 'width': '400', 'height': '400'}, output=f"C:\\GIT\\YAMMU\\obj\\new.png", timeout=180)