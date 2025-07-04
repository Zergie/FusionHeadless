"""
Handles exporting components or bodies from the active Fusion 360 design to a specified file format.
This function determines the export target (component, body, or root component) based on the request,
constructs an appropriate file path in the system's temporary directory, and uses the Fusion 360
exportManager to export the selected item in the requested format (STEP or STL).
"""

import os, tempfile, uuid
from _utils_ import BinaryResponse, body2dict

def handle(query:dict, app) -> any:
    design = app.activeProduct
    if not hasattr(design, "exportManager"):
        raise Exception("Active product does not support exportManager")
    exportMgr = design.exportManager
    temp_dir = tempfile.gettempdir()

    format = query.get("format", "step")
    path = os.path.join(temp_dir, f"{uuid.uuid4().hex}.{format}")

    if "component" in query:
        items = [x for x in design.rootComponent.allOccurrences if x.component.name == query["component"] or x.component.id == query["component"]]
        if len(items) == 0:
            raise Exception(f"Component '{query['component']}' not found.")
        design = items[0].component
    elif "body" in query:
        design = None
        for occ in design.rootComponent.allOccurrences:
            design = occ.component.bRepBodies.itemByName(query["body"])
            if design:
                break
        if not design:
            for body in design.rootComponent.bRepBodies:
                dict = body2dict(body)
                if dict.name == query["body"] or dict.id == query["body"]:
                    design = body
                    break
        if not design:
            for occ in design.rootComponent.allOccurrences:
                for body in occ.component.bRepBodies:
                    dict = body2dict(body)
                    if dict.name == query["body"] or dict.id == query["body"]:
                        design = body
                        break
        if not design:
            raise Exception(f"Body '{query['body']}' not found.")
    else:
        design = design.rootComponent

    if format == "step":
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
    test(__file__, { "query" : { "format": "obj" } , "app": None }, output=f"C:\\GIT\\YAMMU\\obj\\{uuid.uuid4().hex}.obj", timeout=60)