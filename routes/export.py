"""
Handles exporting components or bodies from the active Fusion 360 design to a specified file format.
This function determines the export target (component, body, or root component) based on the request,
constructs an appropriate file path in the system's temporary directory, and uses the Fusion 360
exportManager to export the selected item in the requested format (STEP or STL).
"""

import os, tempfile, uuid
from _utils_ import BinaryResponse, setVisibility, Visibility

def handle(query:dict, app, adsk) -> any:
    if not hasattr(app.activeProduct, "exportManager"):
        raise Exception("Active product does not support exportManager")
    exportMgr = app.activeProduct.exportManager
    temp_dir = tempfile.gettempdir()

    format = query.get("format", "step")
    path = os.path.join(temp_dir, f"{uuid.uuid4().hex}.{format}")

    setVisibility(app.activeProduct, 'all', Visibility.SHOW)

    design = None
    if "component" in query:
        items = [x for x in app.activeProduct.rootComponent.allOccurrences if x.component.name == query["component"] or x.component.id == query["component"]]
        if len(items) == 0:
            raise Exception(f"Component '{query['component']}' not found.")
        else:
            design = items[0]
    else:
        design = app.activeProduct.rootComponent
    
    if 'body' in query:
        bodies = query["body"] if isinstance(query["body"], list) else [query["body"]]

        if len(bodies) == 1:
            design = design.bRepBodies.itemByName(bodies[0])
            if not design:
                raise Exception(f"Body '{bodies[0]}' not found in component '{design.name}'.")
        else:
            bodies_found = []

            for body in design.bRepBodies:
                if body.name in bodies:
                    bodies_found.append(body.name)
                else:
                    body.isLightBulbOn = False

            bodies_not_found = list(set(bodies) - set(bodies_found))
            if len(bodies_not_found) > 0:
                raise Exception(f"Body(s) '{', '.join(bodies_not_found)}' not found in component '{design.name}'.")

    if format == "f3d":
        exportOptions = exportMgr.createFusionArchiveExportOptions(path, design)
    elif format == "step":
        exportOptions = exportMgr.createSTEPExportOptions(path, design)
    elif format == "stl":
        exportOptions = exportMgr.createSTLExportOptions(design, path)
    elif format == "3mf":
        exportOptions = exportMgr.createC3MFExportOptions (design, path)
    elif format == "obj":
        exportOptions = exportMgr.createOBJExportOptions(design, path)
    else:
        raise Exception(f"Unsupported export format: {format}")

    exportMgr.execute(exportOptions)
    with open(exportOptions.filename, 'rb') as file:
        content = file.read()
    os.remove(exportOptions.filename)
    return BinaryResponse(content)

if __name__ == "__main__":
    from _client_ import *
    test(__file__, { "format": "f3d"}, output=f"C:\\GIT\\GT2_Pulley\\GT2_Pulley.f3d", timeout=60)