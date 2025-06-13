
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

def body2json(body, **kwargs) -> dict:
    result = {
        'name': body.name,
        'volume': body.physicalProperties.volume,
        'mass': body.physicalProperties.mass,
        'area': body.physicalProperties.area,
        'centerOfMass': [round(v, 2) for v in body.physicalProperties.centerOfMass.asArray()],
        'color': get_color(body),
        'material': body.material.name if body.material else None,
        'boundingBox': {
            'min': [round(v, 2) for v in body.boundingBox.minPoint.asArray()],
            'max': [round(v, 2) for v in body.boundingBox.maxPoint.asArray()],
        }
    }
    result.update(kwargs)
    return result


def handle(path:str, app) -> any:
    design = app.activeProduct
    result = {}

    if path == "/list/bodies":
        for x in design.rootComponent.bRepBodies:
            result[x.name] = body2json(x, count=1)

    for occ in design.rootComponent.allOccurrences:
        comp = occ.component
        if path == "/list/components":
            if comp.name in result:
                result[comp.name]['count'] += 1
            else:
                result[comp.name] = {
                    'name'  : comp.name, 
                    'bodies': [body2json(body) for body in comp.bRepBodies], 
                    'count' : 1
                }
        elif path == "/list/bodies":
            for body in comp.bRepBodies:
                if body.name in result:
                    result[body.name]['count'] += 1
                else:
                    result[body.name] = body2json(body, count=1)
        else:
            raise ConnectionError("501;Endpoint not supported")

    return [v for _, v in result.items()]


if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { "path" : "/list/bodies", "app": None })