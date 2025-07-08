import json

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