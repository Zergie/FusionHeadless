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
            elif path == "/exec":
                if request.get("ui_thread", False):
                    adsk.core.Application.get().fireCustomEvent('FusionHeadless.ExecOnUiThread', request.get("code", ""))
                else:
                    result = execute_code(request, context)
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
