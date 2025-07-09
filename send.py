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

def output(result, path:str, verbose:bool=False):
    if os.path.exists(path):
        if isinstance(result, bytes):
            old = open(path, 'rb').read()
        else:
            old = json.loads(open(path, 'r').read())

        if old != result:
            doUpdate = True
        else:
            preamble = f"{path}: " if verbose else ""
            print(f"{preamble}Responses are identical, output file not updated.")
            doUpdate = False
    else:
        doUpdate = True
        
    if doUpdate:
        if isinstance(result, bytes):
            with open(path, 'wb') as f:
                f.write(result)
        else:
            json.dump(result, open(path, 'w'), indent=2, ensure_ascii=False)

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
    parser.add_argument('--base-material', type=str, help='Base material for matching files.')
    parser.add_argument('--accent-material', type=str, help='Accent material for matching files.')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--output', "-o", type=str, help='File path to save the response.')
    group.add_argument('--plain', action='store_true', help='Output plain text without formatting.')
    group.add_argument('--outdir', "-O", type=str, help='Output directory to save the response files.')

    # print(repr(sys.argv[1:]))
    # exit(0)
    args = parser.parse_args()
    
    if args.base_material and not args.match_with_files:
        parser.error("--base-material requires --match-with-files to be specified.")
    if args.accent_material and not args.match_with_files:
        parser.error("--accent-material requires --match-with-files to be specified.")

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
        result = match_with_files(result, args.match_with_files, args.base_material, args.accent_material)

    if args.output:
        output(result, args.output)
    elif args.outdir:
        mapping = {}
        if isinstance(result, list):
            for i in range(len(result)):
                mapping[i] = result[i]
        elif isinstance(result, dict):
            mapping = result

        for key, value in mapping.items():
            output(value, os.path.join(args.outdir, f"{key}.json"), verbose=True)

    elif args.plain:
        print(json.dumps(result))
    else:
        cli.pprint(result)

if __name__ == "__main__":
    main()