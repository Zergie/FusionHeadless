import adsk.core, traceback
import threading

try:
    from . import server
except:
    adsk.core.Application.get().userInterface.messageBox("Loading failed:\n" + traceback.format_exc())

def run(context):
    try:
        threading.Thread(target=server.start_server, daemon=True).start()
    except:
        adsk.core.Application.get().userInterface.messageBox("Startup failed:\n" + traceback.format_exc())

def stop(context):
    pass
    # adsk.core.Application.get().userInterface.messageBox("Stopping FusionHeadless add-in.")
