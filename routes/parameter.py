"""
<< short description >>
"""
from _utils_ import log
import re

class GenericParameter:
    def __init__(self, name, parent, prop):
        self.name = name
        self.parent = parent
        self.property = prop
    
    @property
    def expression(self):
        return getattr(self.parent, self.property)
    
    @expression.setter
    def expression(self, value):
        prop_type = type(self.expression)
        if isinstance(value, str):
            if prop_type is bool:
                value = value.lower() in ("true", "1", "yes", "on")
            elif prop_type is int:
                value = int(value)
            elif prop_type is float:
                value = float(value)
            elif prop_type is str:
                pass
            else:
                try:
                    value = prop_type(value)
                except Exception:
                    pass
        
        try:
            limits = getattr(self.parent, f"{self.property[:-5]}Limits", None)
            if limits.minimumValue == limits.maximumValue:
                pass
            elif value < limits.minimumValue:
                value = limits.minimumValue
            elif value > limits.maximumValue:
                value = limits.maximumValue
        except Exception:
            pass
        setattr(self.parent, self.property, value)

def iter_parameters_in_component(design, component):
    for sketch in component.sketches:
        for i in sketch.sketchDimensions:
            yield i.parameter
        index = 0
        for i in sketch.sketchTexts:
            yield GenericParameter(f"{sketch.name}-{index}", i, "text")
            index += 1
    for i in component.joints:
        if i.jointMotion.jointType == 0:
            pass
        else:
            for prop in [x for x in dir(i.jointMotion) if not x.startswith('_') and x.endswith('Value')]:
                name = f"{i.name}-{prop[:-5]}"
                # name = f"{component.name}-{i.name}-{prop[:-5]}"
                yield GenericParameter(name, i.jointMotion, prop)

    if design.designType == 1:
        for i in component.modelParameters:
            yield i

def iter_parameters(design):
    if design.designType == 1:
        for i in design.userParameters:
            yield i
    for i in iter_parameters_in_component(design, design.rootComponent):
        yield i
    for occurrence in design.rootComponent.allOccurrences:
        for i in iter_parameters_in_component(design, occurrence.component):
            yield i

def sort_result(x):
    m = re.match(r"^d(\d+)", x[0])
    if m:
        return (2, int(m.group(1)))
    
    m = re.match(r"^([^\d]+)(\d+)", x[0])
    if m:
        return (1, m.group(1), int(m.group(2)))

    return (0, x[0].lower())

def handle(query, app) -> any:
    design = app.activeProduct

    if len(query.keys()) == 0:
        result = {x.name : x.expression for x in iter_parameters(design) if not x is None}
        # return [x.name for x in iter_parameters(design) if not x is None]
    else:
        result = {}
        keys = list(query.keys())
        for item in iter_parameters(design):
            if not item is None and item.name in keys:
                keys.remove(item.name)

                item.expression = str(query[item.name])
                result[item.name] = item.expression
            
            if len(keys) == 0:
                break
        for key in keys:
            result[key] = f"Parameter '{key}' not found."

    return dict(sorted(result.items(), key=sort_result))

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, )
    # _client_.test(__file__, {"Revolute 109-rotation": 0.0})