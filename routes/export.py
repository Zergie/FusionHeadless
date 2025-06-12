"""
Handles exporting components or bodies from the active Fusion 360 design to a specified file format.
This function determines the export target (component, body, or root component) based on the request,
constructs an appropriate file path in the system's temporary directory, and uses the Fusion 360
exportManager to export the selected item in the requested format (STEP or STL).
"""

import os, tempfile

def handle(path:str, request:dict, app) -> any:
    design = app.activeProduct
    if not hasattr(design, "exportManager"):
        raise Exception("Active product does not support exportManager")
    exportMgr = design.exportManager
    temp_dir = tempfile.gettempdir()

    extension = path.split("/")[2]
    if "filename" in request:
        path = os.path.join(temp_dir, request["filename"])
    elif "component" in request:
        path = os.path.join(temp_dir, f"{request['component']}.{extension}")
    elif "body" in request:
        path = os.path.join(temp_dir, f"{request['body']}.{extension}")
    else:
        path = os.path.join(temp_dir, f"exported.{extension}")

    if "component" in request:
        items = [x for x in design.rootComponent.allOccurrences if x.component.name == request["component"]]
        if len(items) == 0:
            raise Exception(f"Component '{request['component']}' not found in {repr([x.component.name for x in design.rootComponent.allOccurrences])}")
        design = items[0].component
    elif "body" in request:
        found = None
        for occ in design.rootComponent.allOccurrences:
            found = occ.component.bRepBodies.itemByName(request["body"])
            if found:
                break
        if not found:
            raise Exception(f"Body '{request['body']}' not found in {repr([x.name for x in design.rootComponent.bRepBodies])}")
        design = found
    else:
        design = design.rootComponent

    if extension == "step":
        exportOptions = exportMgr.createSTEPExportOptions(path, design)
    elif extension == "stl":
        exportOptions = exportMgr.createSTLExportOptions(design, path)
    else:
        raise Exception(f"Unsupported export format: {extension}")

    exportMgr.execute(exportOptions)
    return exportOptions.filename


if __name__ == "__main__":
    from _client_ import *
    test(__file__, { "path" : "/export/stl", "request": { "body": "ptfe_din_rail_clamp_x2" }, "app": ContextVariable("app") })