"""
Reloads all FusionHeadless modules and restarts the server.
This is useful for development purposes to apply changes without restarting Fusion 360.
"""
import importlib
import sys

def handle(path:str, app) -> any:
    modules = {x: getattr(sys.modules.get(x), '__file__', None) for x in sorted(sys.modules)}
    my_modules = {k: v for k, v in modules.items() if v is not None and "FusionHeadless" in v}
    
    result = {}
    for module in my_modules:
        if module == "server":
            continue

        try:
            importlib.reload(sys.modules[module])
            result[module] = "Reloaded"
        except:
            del sys.modules[module]
            result[module] = "Removed"
    
    if path == "/restart":
        result["server"] = "Restarting.."
        app.fireCustomEvent('FusionHeadless.Restart')
    return result

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, {})