"""
Module for checking the server status.
"""
import sys

def handle(app) -> any:
    return {
        "status": "Server is running",
        "version": f"Autodesk Fusion v{app.version}",
        "python": sys.version,
    }

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, {})