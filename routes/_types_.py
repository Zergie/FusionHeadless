from http.server import BaseHTTPRequestHandler

class HttpResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.headers = {}
        self.content = ""
    
    def send(self, requestHandler: BaseHTTPRequestHandler):
        requestHandler.send_response(self.status_code)
        for k, v in self.headers.items():
            requestHandler.send_header(k, v)
        requestHandler.end_headers()
        requestHandler.wfile.write(self.content)

class BinaryResponse(HttpResponse):
    def __init__(self, data):
        super().__init__(200)
        self.headers["Content-Type"] = "application/octet-stream"
        self.content = data