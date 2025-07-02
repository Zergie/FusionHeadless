import importlib
import importlib.util
import sys
import os

routes = {}
def register(path:str, handler_func):
    routes[path] = handler_func

def get_handler(path:str):
    return routes.get(path, None)

modules = {}
def module(file:str):
    if not file in modules:
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{file}.py")
        spec = importlib.util.spec_from_file_location(file, base_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[file] = module
    return modules[file]

register("/status", module("status").handle)
register("/components", module("list").handle)
register("/bodies", module("list").handle)
register("/export/step", module("export").handle)
register("/export/stl", module("export").handle)
register("/projects", module("list_projects").handle)
register("/document", module("document").handle)
register("/files", module("files").handle)
register("/render", module("render").handle)
register("/reload", module("reload").handle)
register("/restart", module("reload").handle)
register("/select", module("select").handle)