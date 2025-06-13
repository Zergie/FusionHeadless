"""
Module for checking the server status.
"""

def handle() -> any:
    return f"Server is running"

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, {})