"""
This route acts as a filter, returning all files with a specific name from the application's data.
"""

def walk_folder(folder):
    for file in folder.dataFiles:
        yield { 
            "id": str(file.id), 
            "name": str(file.name), 
            "dateModified": str(file.dateModified), 
            "versionNumber": str(file.versionNumber), 
            "latestVersionNumber": str(file.latestVersionNumber),
            "parentFolder" : {
                "id": str(folder.id), 
                "name": str(folder.name),
            },
        }
    for subfolder in folder.dataFolders:
        yield from walk_folder(subfolder)

def walk(dataProjects):
    for project in dataProjects:
        yield from walk_folder(project.rootFolder)

def handle(query, app) -> any:
    if 'name' in query:
        return [item for item in walk(app.data.dataProjects) if item['name'] == query['name']]
    else:
        return [item for item in walk(app.data.dataProjects)]

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { 'query': {'name':'Assembly'}, 'app' : None})