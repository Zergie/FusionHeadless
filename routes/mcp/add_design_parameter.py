"""Add a user parameter to the active Fusion 360 design.

Creates parameters through the design's userParameters collection using
name, expression, units, and optional comment.
"""


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique user parameter name to create."
            },
            "expression": {
                "type": "string",
                "description": "Parameter expression, for example `10 mm` or `2 * pi rad`."
            },
            "units": {
                "type": "string",
                "description": "Units token accepted by Fusion, for example `mm` or `rad`."
            },
            "comment": {
                "type": "string",
                "description": "Optional parameter comment."
            }
        },
        "required": ["name", "expression", "units"]
    }


def _is_parametric(design) -> bool:
    return getattr(design, "designType", None) == 1


def _get_user_parameter(design, name: str):
    user_parameters = getattr(design, "userParameters", None)
    if not user_parameters:
        return None

    if hasattr(user_parameters, "itemByName"):
        try:
            parameter = user_parameters.itemByName(name)
            if parameter:
                return parameter
        except Exception:
            pass

    if hasattr(user_parameters, "count") and hasattr(user_parameters, "item"):
        for i in range(user_parameters.count):
            parameter = user_parameters.item(i)
            if getattr(parameter, "name", None) == name:
                return parameter

    for parameter in user_parameters:
        if getattr(parameter, "name", None) == name:
            return parameter

    return None


def handle(query: dict, app, adsk) -> dict:
    design = app.activeProduct
    if not design:
        raise Exception("No active product")
    if not _is_parametric(design):
        raise Exception("Active design is not parametric")

    name = query.get("name")
    expression = query.get("expression")
    units = query.get("units")
    comment = query.get("comment", "")

    if not isinstance(name, str) or not name.strip():
        raise Exception("'name' is required and must be a non-empty string")
    if not isinstance(expression, str) or not expression.strip():
        raise Exception("'expression' is required and must be a non-empty string")
    if not isinstance(units, str) or not units.strip():
        raise Exception("'units' is required and must be a non-empty string")
    if not isinstance(comment, str):
        raise Exception("'comment' must be a string when provided")

    name = name.strip()
    expression = expression.strip()
    units = units.strip()

    if _get_user_parameter(design, name):
        raise Exception(f"User parameter '{name}' already exists")

    user_parameters = design.userParameters
    value_input = adsk.core.ValueInput.createByString(expression)
    created = user_parameters.add(name, value_input, units, comment)
    if not created:
        raise Exception(f"Failed to create user parameter '{name}'")

    return {
        "created": True,
        "parameter": {
            "name": getattr(created, "name", name),
            "expression": getattr(created, "expression", expression),
            "comment": getattr(created, "comment", comment),
            "unit": getattr(created, "unit", units),
            "type": type(created).__name__,
        },
    }


if __name__ == "__main__":
    from _client_ import test

    test(
        __file__,
        {
            "name": "mcp_demo_param",
            "expression": "10 mm",
            "units": "mm",
            "comment": "Created from MCP tool test",
        },
        timeout=30,
    )
