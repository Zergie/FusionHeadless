"""
This route acts as a filter, returning all files with a specific name from the application's data.
"""

def file2dict(file):
    return { 
            "id": str(file.id), 
            "name": str(file.name), 
            "dateModified": str(file.dateModified), 
            "versionNumber": str(file.versionNumber), 
            "latestVersionNumber": str(file.latestVersionNumber),
            "parentFolder" : {
                "id": file.parentFolder.id,
                "name": file.parentFolder.name,
            },
            "parentProject": {
                "id": file.parentProject.id,
                "name": file.parentProject.name,
            }
        }

def walk_folder(folder):
    for file in folder.dataFiles:
        yield file2dict(file)
    for subfolder in folder.dataFolders:
        yield from walk_folder(subfolder)

def walk_project(dataProjects):
    for project in dataProjects:
        yield from walk_folder(project.rootFolder)

def handle(query, app) -> any:
    if 'active' in query:
        return [file2dict(app.activeDocument.dataFile)]
    elif 'id' in query:
        return file2dict(app.data.findFileById(query['id']))
    else:
        result = [item for item in walk_project(app.data.dataProjects)]
    
    if 'name' in query:
        return [item for item in result if item['name'].lower() == query['name'].lower()]
    else:
        return result

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { 
        'active': 1
        })