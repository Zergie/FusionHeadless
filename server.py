from . import routes
from .route_registry import get_handler
from http.server import BaseHTTPRequestHandler, HTTPServer
import adsk.core
import json
import traceback

class RequestHandler(BaseHTTPRequestHandler):
    def _do_ANY(self, request):
        context = {
            "adsk": adsk,
            "app": adsk.core.Application.get(),
            "path": self.path,
            "request": request,
        }
        result = None

        try:
            if self.path == "/eval":
                result = eval(request.get("code", ""), context)
            elif self.path == "/exec":
                exec(request.get("code", ""), context)
                result = context.get("result", None)
            else:
                handler = get_handler(self.path)
                if handler:
                    result = handler(**{k: v for k, v in context.items() if k in handler.__code__.co_varnames})
                else:
                    return self.send_error(404, f"Route {self.path} not defined")
        
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "result": result
            }).encode())

        except ConnectionError as e:
            try:
                status_code, message = str(e).split(";", 1)
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": message,
                    "traceback": traceback.format_exc()
                }).encode())
            except:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "error",
                    "message": str(e),
                    "traceback": traceback.format_exc()
                }).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "error",
                "message": str(e),
                "traceback": traceback.format_exc()
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

def start_server(port=5000):
    server = HTTPServer(("localhost", port), RequestHandler)
    print(f"[FusionHeadless] Listening on port {port}")
    server.serve_forever()
