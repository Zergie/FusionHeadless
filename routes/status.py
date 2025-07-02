"""
Module for checking the server status.
"""
import datetime
import os
import sys

def get_uptime(startup_time: datetime.datetime) -> str:
    uptime = datetime.datetime.now() - startup_time
    if uptime.days > 0:
        return f"{uptime.days} days, {uptime.seconds // 3600} hours, {(uptime.seconds // 60) % 60} minutes"
    elif uptime.seconds > 3600:
        return f"{uptime.seconds // 3600} hours, {(uptime.seconds // 60) % 60} minutes"
    elif uptime.seconds > 60:
        return f"{uptime.seconds // 60} minutes, {uptime.seconds % 60} seconds"
    else:
        return f"{uptime.total_seconds():0.0f} seconds"

def handle(app, startup_time) -> any:
    return {
        "status": "Server is running",
        "uptime": get_uptime(startup_time),
        "version": f"Autodesk Fusion v{app.version}",
        "python": sys.version,
    }

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, {})