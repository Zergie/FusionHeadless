import argparse
import base64
import sys
import os
import tempfile
import winreg

class Log:
    def __init__(self):
        self.log_file = os.path.join(tempfile.gettempdir(), os.path.basename(__file__) + ".txt")

    def log(self, message):
        with open(self.log_file, "a") as f:
            f.write(message + "\n")
        print(message)

    def error(self, message):
        if isinstance(message, Exception):
            message = f"{type(message).__name__}: {message}"
        self.log(f"ERROR: {message}")

    def info(self, message):
        self.log(f"INFO: {message}")

    def debug(self, message):
        self.log(f"DEBUG: {message}")

def main():
    parser = argparse.ArgumentParser(description="Installs Url Handler and handles URLs.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Install the URL handler.")
    group.add_argument("--uninstall", action="store_true", help="Uninstall the URL handler.")
    group.add_argument("--url", type=str, help="The URL to handle.")

    args = parser.parse_args()
    log = Log()

    if args.install:
        log.info("Installing URL handler...")
        
        scheme = "fh"
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
        
        scheme = "fh"
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
        if not args.url.startswith("fh://"):
            log.error(f"Invalid URL format: {args.url}. Expected format: fh://<command>")
            sys.exit(1)

        log.info(f"Handled URL: {args.url}")
        try:
            value = f"{int.from_bytes(base64.b85decode(args.url[5:-1]), byteorder='big'):x}"
            log.info(f"Value: {value}")

            s = f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"
            log.info(f"Formatted: {s}")
        except Exception as e:
            log.error(e)

if __name__ == "__main__":
    main()