routes = {}

def register(path, handler_func):
    routes[path] = handler_func

def get_handler(path):
    return routes.get(path, None)
