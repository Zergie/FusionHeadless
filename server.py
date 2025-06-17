from . import routes
from .route_registry import get_handler
from http.server import BaseHTTPRequestHandler, HTTPServer
import adsk.core
import json
import traceback
import os, sys
from urllib.parse import urlparse, parse_qs

def get_context(additional={}):
    context = {
        "adsk": adsk,
        "app": adsk.core.Application.get(),
        "ui": adsk.core.Application.get().userInterface,
        "os": os,
        "sys": sys,
    }
    context.update(additional)
    return context

def execute_code(code: str|dict, context: dict = None):
    if context is None:
        context = get_context()
    
    if isinstance(code, str):
        exec(code, context)
    else:
        exec(code.get("code", ""), context)
    return context.get("result", None)

def sort_attrs(item):
    order = ["id", "name", "description"]
    if item in order:
        return f"{order.index(item):02d}_{item}"
    else:
        return f"{len(order):02d}_{item}"

def object2json(obj, max_depth, depth=0):
    if type(obj).__name__ in ['method', 'function', 'NoneType']:
        result = None
    elif isinstance(obj, (int, float, str, bool)):
        result = obj
    elif obj is None:
        result = None
    elif isinstance(obj, (list, tuple)) and not hasattr(obj, '__iter__'):
        result = [object2json(x, max_depth, depth+1) for x in obj] if depth < max_depth else []
    elif isinstance(obj, dict):
        result = {k: object2json(v, max_depth, depth+1) for k, v in obj.items()} if depth < max_depth else {}
    elif hasattr(obj, 'asArray') and callable(obj.asArray):
        result = [object2json(v, max_depth, depth+1) for v in obj.asArray()] if depth < max_depth else []
    elif hasattr(obj, 'asDict') and callable(obj.asDict):
        result = {k: object2json(v, max_depth, depth+1) for k, v in obj.asDict().items()} if depth < max_depth else {}
    else:
        result = {k: object2json(attribute2json(obj, k), max_depth, depth+1) for k in sorted(dir(obj), key=sort_attrs) if not k.startswith('_')}  if depth < max_depth else {}

    if isinstance(result, (list, tuple)):
        result = {
            'items': [x for x in result if x is not None],
            'objectType': f"https://help.autodesk.com/view/fusion360/ENU/?cg=Developer%27s%20Documentation&query={type(obj).__name__}%20Object",
            # 'objectType': type(obj).__name__,
            # 'depth': depth
        }
    elif isinstance(result, dict):
        result.update({
            'objectType': f"https://help.autodesk.com/view/fusion360/ENU/?cg=Developer%27s%20Documentation&query={type(obj).__name__}%20Object",
            # 'objectType': type(obj).__name__,
            #  'depth': depth
        })
        result = {k: v for k, v in result.items() if v is not None}
    
    return result

def attribute2json(body, attr) -> dict:
    if attr in ['this', 'objectType']: # ignore these attributes
        return None
    try:
        return getattr(body, attr)
    except:
        return None

class RequestHandler(BaseHTTPRequestHandler):
    def _do_ANY(self, request):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)
        context = get_context({ "path": path, "query": query, "request": request })
        result = None

        try:
            if path == "/eval":
                result = eval(request.get("code", ""), context)
                if "depth" in request:
                    result = object2json(result, max_depth=int(request["depth"]))
            elif path == "/exec":
                result = execute_code(request, context)
                if "depth" in request:
                    result = object2json(result, max_depth=int(request["depth"]))
            elif path == "/exec/ui":
                adsk.core.Application.get().fireCustomEvent('FusionHeadless.ExecOnUiThread', request.get("code", ""))
            else:
                handler = get_handler(path)
                if handler:
                    result = handler(**{k: v for k, v in context.items() if k in handler.__code__.co_varnames})
                else:
                    return self.send_error(404, f"Route {path} not defined")
        
            if hasattr(result, 'send') and callable(getattr(result, 'send')):
                result.send(self)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "result": result
                }).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(traceback.format_exc().encode())

    def do_GET(self):
        return self._do_ANY({})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            request = {}

        return self._do_ANY(request)

def start_server(port=5000):
    server = HTTPServer(("localhost", port), RequestHandler)
    print(f"[FusionHeadless] Listening on port {port}")
    server.serve_forever()
