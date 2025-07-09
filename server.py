from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import adsk.core # type: ignore
import importlib
import json
import os
import routes
import sys
import threading
import traceback
import uuid


startup_time = datetime.now()
app = None
ui = None
def get_context(additional={}):
    global app, ui, startup_time
    if app is None:
        app = adsk.core.Application.get()
    if ui is None:
        ui = app.userInterface
    context = {
        "adsk" : adsk,
        "app"  : app,
        "os"   : os,
        "sys"  : sys,
        "ui"   : ui,
        "status": {
            "startup_time": startup_time,
            "routes": sorted(["/eval", "/exec", "/restart", "/reload"] + [x for x in routes.routes.keys()])
        }
    }
    context.update(additional)
    return context

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
    elif isinstance(obj, (list, tuple)):
        result = [object2json(x, max_depth, depth+1) for x in obj] if depth < max_depth else []
    elif isinstance(obj, dict):
        result = {k: object2json(v, max_depth, depth+1) for k, v in obj.items()} if depth < max_depth else {}
    elif hasattr(obj, 'asArray') and callable(obj.asArray):
        result = [object2json(v, max_depth, depth+1) for v in obj.asArray()] if depth < max_depth else []
    elif hasattr(obj, 'asDict') and callable(obj.asDict):
        result = {k: object2json(v, max_depth, depth+1) for k, v in obj.asDict().items()} if depth < max_depth else {}    
    elif hasattr(obj, '__iter__') and callable(obj.__iter__):
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

customEventArguments = {}
class CustomEventArgument:
    def __init__(self, path, query, context):
        self.uuid = str(uuid.uuid4())
        self.event = threading.Event()
        self.path = path
        self.query = query
        self.context = context
        self.result = None
        self.http_error = None 

    def __str__(self):
        return f"CustomEventArgument(uuid={self.uuid})"

    def __repr__(self):
        return self.__str__()

def handle_restart(path:str, app) -> any:
    modules = {x: getattr(sys.modules.get(x), '__file__', None) for x in sorted(sys.modules)}
    my_modules = {k: v for k, v in modules.items() if v is not None and "FusionHeadless" in v}
    
    result = {}
    for module in my_modules:
        if module == "server":
            continue

        try:
            importlib.reload(sys.modules[module])
            result[module] = "Reloaded"
        except:
            del sys.modules[module]
            result[module] = "Removed"
    
    if path == "/restart":
        result["server"] = "Restarting.."
        app.fireCustomEvent('FusionHeadless.Restart')
    return result

class ExecOnUiThreadHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        global ui, customEventArguments
        arg = None
        try:
            arg = customEventArguments.get(args.additionalInfo, None)
            if not arg:
                return  # If the argument is not found, do nothing
            elif arg.path == "/eval" or arg.path == "/exec":
                # evaluate or execute are low-level operations so a running server can be recovered
                if arg.path == "/eval":
                    arg.result = eval(arg.query.get("code", ""), arg.context)
                elif arg.path == "/exec":
                    exec(arg.query.get("code", ""), arg.context)
                    arg.result = arg.context.get("result", None)

                if "depth" in arg.query:
                    arg.result = object2json(arg.result, max_depth=int(arg.query["depth"]))
            elif arg.path == "/restart" or arg.path == "/reload":
                # restart and reload are low-level operations so a running server can be recovered
                modules = {x: getattr(sys.modules.get(x), '__file__', None) for x in sorted(sys.modules)}
                my_modules = {k: v for k, v in modules.items() if v is not None and "FusionHeadless" in v}
                
                arg.result = {}
                for module in my_modules:
                    if module == "server":
                        continue

                    try:
                        importlib.reload(sys.modules[module])
                        arg.result[module] = "Reloaded"
                    except:
                        del sys.modules[module]
                        arg.result[module] = "Removed"
                
                if arg.path == "/restart":
                    arg.result["server"] = "Restarting.."
                    app.fireCustomEvent('FusionHeadless.Restart')
            else:
                handler = routes.get_handler(arg.path)
                if handler:
                    args = handler.__code__.co_varnames[:handler.__code__.co_argcount]
                    kwargs = {k: v for k, v in arg.context.items() if k in args}
                    arg.result = handler(**kwargs)
                else:
                    arg.http_error = (404, f"Route {arg.path} not defined")
                
            arg.event.set()  # Signal that the code execution is complete
        except Exception as e:
            if arg:
                arg.result = None
                arg.http_error = (500, traceback.format_exc())
                arg.event.set()  # Signal that the code execution is complete
            elif ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
            adsk.autoTerminate(False)

class RequestHandler(BaseHTTPRequestHandler):
    def _do_ANY(self, request):
        global app, customEventArguments
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed_url.query).items()}
        query.update(request)  # Merge query parameters with request body
        context = get_context({ "path": path, "query": query, "request": request })

        arg = CustomEventArgument(path, query, context)
        customEventArguments[arg.uuid] = arg
        app.fireCustomEvent('FusionHeadless.ExecOnUiThread', arg.uuid)
        arg.event.wait()  # Wait for the event to be set by the custom event handler
        del customEventArguments[arg.uuid]  # Clean up after we're done

        if arg.http_error:
            self.send_response(arg.http_error[0])
            message = arg.http_error[1]
            if isinstance(message, str):
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(message.encode())
            else:
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(message).encode())
            self.send_error(arg.http_error[0], arg.http_error[1])
        elif hasattr(arg.result, 'send') and callable(getattr(arg.result, 'send')):
            arg.result.send(self)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "result": arg.result
            }).encode())

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

server:ThreadingHTTPServer = None
def start_server(port=5000):
    global server
    server = ThreadingHTTPServer(("localhost", port), RequestHandler)
    print(f"[FusionHeadless] Listening on port {port}")
    server.serve_forever()

def stop_server():
    global server
    if server:
        print("[FusionHeadless] Stopping server...")
        server.shutdown()
        server.server_close()
        print("[FusionHeadless] Server stopped.")