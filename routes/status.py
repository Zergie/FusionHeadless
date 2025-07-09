"""
Module for checking the server status.
"""
import datetime
import sys

def get_uptime(startup_time:datetime.datetime) -> str:
    uptime = datetime.datetime.now() - startup_time
    if uptime.days > 0:
        return f"{uptime.days} days, {uptime.seconds // 3600} hours, {(uptime.seconds // 60) % 60} minutes"
    elif uptime.seconds > 3600:
        return f"{uptime.seconds // 3600} hours, {(uptime.seconds // 60) % 60} minutes"
    elif uptime.seconds > 60:
        return f"{uptime.seconds // 60} minutes, {uptime.seconds % 60} seconds"
    else:
        return f"{uptime.total_seconds():0.0f} seconds"

def handle(app, status:dict) -> any:
    # copy status to result, except startup_time
    result = {
        "status": "Server is running",
        "uptime": get_uptime(status['startup_time']),
        "version": f"Autodesk Fusion v{app.version}",
        "python": sys.version,
        "paths" : {k: getattr(app.applicationFolders, k) for k in dir(app.applicationFolders) if not k.startswith('_') and 'path' in k.lower()},
    }
    result.update(status)
    del result['startup_time']
    return result

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, {})