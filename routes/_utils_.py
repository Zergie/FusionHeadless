import os, re, hashlib
from http.server import BaseHTTPRequestHandler


########  ########  ######  ########   #######  ##    ##  ######  ########  ######  
##     ## ##       ##    ## ##     ## ##     ## ###   ## ##    ## ##       ##    ## 
##     ## ##       ##       ##     ## ##     ## ####  ## ##       ##       ##       
########  ######    ######  ########  ##     ## ## ## ##  ######  ######    ######  
##   ##   ##             ## ##        ##     ## ##  ####       ## ##             ## 
##    ##  ##       ##    ## ##        ##     ## ##   ### ##    ## ##       ##    ## 
##     ## ########  ######  ##         #######  ##    ##  ######  ########  ######  
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

class PngResponse(HttpResponse):
    def __init__(self, data: bytes):
        super().__init__(200)
        self.headers["Content-Type"] = "image/png"
        self.content = data
    
    def send_content(self, requestHandler: BaseHTTPRequestHandler):
        requestHandler.wfile.write(self.content)


##     ## ######## ##       ########  ######## ########       ######## ##     ## ##    ##  ######  ######## ####  #######  ##    ##  ######  
##     ## ##       ##       ##     ## ##       ##     ##      ##       ##     ## ###   ## ##    ##    ##     ##  ##     ## ###   ## ##    ## 
##     ## ##       ##       ##     ## ##       ##     ##      ##       ##     ## ####  ## ##          ##     ##  ##     ## ####  ## ##       
######### ######   ##       ########  ######   ########       ######   ##     ## ## ## ## ##          ##     ##  ##     ## ## ## ##  ######  
##     ## ##       ##       ##        ##       ##   ##        ##       ##     ## ##  #### ##          ##     ##  ##     ## ##  ####       ## 
##     ## ##       ##       ##        ##       ##    ##       ##       ##     ## ##   ### ##    ##    ##     ##  ##     ## ##   ### ##    ## 
##     ## ######## ######## ##        ######## ##     ##      ##        #######  ##    ##  ######     ##    ####  #######  ##    ##  ######  

def log(message:str, mode:str = 'a') -> None:
    path = os.path.join(os.path.dirname(__file__), "debug.log")
    with open(path, mode) as log_file:
        log_file.write(f"{message}\n")

def get_assembly_contexts(occurrence) -> list[any]:
    assembly_contexts = []
    if occurrence.assemblyContext:
        assembly_contexts.append(occurrence.assemblyContext)
        occ = occurrence.assemblyContext
        while occ.assemblyContext:
            assembly_contexts.append(occ.assemblyContext)
            occ = occ.assemblyContext
        assembly_contexts.reverse()
    return assembly_contexts

def get_allBodies(design):
    if not hasattr(design, "rootComponent"):
        raise Exception("Design does not have a rootComponent.")

    for body in design.rootComponent.bRepBodies:
            yield body
    
    for occ in design.rootComponent.allOccurrences:
        for body in occ.component.bRepBodies:
            yield body

class Visibility:
    HIDE = 0
    SHOW = 1
    ISOLATE = 2

def setVisibility(design, filter:str, value:int) -> None:
    if filter == "all":
        for _ in range(2):
            for body in get_allBodies(design):
                body.isLightBulbOn = True if value == Visibility.SHOW else False
            for occ in design.rootComponent.allOccurrences:
                occ.isLightBulbOn = True if value == Visibility.SHOW else False
    else:
        for _ in range(2):
            for occ in design.rootComponent.allOccurrences:
                match = re.match(r"^(?:(.+)( v\d+)|(.+))(:\d)$", occ.name)
                if match:
                    name = match.group(1) or match.group(3)
                    version = match.group(2) or None
                    occurrence = match.group(4)

                    if name == filter:
                        if value == Visibility.ISOLATE:
                            occ.isIsolated = True

                            stack = [occ]
                            while stack:
                                item = stack.pop()
                                if hasattr(item, 'childOccurrences'):
                                    for x in item.childOccurrences:
                                        stack.append(x)
                                if not item.isVisible:
                                    item.isLightBulbOn = True

                        elif value == Visibility.SHOW:
                            occ.isLightBulbOn = True
                        elif value == Visibility.HIDE:
                            occ.isLightBulbOn = False
                    else:
                        for body in occ.bRepBodies:
                            if body.name == filter:
                                if value == Visibility.ISOLATE:
                                    occ.isIsolated = True
                                    body.isLightBulbOn = True
                                elif value == Visibility.SHOW:
                                    body.isLightBulbOn = True
                                elif value == Visibility.HIDE:
                                    body.isLightBulbOn = False

def body2dict(body, **kwargs) -> dict:
    def str2hash(string: str) -> str:
        hash = hashlib.md5(string.encode()).hexdigest()
        return f"{hash[:8]}-{hash[8:12]}-{hash[12:16]}-{hash[16:20]}-{hash[20:]}"

    def dict2hash(dict) -> str:
        return str2hash(str(dict))
    
    def body2color(body) -> str:
        colors = [x for x in body.appearance.appearanceProperties if x.name == "Color"]
        if not colors or len(colors) == 0:
            return "00000000"
        if colors[0].value is None:
            return "00000000"
        return "%0.2X%0.2X%0.2XFF" % (colors[0].value.red, colors[0].value.green, colors[0].value.blue)
    
    def round2(value, precision):
        v = round(value, precision)
        if v > -1/10**precision and v < 1/10**precision:
            return 0.0
        else:
            return v
        

    result = {
        'id'          : str2hash("-".join((body.name, body.parentComponent.id))),
        'hash'        : None,
        'name'        : body.name,
        'volume'      : round2(body.physicalProperties.volume, 5), # needed to identify changes
        'mass'        : round2(body.physicalProperties.mass  , 5),   # needed to identify changes
        'area'        : round2(body.physicalProperties.area  , 5),   # needed to identify changes
        'color'       : body2color(body),               # needed to identify changes
        'centerOfMass': [round2(v, 3) for v in body.physicalProperties.centerOfMass.asArray()],
        'material'    : body.material.name if body.material else None,
        'orientation' : list({tuple(round2(-x, 5) if face.isParamReversed else round2(x, 5) for x in face.geometry.normal.asArray()) for face in body.faces if "Build Plate" in face.appearance.name}),
        'boundingBox' : {
            'min': [round2(v, 3) for v in body.boundingBox.minPoint.asArray()],
            'max': [round2(v, 3) for v in body.boundingBox.maxPoint.asArray()],
        },
    }
    result['hash'] = dict2hash(result)
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
