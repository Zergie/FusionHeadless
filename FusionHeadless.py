from ast import arg
import glob
import json
import adsk.core, traceback
import threading

try:
    from . import server
except:
    adsk.core.Application.get().userInterface.messageBox("Loading failed:\n" + traceback.format_exc())

app = None
ui = adsk.core.UserInterface.cast(None)
handlers = []
customEvent = None

class ThreadEventHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            # Make sure a command isn't running before changes are made.
            if ui.activeCommand != 'SelectCommand':
                ui.commandDefinitions.itemById('SelectCommand').execute()
            
            server.execute_code(args.additionalInfo)
        except:
            if ui:
                ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
            adsk.autoTerminate(False)


def run(context):
    global app
    global ui
    global customEvent
    app = adsk.core.Application.get()
    ui = app.userInterface
    
    customEvent = app.registerCustomEvent('FusionHeadless.ExecOnUiThread')
    onThreadEvent = ThreadEventHandler()
    customEvent.add(onThreadEvent)
    handlers.append(onThreadEvent)

    try:
        threading.Thread(target=server.start_server, daemon=True).start()
    except:
        adsk.core.Application.get().userInterface.messageBox("Startup failed:\n" + traceback.format_exc())

def stop(context):
    pass
    # adsk.core.Application.get().userInterface.messageBox("Stopping FusionHeadless add-in.")
