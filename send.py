#!.venv/bin/python3
# -*- coding: utf-8 -*-
import argparse
import http.client
import json
import os
import sys
import re
import jmespath
from urllib.parse import parse_qs, urlencode, urlparse

host = 'localhost'
port = 5000
headers = {'Content-Type': 'application/json'}
suppress_errors = False

class Term:
    RESET = '\033[0m'
    
    @classmethod
    def url(cls, text, route, **kwargs):
        url = f"FusionHeadless://{host}:{port}{route}"
        if kwargs:
            url += "?" + urlencode(kwargs)
        return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"

    @classmethod
    def red(cls, text):
        return f"\033[91m{text}{cls.RESET}"

    @classmethod
    def green(cls, text):
        return f"\033[92m{text}{cls.RESET}"

    @classmethod
    def yellow(cls, text):
        return f"\033[93m{text}{cls.RESET}"
    
    @classmethod
    def blue(cls, text):
        return f"\033[94m{text}{cls.RESET}"

class FileItem:
    def __init__(self, root, name):
        self.name = name
        self.path = os.path.join(root, name)
        self.assigned = []

    def __repr__(self):
        return f"FileItem(name={self.name}, path={self.path})"
    
    def _get_compare_key(self, name, path=None):
        if path is None:
            path = ""
        else:
            path = "/".join(path.split(os.sep)[-2:-1]).lower() + "/"
        
        name = name.replace(' ', '_').lower()
        if name.endswith('.stl'):
            name = name[:-4]
        compare_key = path + "_".join([x for x in name.split('_') if not x.startswith('x') and x != '[a]']) + ".stl"
        return compare_key

    def __eq__(self, value):
        if isinstance(value, FileItem):
            compare_key = self._get_compare_key(value.name)
        elif isinstance(value, str):
            compare_key = self._get_compare_key(value)
        
        if "/" in compare_key:
            return compare_key == self._get_compare_key(self.name, self.path)
        else:
            return compare_key == self._get_compare_key(self.name)


class ListArgument:
    def __init__(self, argument):
        self.items = [item.strip() for item in argument.split(',')]
    def __repr__(self):
        return f"ListArgument({self.items})"
    def __str__(self):
        return self.__repr__()
    def __iter__(self):
        return iter(self.items)

class GroupArgument:
    def __init__(self, argument):
        args = argument.split(',')
        if len(args) == 1:
            self.selector = args[0]
            self.regex = None
            self.name = None
        elif len(args) == 3:
            self.selector, self.regex, self.name = args
            self.regex = re.compile(self.regex.strip(), re.IGNORECASE)
            self.name = self.name.strip()
        else:
            raise ValueError("GroupArgument must be in the format 'selector,regex,name' or 'selector'.")
 
    def __repr__(self):
        return f"GroupArgument(selector={self.selector}, regex={self.regex}, name={self.name})"
    
    def __str__(self):
        return self.__repr__()
    
    def _iter_(self, obj):
        for item in obj:
            if self.regex is None:
                yield item
            elif self.regex.match(item[self.selector]):
                item[self.selector] = self.regex.sub(self.name, item[self.selector])
                yield item
             
    def __call__(self, obj):
        group = {}

        for item in self._iter_(obj):
            key = item[self.selector]
            if key not in group:
                group[key] = {
                    'name': key,
                    'items': [],
                    'count': 0
                }
            group[key]['items'].append(item)
            if 'count' in item:
                group[key]['count'] += item['count']
            else:
                group[key]['count'] += 1
        return [x for x in group.values()]
        # return [x for x in self._iter_(obj)]


class ContextVariable:
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return self.name

class HttpException(Exception):
    def __init__(self, status, reason):
        super().__init__(f"HttpException {status}: {reason}")
        self.status = status
        self.reason = reason
    def __str__(self):
        return f"HttpException {self.status}: {self.reason}"

def raise_error(resp_status, resp_reason, resp_data, file_path_hint=None):
    global suppress_errors
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
    
    if suppress_errors:
        print(f"HttpException {resp_status}: {resp_reason}")
        return ""
    else:
        raise HttpException(resp_status, resp_reason)

def pprint_hook(event, args):
    if event == "http.client.send":
        try:
            from pygments import highlight
            from pygments.lexers.textfmts import HttpLexer
            from pygments.formatters import TerminalFormatter
            colored = True
        except ImportError:
            colored = False

        conn, buffer = args
        http_str = buffer.decode('utf-8')
        if colored:
            print(highlight(http_str, HttpLexer(), TerminalFormatter()))
        else:
            print(http_str)
    elif event == "http.client.connect":
        conn, host, port = args
        # print(f"Connecting to {host}:{port} ...")

def pprint(obj):
    if isinstance(obj, (dict, list)):
        try:
            from pygments import highlight
            from pygments.lexers import JsonLexer
            from pygments.formatters import TerminalFormatter
            colored = True
        except ImportError:
            colored = False

        json_str = json.dumps(obj, indent=2, ensure_ascii=False)
        if colored:
            print(highlight(json_str, JsonLexer(), TerminalFormatter()))
        else:
            print(json_str)
    elif isinstance(obj, bytes):
        print(obj.decode('utf-8'))
    else:
        print(obj)

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
    content = re.sub(r'\x1b\[[^m]*m', '', file.read())
    try:
        return json.loads(content)
    except:
        return content

def match_with_files(data:list, folder:str, accent_color:str) -> list:
    if not os.path.exists(folder):
        raise FileNotFoundError(f"Folder '{folder}' does not exist.")

    if not isinstance(data, list):
        raise TypeError("Data must be a list of items with 'name' attribute.")

    def clean_name(name):
        result = re.sub(r'(^\[a\]_|_x\d+( \(\d+\))?$|( \(\d+\))$)', '', name).lower()
        result = result.replace(' ', '_').lower()
        return result

    def get_name(component, body, count, color):
        result = ""
        if color == accent_color:
            result += f"[a]_"

        c_name = clean_name(component)
        b_name = clean_name(body)
        if b_name == c_name or b_name.startswith("body"):
            result += c_name
        else:
            result += c_name
            result = f"{b_name}/{result}"
        
        if count > 1:
            result += f"_x{count}"
        return f"{result}.stl"

    fileItems = []
    for root, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith('.stl'):
                fileItems.append(FileItem(root=root, name=name))

    warnings = 0
    errors = 0
    for component in data:
        if 'name' not in component:
            raise ValueError(f"Each item in data must have a 'name' attribute. ({component})")
        if 'bodies' not in component:
            raise ValueError(f"Each item in data must have a 'bodies' attribute. ({component})")
        if not isinstance(component['bodies'], list):
            raise TypeError(f"'bodies' attribute must be a list. ({component})")

        for body in component['bodies']:
            if 'id' not in body:
                raise ValueError(f"Each body in 'bodies' must have an 'id' attribute. ({body})")
            if 'name' not in body:
                raise ValueError(f"Each body in 'bodies' must have a 'name' attribute. ({body})")
            
            name = get_name(component['name'], body['name'], component['count'], body['color'])
            matches = [fileItem for fileItem in fileItems if fileItem == name]
            body['suggested_name'] = name

            if len(matches) == 0 and "/" in name:
                name = name.split("/")[-1]
                matches = [fileItem for fileItem in fileItems if fileItem == name]

            if len(matches) == 0:
                name =  get_name(body['name'], body['name'], component['count'], body['color'])
                matches = [fileItem for fileItem in fileItems if fileItem == name]

            if len(matches) == 0:
                sys.stderr.write(Term.yellow(f"Warning: No matching file found for " + Term.url(component['name'], "/select", id=component['id']) + f" - {body['name']} -> {name}\n"))
                warnings += 1
                name = get_name(component['name'], body['name'], component['count'], body['color'])
                fileItem = FileItem(folder, name)
                fileItems.append(fileItem)
                matches = [fileItem]
            
            if len(matches) == 1:
                fileItem = matches[0]
                if body['id'] in fileItem.assigned:
                    for key in list(body.keys()):
                        del body[key]
                else:
                    fileItem.assigned.append(component)
                    body['path'] = fileItem.path
                    
            else:
                sys.stderr.write(Term.red(f"Error: Multiple matching files found for " + Term.url(component['name'], "/select", id=component['id']) + f" - {body['name']} -> {name}:\n"))
                for match in matches:
                    sys.stderr.write(f"  - {match}")
                errors += 1

            component['bodies'] = [b for b in component['bodies'] if 'id' in b]

    for fileItem in [x for x in fileItems if len(x.assigned) > 1]:
        assigned = ", ".join([Term.url(x["name"], "/select", id=x["id"]) for x in fileItem.assigned])
        sys.stderr.write(Term.yellow(f"Warning: File {fileItem.path} is already assigned multiple times: {assigned}\n"))
        warnings += 1

    for fileItem in [x for x in fileItems if len(x.assigned) == 0]:
        sys.stderr.write(Term.yellow(f"Warning: File {fileItem.path} was not assigned to any component.\n"))
        warnings += 1

    sys.stderr.write("\nSummary: " + Term.green(f"{len(data)} processed") + ", " + Term.yellow(f"{warnings} warnings") + ", " + Term.red(f"{errors} errors") + ".\n")

    return [x for x in data if len(x['bodies']) > 0]

def test(file_path, query = {}, output=None, timeout=60):
    global suppress_errors
    suppress_errors = True

    with open(file_path, 'r') as file:
        code = file.read()

    context = {}
    if isinstance(query, dict):
        context["query"] = query
    elif isinstance(query, str):
        parsed = urlparse(query)
        context["query"] = parse_qs(parsed.query)

    def_handle = [i for i in code.splitlines() if re.match(r'def\s*handle\s*\(', i)][0]
    def_handle_params = [i.strip(' ,)') for i in re.findall(r'([^,()]+\s*[,)])', def_handle)]
    for i in [i for i in def_handle_params if i in ('app', 'adsk', 'ui', 'os', 'sys', 'startup_time')]:
        # If the context variable is one of these, we assume it's already defined
        context[i] = ContextVariable(i)

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

def main():
    parser = argparse.ArgumentParser(description="Send HTTP requests to a server.")

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--get', type=str, help='Send a GET request.')
    group.add_argument('--post', type=str, help='Send a POST request with JSON data.')

    parser.add_argument('--file', "-f", type=argparse.FileType('r', encoding='utf-8'), help='Reads response/data from a file.')
    parser.add_argument('--data', "-d", type=str, help='JSON data to send with POST request.')
    parser.add_argument('--jmespath', "-j", action='append', help='JMESPath to extract data from the response.')
    parser.add_argument('--group', "-g", type=GroupArgument, help='Group selector for the request.')
    parser.add_argument('--group-jmespath', "-gj", type=str, help='JMESPath to extract data from the group.')
    parser.add_argument('--timeout', "-t", type=int, default=60, help='Timeout for the request in seconds.')

    parser.add_argument('--match-with-files', "-m", type=str, help='Find files in a folder and match them with the response.')
    parser.add_argument('--accent-color', "-ac", type=str,  help='Accent color for the mapping with filenames.')


    group = parser.add_mutually_exclusive_group()
    group.add_argument('--output', "-o", type=str, help='File path to save the response.')
    group.add_argument('--append', "-a", type=str, help='File path to save the response as an append operation.')
    group.add_argument('--plain', action='store_true', help='Output plain text without formatting.')

    # print(repr(sys.argv[1:]))
    # exit(0)
    if len(sys.argv) == 1:
        args = parser.parse_args(['--file', '.\\obj\\components.printed.json', '--match-with-files', 'STLs', '--accent-color', 'C43527FF'])
    else:
        args = parser.parse_args()
    
    if args.accent_color and not args.match_with_files:
        parser.error("Accent color requires --match-with-files to be specified.")

    sys.addaudithook(pprint_hook)

    data = {}
    if args.file and (args.get or args.post):
        items = file(args.file)
        data.update(items[0])
    if args.data:
        data.update(json.loads(args.data))

    result = None
    if args.get:
        result = get(args.get, data, timeout=args.timeout)
    elif args.post:
        result = post(args.post, data, timeout=args.timeout)
    elif args.file:
        result = file(args.file)
    else:
        print("Error: You must specify either --get, --post or --file.")

    if args.jmespath:
        for x in args.jmespath:
            result = jmespath.search(x, result)

    if args.group_jmespath:
        group = {}
        for item in result:
            key = jmespath.search(args.group_jmespath, item)
            if key not in group:
                group[key] = []
            group[key].append(item)
        result = group

    if args.match_with_files:
        result = match_with_files(result, args.match_with_files, args.accent_color)

    if args.output:
        if os.path.exists(args.output):
            if isinstance(result, bytes):
                old = open(args.output, 'rb').read()
            else:
                old = json.loads(open(args.output, 'r').read())

            if old != result:
                doUpdate = True
            else:
                print("Responses are identical, output file not updated.")
                doUpdate = False
        else:
            doUpdate = True
        
        if doUpdate:
            if isinstance(result, bytes):
                with open(args.output, 'wb') as f:
                    f.write(result)
            else:
                json.dump(result, open(args.output, 'w'), indent=2, ensure_ascii=False)
    elif args.append:
        if not isinstance(result, list):
            parser.error("Append operation requires a list of items to append.")
        elif len(result) == 0:
            parser.error("No data to append, skipping append operation.")
            
        if os.path.exists(args.append):
            try:
                old = json.loads(open(args.append, 'r').read())
            except json.JSONDecodeError:
                old = []

            if not isinstance(old, list):
                parser.error("Append file is not a valid JSON array.")

            old.append(result)
            result = old
        
        json.dump(result, open(args.append, 'w'), indent=2, ensure_ascii=False)
    elif args.plain:
        print(json.dumps(result))
    else:
        pprint(result)

if __name__ == "__main__":
    main()