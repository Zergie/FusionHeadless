import http.client
import json
import re
from urllib.parse import parse_qs, urlencode, urlparse
from Exceptions import raise_error
from ContextVariable import ContextVariable
from my_printer import pprint

host = None
port = None
headers = {'Content-Type': 'application/json'}
def initialize(host_value, port_value):
    global host, port
    host = host_value
    port = port_value

def get(endpoint, params:dict=None, timeout=60):
    path = endpoint if endpoint.startswith('/') else f"/{endpoint}"
    if params:
        if isinstance(params, str):
            query = params
        else:
            query = urlencode(params)
        path += f"?{query}"

    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request('GET', path, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read()
    conn.close()

    if resp.status != 200:
        return raise_error(resp.status, resp.reason, resp_data)

    if resp.headers.get('Content-Type', '') == 'application/json':
        return json.loads(resp_data.decode())
    else:
        return resp_data

def post(endpoint, data:dict=None, file_path_hint=None, timeout=60):
    path = endpoint if endpoint.startswith('/') else f"/{endpoint}"
    if not data:
        body = None
    elif isinstance(data, str):
        body = data
    else:
        body = json.dumps(data)

    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request('POST', path, body=body, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read()
    conn.close()

    if resp.status != 200:
        return raise_error(resp.status, resp.reason, resp_data, file_path_hint)

    if resp.headers.get('Content-Type', '') == 'application/json':
        return json.loads(resp_data.decode())
    else:
        return resp_data

def file(file):
    result: dict|list[dict] = None
    for f in file:
        content = re.sub(r'\x1b\[[^m]*m', '', f.read())
        data = json.loads(content)

        if result is None:
            result = data
        elif isinstance(result, list) and isinstance(data, list):
            result.extend(data)
        elif isinstance(result, dict) and isinstance(data, dict):
            result.update(data)
        else:
            raise TypeError("Incompatible data types: cannot merge dict and list or vice versa.")
    return result

def test(file_path, query = {}, output=None, timeout=60):
    global suppress_errors
    suppress_errors = True

    with open(file_path, 'r') as file:
        code = file.read()

    context = {}

    def_handle = [i for i in code.splitlines() if re.match(r'def\s*handle\s*\(', i)][0]
    def_handle_params = [i.split(':')[0].strip(' ,)') for i in re.findall(r'([^,()]+\s*[,)])', def_handle)]
    for i in def_handle_params:
        if i in ('app', 'adsk', 'ui', 'os', 'sys', 'startup_time'):
            # If the context variable is one of these, we assume it's already defined
            context[i] = ContextVariable(i)
        elif i == 'query':
            if isinstance(query, dict):
                context["query"] = query
            elif isinstance(query, str):
                parsed = urlparse(query)
                context["query"] = parse_qs(parsed.query)
    data = {
        "code": "\n".join([
            code,
            "",
            f"result = handle(**{repr(context)})"
        ])
    }

    # lineNo = 0
    # for line in data['code'].splitlines():
    #     lineNo += 1
    #     print(f"{lineNo:4d} │ {line}")
    response = post("/exec", data, file_path_hint=file_path, timeout=timeout)
    
    if output is None:
        pprint(response)
    else:
        if isinstance(response, bytes):
            with open(output, 'wb') as f:
                f.write(response)
        elif len(response) == 0:
            print("No response data to write to output file.")
        else:
            with open(output, 'w') as f:
                json.dump(response, f, indent=2, ensure_ascii=False)