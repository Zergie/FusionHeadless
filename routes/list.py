
"""
Handles listing of components or bodies from the active Fusion 360 design based on the provided path.
"""

def handle(path:str, app) -> any:
    """
    TODO: handle files that have no rootComponent, only bodies!
    """
    design = app.activeProduct
    result = {}
    if hasattr(design, "rootComponent"):
        for occ in design.rootComponent.allOccurrences:
            comp = occ.component
            if path == "/list/components":
                if comp.name in result:
                    result[comp.name]['count'] += 1
                else:
                    result[comp.name] = {
                        'name'  : comp.name, 
                        'bodies': [body.name for body in comp.bRepBodies], 
                        'count' : 1
                    }
            elif path == "/list/bodies":
                for body in comp.bRepBodies:
                    if body.name in result:
                        result[body.name]['count'] += 1
                    else:
                        result[body.name] = {
                            'name' : body.name,
                            'count': 1
                        }
            else:
                raise ConnectionError("501;Endpoint not supported")

    return [v for _, v in result.items()]


if __name__ == "__main__":
    from _client_ import *
    test(__file__, { "path" : "/list/bodies", "app": ContextVariable("app") })