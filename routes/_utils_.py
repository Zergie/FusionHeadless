import hashlib
from http.server import BaseHTTPRequestHandler

class HttpResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.headers = { "Content-Type": "text/plain" }
        self.content = ""
    
    def send_header(self, requestHandler: BaseHTTPRequestHandler):
        requestHandler.send_response(self.status_code)
        for k, v in self.headers.items():
            requestHandler.send_header(k, v)
        requestHandler.end_headers()

    def send_content(self, requestHandler: BaseHTTPRequestHandler):
        requestHandler.wfile.write(self.content.encode())

    def send(self, requestHandler: BaseHTTPRequestHandler):
        self.send_header(requestHandler)
        self.send_content(requestHandler)

class BinaryResponse(HttpResponse):
    def __init__(self, data: bytes):
        super().__init__(200)
        self.headers["Content-Type"] = "application/octet-stream"
        self.content = data
    
    def send_content(self, requestHandler: BaseHTTPRequestHandler):
        requestHandler.wfile.write(self.content)

def getAllBodies(design):
    if not hasattr(design, "rootComponent"):
        raise Exception("Design does not have a rootComponent.")

    for body in design.rootComponent.bRepBodies:
            yield body
    
    for occ in design.rootComponent.allOccurrences:
        for body in occ.component.bRepBodies:
            yield body

def body2dict(body, **kwargs) -> dict:
    def dict2hash(dict) -> str:
        hash = hashlib.md5(str(dict).encode()).hexdigest()
        return f"{hash[:8]}-{hash[8:12]}-{hash[12:16]}-{hash[16:20]}-{hash[20:]}"  
    
    def body2color(body) -> str:
        colors = [x for x in body.appearance.appearanceProperties if x.name == "Color"]
        if not colors or len(colors) == 0:
            return "00000000"
        if colors[0].value is None:
            return "00000000"
        return "%0.2X%0.2X%0.2XFF" % (colors[0].value.red, colors[0].value.green, colors[0].value.blue)
    
    props = {
        'name'        : body.name,
        'volume'      : body.physicalProperties.volume,
        'mass'        : body.physicalProperties.mass,
        'area'        : body.physicalProperties.area,
        'centerOfMass': [round(v, 2) for v in body.physicalProperties.centerOfMass.asArray()],
        'color'       : body2color(body),
        'material'    : body.material.name if body.material else None,
        'boundingBox' : {
            'min': [round(v, 2) for v in body.boundingBox.minPoint.asArray()],
            'max': [round(v, 2) for v in body.boundingBox.maxPoint.asArray()],
        },
    }
    result = { 'id' : dict2hash(props) }
    result.update(props)
    result.update(kwargs)
    return result

def component2dict(comp, **kwargs) -> dict:
    result = {
        'id'  : comp.id,
        'name': comp.name
    }
    result.update(kwargs)
    return result

def setControlDefinition(item:str, value:bool|int|list|None, adsk, ui) -> list|None:
    if value is None:
        return None

    cmd = ui.commandDefinitions.itemById(item)
    listCntrl: adsk.core.ListControlDefinition = cmd.controlDefinition
    

    if isinstance(value, list):
        old = [bool(listCntrl.listItems.item(i).isSelected) for i in range(listCntrl.listItems.count)]
        for i in range(listCntrl.listItems.count):
            listCntrl.listItems.item(i).isSelected = value[i]
    if isinstance(value, bool):
        old = [bool(listCntrl.listItems.item(i).isSelected) for i in range(listCntrl.listItems.count)]
        for i in range(listCntrl.listItems.count):
            listCntrl.listItems.item(i).isSelected = value
    elif isinstance(value, int):
        old = [i for i in range(listCntrl.listItems.count) if listCntrl.listItems.item(i).isSelected]
        old = old[0] if len(old) == 1 else None
        listCntrl.listItems.item(value).isSelected = True
        
    return old
