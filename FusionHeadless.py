import adsk.core
import os
import sys
import threading
import traceback
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import server
except:
    adsk.core.Application.get().userInterface.messageBox("Loading failed:\n" + traceback.format_exc())
importlib.reload(server) # Ensure the latest version of server is loaded

app = None
ui = adsk.core.UserInterface.cast(None)
handlers = []
customEvent = None
server_thread: threading.Thread = None

def run(context):
    global app, ui, customEvent, handlers, server_thread
    app = adsk.core.Application.get()
    ui = app.userInterface
    
    customEvent = app.registerCustomEvent('FusionHeadless.ExecOnUiThread')
    onThreadEvent = server.ExecOnUiThreadHandler()
    customEvent.add(onThreadEvent)
    handlers.append(onThreadEvent)

    try:
        server_thread = threading.Thread(target=server.start_server, daemon=True).start()
    except:
        adsk.core.Application.get().userInterface.messageBox("Startup failed:\n" + traceback.format_exc())

def stop(context):
    global server_thread
    if server_thread and server_thread.is_alive():
        try:
            server.stop_server()
        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox(f"Error stopping server: {e}")
