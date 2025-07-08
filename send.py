#!.venv/bin/python3
# -*- coding: utf-8 -*-
import argparse
import json
import os
import sys

import jmespath
import cli
from cli.methods import get, post, file
from cli.match_with_files import match_with_files

host = 'localhost'
port = 5000
cli.initialize(host, port)

def main():
    parser = argparse.ArgumentParser(description="Send HTTP requests to a server.")

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--get', type=str, help='Send a GET request.')
    group.add_argument('--post', type=str, help='Send a POST request with JSON data.')

    parser.add_argument('--file', "-f", action='append', type=argparse.FileType('r', encoding='utf-8'), help='Reads response/data from a file.')
    parser.add_argument('--data', "-d", type=str, help='JSON data to send with POST request.')
    parser.add_argument('--jmespath', "-j", action='append', help='JMESPath to extract data from the response.')
    parser.add_argument('--timeout', "-t", type=int, default=60, help='Timeout for the request in seconds.')

    parser.add_argument('--match-with-files', "-m", type=str, help='Find files in a folder and match them with the response.')
    parser.add_argument('--accent-color', "-ac", type=str,  help='Accent color for the mapping with filenames.')


    group = parser.add_mutually_exclusive_group()
    group.add_argument('--output', "-o", type=str, help='File path to save the response.')
    group.add_argument('--append', "-a", type=str, help='File path to save the response as an append operation.')
    group.add_argument('--plain', action='store_true', help='Output plain text without formatting.')

    # print(repr(sys.argv[1:]))
    # exit(0)
    args = parser.parse_args()
    
    if args.accent_color and not args.match_with_files:
        parser.error("Accent color requires --match-with-files to be specified.")

    sys.addaudithook(cli.pprint_hook)

    data = {}
    if args.file and (args.get or args.post):
        items = file(args.file)
        data.update(items)
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
        parser.error("Error: You must specify either --get, --post or --file.")

    if args.jmespath:
        for x in args.jmespath:
            result = jmespath.search(x, result)

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
        cli.pprint(result)

if __name__ == "__main__":
    main()