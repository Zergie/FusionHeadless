#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import http.client
import json
import argparse
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
        error_data = resp_data.decode()

    if isinstance(error_data, dict):
        if 'traceback' in error_data:
            traceback = error_data['traceback'].strip()
            if file_path_hint:
                traceback = traceback.replace("<string>", file_path_hint)
            print(f"{traceback}")
        elif 'message' in error_data:
            print(f"{error_data['message'].strip()}")
    else:
        if file_path_hint:
            error_data = error_data.replace("<string>", file_path_hint)
        print(f"{error_data}")
    
    print(f"HttpException {resp_status}: {resp_reason}")    
    return ""

def get(endpoint, params=None):
    path = endpoint if endpoint.startswith('/') else f"/{endpoint}"
    if params:
        query = urlencode(params)
        path = f"{endpoint}?{query}"

    conn = http.client.HTTPConnection(host, port)
    conn.request('GET', path, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read()
    conn.close()

    if resp.status != 200:
        return raise_error(resp.status, resp.reason, resp_data)

    try:
        return json.loads(resp_data.decode())
    except:
        return resp_data

def post(endpoint, data=None, file_path_hint=None):
    path = endpoint if endpoint.startswith('/') else f"/{endpoint}"
    body = json.dumps(data) if data is not None else None

    conn = http.client.HTTPConnection(host, port)
    conn.request('POST', path, body=body, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read()
    conn.close()

    if resp.status != 200:
        return raise_error(resp.status, resp.reason, resp_data, file_path_hint)

    try:
        return json.loads(resp_data.decode())
    except:
        return resp_data

def test(file_path, context = {}):
    with open(file_path, 'r') as file:
        code = file.read()

    for k, v in context.items():
        if k in ['app', 'adsk', 'os', 'sys']:
            # If the context variable is one of these, we assume it's already defined
            context[k] = ContextVariable(k)

    data = {
        "imports": "\n".join([
            'sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(),"..","..","..","..","..","Roaming","Autodesk","Autodesk Fusion 360", "API", "AddIns", "FusionHeadless", "routes")))',
        ]),
        "code": "\n".join([
            code,
            "",
            f"result = handle(**{repr(context)})"
        ])
    }

    # lineNo = 0
    # for line in source.splitlines():
    #     lineNo += 1
    #     print(f"{lineNo:4d} │ {line}")
    print(post("/exec", data, file_path_hint=file_path))

    



def main():
    parser = argparse.ArgumentParser(description="Send HTTP requests to a server.")
    parser.add_argument('endpoint', type=str, help='The endpoint to send the request to.')
    parser.add_argument('--get', "-g", action='store_true', help='Send a GET request.')
    parser.add_argument('--post', "-p", action='store_true', help='Send a POST request with JSON data.')
    parser.add_argument('--data', "-d", type=str, help='JSON data to send with POST request.')
    parser.add_argument('--output', "-o", type=str, help='File path hint for error messages.')

    args = parser.parse_args()

    if args.get:
        response = get(args.endpoint)
    elif args.post:
        if args.data:
            data = json.loads(args.data)
        else:
            data = {}
        response = post(args.endpoint, data=data)
    else:
        print("Error: You must specify either --get or --post.")
    
    if args.output:
        open(args.output, 'wb').write(response)
    else:
        print(response)

if __name__ == "__main__":
    main()