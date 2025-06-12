import http.client
import json
from urllib.parse import urlencode

host = 'localhost'
port = 5000
headers = {'Content-Type': 'application/json'}

class ContextVariable:
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return self.name

def get(endpoint, params=None):
    path = endpoint
    if params:
        query = urlencode(params)
        path = f"{endpoint}?{query}"

    conn = http.client.HTTPConnection(host, port)
    conn.request('GET', path, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read().decode()
    conn.close()

    if resp.status != 200:
        raise Exception(f"Error {resp.status}: {resp.reason} - {resp_data}")
    
    return json.loads(resp_data)

def post(endpoint, data=None):
    body = json.dumps(data) if data is not None else None

    conn = http.client.HTTPConnection(host, port)
    conn.request('POST', endpoint, body=body, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read().decode()
    conn.close()

    if resp.status != 200:
        raise Exception(f"Error {resp.status}: {resp.reason} - {resp_data}")
    
    return json.loads(resp_data)

def test(file_path, context = {}):
    with open(file_path, 'r') as file:
        code = file.read()

    source = "\n".join(
        [code] +
        ["", f"result = handle(**{repr(context)})"]
    )
    #print(f">> /exec:\n{source}")
    print(post("/exec", {"code": source}))

    