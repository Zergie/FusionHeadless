import importlib
import importlib.util
import os
import sys
import types

routes = {}
def register(path:str, handler_func):
    routes[path] = handler_func

def get_handler(path:str):
    return routes.get(path, None)

class FusionHeadlessModules:
    def __getattr__(self, file:str) -> types.ModuleType:
        key = f"FusionHeadless.{file}"
        if not key in sys.modules:
            base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{file}.py")
            spec = importlib.util.spec_from_file_location(file, base_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[key] = module
        return sys.modules[key]
FusionHeadless = FusionHeadlessModules()

register("/status"     , FusionHeadless.status.handle)
register("/components" , FusionHeadless.list.handle)
register("/bodies"     , FusionHeadless.list.handle)
register("/export"     , FusionHeadless.export.handle)
register("/projects"   , FusionHeadless.list_projects.handle)
register("/document"   , FusionHeadless.document.handle)
register("/files"      , FusionHeadless.files.handle)
register("/render"     , FusionHeadless.render.handle)
register("/select"     , FusionHeadless.select.handle)
register("/parameter"  , FusionHeadless.parameter.handle)