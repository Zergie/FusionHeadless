"""
Handles listing of components or bodies from the active Fusion 360 design based on the provided path.
"""


def get_color(body) -> str:
    colors = [x for x in body.appearance.appearanceProperties if x.name == "Color"]

    if not colors or len(colors) == 0:
        return "00000000"
    
    if colors[0].value is None:
        return "00000000"

    return "%0.2X%0.2X%0.2XFF" % (colors[0].value.red, colors[0].value.green, colors[0].value.blue)

def body2json(body) -> dict:
    return {
        'name': body.name,
        'volume': body.physicalProperties.volume,
        'mass': body.physicalProperties.mass,
        'area': body.physicalProperties.area,
        # 'physicalProperties' : object2json(body.physicalProperties),
        'centerOfMass': [round(v, 2) for v in body.physicalProperties.centerOfMass.asArray()],
        'color': get_color(body),
        'material': body.material.name if body.material else None,
        'boundingBox': {
            'min': [round(v, 2) for v in body.boundingBox.minPoint.asArray()],
            'max': [round(v, 2) for v in body.boundingBox.maxPoint.asArray()],
        },
    }

def handle(path:str, app) -> any:
    design = app.activeProduct

    if path == "/list/components":
        result = {}
    elif path == "/list/bodies":
        result = [body2json(x) for x in design.rootComponent.bRepBodies]

    for occ in design.rootComponent.allOccurrences:
        comp = occ.component
        if path == "/list/components":
            if comp.name in result:
                result[comp.name]['count'] += 1
            else:
                result[comp.name] = {
                    'name'  : comp.name, 
                    'bodies': [body2json(x) for x in comp.bRepBodies], 
                    'count' : 1
                }
        elif path == "/list/bodies":
            result += [body2json(x) for x in comp.bRepBodies]

    if isinstance(result, dict):
        return [v for _, v in result.items()]
    else:
        return result


if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { "path" : "/list/bodies", "app": None })