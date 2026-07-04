"""Modify the expression of an existing design parameter.

Works for user parameters and discovered model/sketch/joint parameters. The
parameter is selected by exact name.
"""


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact parameter name to modify."
            },
            "expression": {
                "type": "string",
                "description": "New expression to assign."
            },
            "allow_multiple": {
                "type": "boolean",
                "description": "When true, update all matching parameter names. Default false."
            }
        },
        "required": ["name", "expression"]
    }


class GenericParameter:
    def __init__(self, name, parent, prop, category):
        self.name = name
        self.parent = parent
        self.property = prop
        self.category = category

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
            if limits and limits.minimumValue != limits.maximumValue:
                if value < limits.minimumValue:
                    value = limits.minimumValue
                elif value > limits.maximumValue:
                    value = limits.maximumValue
        except Exception:
            pass

        setattr(self.parent, self.property, value)


def _parse_bool(query: dict, key: str, default: bool) -> bool:
    value = query.get(key, default)
    if isinstance(value, bool):
        return value
    raise Exception(f"'{key}' must be a boolean")


def _is_parametric(design) -> bool:
    return getattr(design, "designType", None) == 1


def _iter_parameters_in_component(design, component):
    for sketch in component.sketches:
        for dimension in sketch.sketchDimensions:
            parameter = getattr(dimension, "parameter", None)
            if parameter is not None:
                yield parameter, "sketch_dimension"

        index = 0
        for sketch_text in sketch.sketchTexts:
            yield GenericParameter(f"{sketch.name}-{index}", sketch_text, "text", "sketch_text"), "sketch_text"
            index += 1

    for joint in component.joints:
        joint_motion = getattr(joint, "jointMotion", None)
        if not joint_motion:
            continue

        if getattr(joint_motion, "jointType", None) == 0:
            continue

        for prop in [x for x in dir(joint_motion) if not x.startswith("_") and x.endswith("Value")]:
            name = f"{joint.name}-{prop[:-5]}"
            yield GenericParameter(name, joint_motion, prop, "joint_motion"), "joint_motion"

    if _is_parametric(design):
        for parameter in component.modelParameters:
            yield parameter, "model"


def _iter_parameters(design):
    if _is_parametric(design):
        for parameter in design.userParameters:
            yield parameter, "user"

    for parameter, category in _iter_parameters_in_component(design, design.rootComponent):
        yield parameter, category

    for occurrence in design.rootComponent.allOccurrences:
        for parameter, category in _iter_parameters_in_component(design, occurrence.component):
            yield parameter, category


def handle(query: dict, app, adsk) -> dict:
    design = app.activeProduct
    if not design:
        raise Exception("No active product")

    name = query.get("name")
    expression = query.get("expression")
    allow_multiple = _parse_bool(query, "allow_multiple", False)

    if not isinstance(name, str) or not name.strip():
        raise Exception("'name' is required and must be a non-empty string")
    if not isinstance(expression, str) or not expression.strip():
        raise Exception("'expression' is required and must be a non-empty string")

    target_name = name.strip()
    target_expression = expression.strip()

    matched = []
    for parameter, category in _iter_parameters(design):
        if parameter is None:
            continue
        if getattr(parameter, "name", None) == target_name:
            matched.append((parameter, category))

    if not matched:
        raise Exception(f"Parameter '{target_name}' not found")

    if len(matched) > 1 and not allow_multiple:
        raise Exception(
            f"Parameter name '{target_name}' is ambiguous ({len(matched)} matches). "
            "Set 'allow_multiple' to true to update all matches."
        )

    updated = []
    targets = matched if allow_multiple else [matched[0]]
    for parameter, category in targets:
        before = getattr(parameter, "expression", None)
        parameter.expression = target_expression
        after = getattr(parameter, "expression", None)
        updated.append({
            "name": target_name,
            "category": category,
            "before": before,
            "after": after,
            "type": type(parameter).__name__,
        })

    return {
        "updated": len(updated),
        "items": updated,
    }


if __name__ == "__main__":
    from _client_ import test

    test(
        __file__,
        {
            "name": "d1",
            "expression": "20 mm",
        },
        timeout=30,
    )
