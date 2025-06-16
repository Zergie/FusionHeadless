"""
<< short description >>
"""

def file2json(file):
    return {
        'id'                  : file.id,
        'name'                : file.name,
        'dateModified'        : file.dateModified,
        'versionNumber'       : file.versionNumber,
        'latestVersionNumber' : file.latestVersionNumber,
    }

def folder2json(folder):
    return {
        'id'        : folder.id,
        'name'      : folder.name,
        'dataFiles' : [file2json(x) for x in folder.dataFiles],
    }

def project2json(project):
    return {    
        'id'         : project.id,
        'name'       : project.name,
        'rootFolder' : folder2json(project.rootFolder),
    }

def handle(app) -> any:
    return  [project2json(x) for x in app.data.dataProjects]

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { 'app' : None})