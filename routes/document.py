"""
This endpoint handles requests to open an existing design or activate it within the Fusion 360 environment.
"""

import asyncio

def open(id, app, adsk) -> any:
    id = id.strip()
    if app.activeDocument and app.activeDocument.dataFile and app.activeDocument.dataFile.id == id:
        return f"File is already active."
    
    file = app.data.findFileById(id)
    if not file:
        raise Exception(f"File with ID '{id}' not found.")
    app.documents.open(file)

    async def document_opened(id):
        while 1:
            adsk.doEvents()
            if app.activeDocument and app.activeDocument.dataFile and app.activeDocument.dataFile.id == id:
                return
            await asyncio.sleep(.5)

    try:
        asyncio.run(asyncio.wait_for(document_opened(id), timeout=30))
        return f"File opened successfully."
    except asyncio.TimeoutError:
        raise Exception(f"Failed to open file with ID '{id}' within 30 seconds.")

def close(saveChanges, app, adsk) -> any:
    if app.activeDocument and app.activeDocument.dataFile:
        app.activeDocument.close(bool(saveChanges))
        return f"File closed successfully."
    else:
        return f"No active document to close."

def handle(query:dict, app, adsk) -> any:
    if 'open' in query:
        return open(query['open'], app, adsk)
    elif 'close' in query:
        return close(query['close'], app, adsk)

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, {'open': 'urn:adsk.wipprod:dm.lineage:KdrfgN7NQyWufnPf5J3L0Q  '})
    # _client_.test(__file__, { 'query' : {'close': 'False'}})