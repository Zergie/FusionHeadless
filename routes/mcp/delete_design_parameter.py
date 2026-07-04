"""Delete a user parameter from the active Fusion 360 design.

Only user parameters can be deleted through Fusion's API. Model/sketch/joint
parameters are derived from geometry and cannot be removed directly.
"""


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact user-parameter name to delete."
            }
        },
        "required": ["name"]
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
    if not isinstance(name, str) or not name.strip():
        raise Exception("'name' is required and must be a non-empty string")

    name = name.strip()
    parameter = _get_user_parameter(design, name)
    if not parameter:
        raise Exception(f"User parameter '{name}' not found")

    parameter.deleteMe()
    return {
        "deleted": True,
        "name": name,
    }


if __name__ == "__main__":
    from _client_ import test

    test(__file__, {"name": "mcp_demo_param"}, timeout=30)
