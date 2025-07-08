import argparse
import sys
import os
import tempfile
import traceback
import winreg
from urllib.parse import urlparse, parse_qs
import cli
from send import host, port
import cli.my_printer as printer

scheme = "FusionHeadless"
key_path = f"SOFTWARE\\Classes\\{scheme}"

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
        self._log(f"ERROR: {message}\nTraceback:{traceback.format_exc()}", to_console=to_console)

    def info(self, message, to_console=True):
        self._log(f"INFO: {message}", to_console=to_console)

    def debug(self, message, to_console=True):
        self._log(f"DEBUG: {message}", to_console=to_console)
log = Log()

def pprint_hook(event, args):
    printer.pprint_hook(event, args)

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
        
        pythonw_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(pythonw_exe):
            command = f'"{pythonw_exe}" "{os.path.abspath(__file__)}" --url "%1"'
        else:
            command = f'"{sys.executable}" "{os.path.abspath(__file__)}" --url "%1"'
        log.info(f"Registering URL scheme: {scheme} with command: {command}")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f"{scheme} Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key_path}\\shell\\open\\command") as cmd_key:
            winreg.SetValueEx(cmd_key, None, 0, winreg.REG_SZ, command)

        log.info("URL handler installed successfully.")

    elif args.uninstall:
        log.info("Uninstalling URL handler...")
        
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{key_path}\\shell\\open\\command")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{key_path}\\shell\\open")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{key_path}\\shell")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{key_path}")
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

            if not url.lower().startswith(f"{scheme.lower()}://"):
                raise ValueError(f"URL must start with '{scheme}://'")

            parsed = urlparse(url)
            log.debug(f"Parsed URL: {parsed}")
            query = parse_qs(parsed.query)
            log.debug(f"Query parameters: {query}")

            cli.initialize(parsed.hostname, parsed.port)
            sys.addaudithook(pprint_hook)
            result = cli.methods.get(parsed.path, parsed.query)
            log.info(result)

        except Exception as e:
            log.error(e)
            sys.exit(1)


if __name__ == "__main__":
    main()