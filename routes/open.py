"""
This endpoint handles requests to open an existing design or activate it within the Fusion 360 environment.
"""

def handle(request:dict, app) -> any:
    if not 'id' in request:
        raise Exception("Request must contain 'id' key")
    code = f"""
import adsk.core
app = adsk.core.Application.get()
ui = app.userInterface
file_id = "{request['id']}"
file = app.data.findFileById(file_id)
if not file:
    raise Exception(f"File with ID {{file_id}} not found.")
app.documents.open(file)
"""
    return app.fireCustomEvent('FusionHeadless.ExecOnUiThread', code)

if __name__ == "__main__":
    import _client_
    # _client_.test(__file__, { 'request' : { 'name' : 'Latch Lock' }, 'app' : None})
    _client_.test(__file__, { 'request' : { 'id' : 'urn:adsk.wipprod:dm.lineage:Hch4mZruQBuLmXgnxpJRIg' }, 'app' : None})