"""
This endpoint handles requests to open an existing design or activate it within the Fusion 360 environment.
"""

def handle(request:dict, app) -> any:
    file = app.data.findFileById(request["file_id"])
    app.documents.open(file) # todo: (fixme) this crashes fusion 360 ... 

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { 'request' : { 'file_id' : 'urn:adsk.wipprod:dm.lineage:XCtddeaGT6ec7QPuHEVXNQ' }, 'app' : None})