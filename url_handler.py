import argparse
import sys
import os
import tempfile
import winreg
import send
from urllib.parse import urlparse, parse_qs

scheme = "fh"

class Log:
    def __init__(self):
        self.log_file = os.path.join(tempfile.gettempdir(), os.path.basename(__file__) + ".txt")

    def _log(self, message, to_console=True):
        with open(self.log_file, "a") as f:
            f.write(message + "\n")
        if to_console:
            print(message)

    def error(self, message, to_console=True):
        if isinstance(message, Exception):
            message = f"{type(message).__name__}: {message}"
        self._log(f"ERROR: {message}", to_console=to_console)

    def info(self, message, to_console=True):
        self._log(f"INFO: {message}", to_console=to_console)

    def debug(self, message, to_console=True):
        self._log(f"DEBUG: {message}", to_console=to_console)
log = Log()

def pprint_hook(event, args):
    send.pprint_hook(event, args)

    if event == "http.client.send":
        conn, buffer = args
        http_str = buffer.decode('utf-8')
        log.info(http_str, to_console=False)

def main():
    parser = argparse.ArgumentParser(description="Installs Url Handler and handles URLs.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Install the URL handler.")
    group.add_argument("--uninstall", action="store_true", help="Uninstall the URL handler.")
    group.add_argument("--url", type=str, help="The URL to handle.")

    args = parser.parse_args()

    if args.install:
        log.info("Installing URL handler...")
        
        command = f'"{sys.executable}" "{os.path.abspath(__file__)}" --url "%1"'
        log.info(f"Registering URL scheme: {scheme} with command: {command}")

        key_path = f"SOFTWARE\\Classes\\{scheme}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f"{scheme} Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key_path}\\shell\\open\\command") as cmd_key:
            winreg.SetValueEx(cmd_key, None, 0, winreg.REG_SZ, command)

        log.info("URL handler installed successfully.")

    elif args.uninstall:
        log.info("Uninstalling URL handler...")
        
        key_path = f"SOFTWARE\\Classes\\{scheme}"
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            log.info("URL handler uninstalled successfully.")
        except FileNotFoundError:
            log.error(f"URL handler for scheme '{scheme}' not found.")
        except Exception as e:
            log.error(f"Failed to uninstall URL handler: {e}")
            sys.exit(1)

    elif args.url:
        try:
            url = args.url
            log.info(f"Handling URL: {url}")

            if not url.startswith(f"{scheme}://"):
                raise ValueError(f"URL must start with '{scheme}://'")

            parsed = urlparse(url)
            log.debug(f"Parsed URL: {parsed}")
            query = parse_qs(parsed.query)
            log.debug(f"Query parameters: {query}")
            
            sys.addaudithook(pprint_hook)
            result = send.get(parsed.path, parsed.query)
            log.info(result)

        except Exception as e:
            log.error(e)
            input("An error occurred while handling the URL. Press Enter to exit.")
            sys.exit(1)


if __name__ == "__main__":
    main()