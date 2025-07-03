import adsk.core # type: ignore
import importlib
import os
import sys
import threading
import traceback

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, "routes"))
try:
    import server
except:
    adsk.core.Application.get().userInterface.messageBox("Loading failed:\n" + traceback.format_exc())

app = None
handlers = []
server_thread: threading.Thread|None = None

class RestartHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        global server_thread
        
        try:
            server.stop_server()
        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox("Error stopping server:\n" + traceback.format_exc())
        
        try:
            importlib.reload(server)
        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox("Error reloading server:\n" + traceback.format_exc())

        try:
            server_thread = threading.Thread(target=server.start_server, daemon=True)
            server_thread.start()
        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox("Restart failed:\n" + traceback.format_exc())

def register_event_handler(event_id:str, on_event):
    global app, handlers
    if not app:
        raise RuntimeError("Application instance is not initialized.")
    customEvent = app.registerCustomEvent(event_id)
    customEvent.add(on_event)
    handlers.append(on_event)

def run(context):
    global app, server_thread
    app = adsk.core.Application.get()

    register_event_handler('FusionHeadless.ExecOnUiThread', server.ExecOnUiThreadHandler())
    register_event_handler('FusionHeadless.Restart', RestartHandler())

    try:
        server_thread = threading.Thread(target=server.start_server, daemon=True)
        server_thread.start()
    except Exception as e:
        adsk.core.Application.get().userInterface.messageBox("Startup failed:\n" + traceback.format_exc())

def stop(context):
    global server_thread
    if server_thread and server_thread.is_alive():
        try:
            server.stop_server()
        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox("Error stopping server:\n" + traceback.format_exc())
