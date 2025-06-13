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

def raise_error(resp_status, resp_reason, resp_data, file_path_hint=None):
    try:
        error_data = json.loads(resp_data)
    except json.JSONDecodeError:
        error_data = resp_data

    if isinstance(error_data, dict):
        if 'traceback' in error_data:
            traceback = error_data['traceback'].strip()
            if file_path_hint:
                traceback = traceback.replace("<string>", file_path_hint)
            print(f"{traceback}")
        elif 'message' in error_data:
            print(f"{error_data['message'].strip()}")
    else:
        print(f"{error_data}")
    
    print(f"HttpException {resp_status}: {resp_reason}")    
    return ""

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
        return raise_error(resp.status, resp.reason, resp_data)

    return json.loads(resp_data)

def post(endpoint, data=None, file_path_hint=None):
    body = json.dumps(data) if data is not None else None

    conn = http.client.HTTPConnection(host, port)
    conn.request('POST', endpoint, body=body, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read().decode()
    conn.close()

    if resp.status != 200:
        return raise_error(resp.status, resp.reason, resp_data, file_path_hint)

    return json.loads(resp_data)

def test(file_path, context = {}):
    with open(file_path, 'r') as file:
        code = file.read()

    for k, v in context.items():
        if k in ['app', 'adsk']:
            context[k] = ContextVariable(k)

    source = "\n".join(
        [code] +
        ["", f"result = handle(**{repr(context)})"]
    )
    #print(f">> /exec:\n{source}")
    print(post("/exec", {"code": source}, file_path_hint=file_path))

    