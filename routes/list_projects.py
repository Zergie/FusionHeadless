"""
This route returns all projects from app.data.dataProjects, each converted to a JSON-compatible format.
"""

def sort_idName_first(item):
    order = ["id", "name"]
    if item in order:
        return f"{order.index(item):02d}_{item}"
    else:
        return f"{len(order):02d}_{item}"

def object2json(obj, **kwargs):
    result = {attr: str(getattr(obj, attr)) for attr in sorted(dir(obj), key=sort_idName_first) if not attr.startswith('_') and isinstance(getattr(obj, attr), (str, int, float, bool))}
    result.update(kwargs)
    return result

def file2json(file):
    return {
        'id'                  : file.id,
        'name'                : file.name,
        'dateModified'        : file.dateModified,
        'versionNumber'       : file.versionNumber,
        'latestVersionNumber' : file.latestVersionNumber,
    }

def folder2json(folder):
    return object2json(folder, dataFolders=[folder2json(x) for x in folder.dataFolders], dataFiles=[file2json(x) for x in folder.dataFiles])

def project2json(project):
    return object2json(project, rootFolder=folder2json(project.rootFolder))

def handle(app) -> any:
    return [project2json(x) for x in app.data.dataProjects]

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { 'app' : None})