"""
Handles listing of components or bodies from the active Fusion 360 design based on the provided path.
"""
from _utils_ import get_allBodies, body2dict, component2dict

def appendBody(result, body) -> None:
    dict = body2dict(body, count=0)
    if not dict['id'] in result:
        result[dict['id']] = dict
    result[dict['id']]['count'] += 1

def handle(path:str, app) -> any:
    design = app.activeProduct

    result = {}
    if path == "/bodies":
        for body in get_allBodies(design):
            appendBody(result, body)

        return {k:v for k, v in result.items()}

    elif path == "/components":
        for component in [x.component for x in design.rootComponent.allOccurrences]:
            json = component2dict(component, bodies=[body2dict(x) for x in component.bRepBodies], count=0)
            if not json['id'] in result:
                result[json['id']] = json
            result[json['id']]['count'] += 1

        return {k:v for k, v in result.items() if len(v['bodies']) > 0}

    raise Exception(f"Unknown path: {path}. Supported paths are: /bodies, /components")

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { "path" : "/bodies", "app": None }, output="C:\\GIT\\YAMMU\\obj\\bodies.json")