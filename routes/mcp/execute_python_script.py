"""Execute Python scripts inside Fusion 360's UI-thread context.

Use this when you need to run short automation scripts that interact with Fusion's
`app` and `adsk` objects. For API discovery and symbol details, use the
`get_api_documentation` MCP tool.
"""

import traceback


MAX_DEPTH = 8
DEFAULT_DEPTH = 2


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python script to execute. Use `result = ...` in your script "
                    "to return a value."
                )
            },
            "depth": {
                "type": "integer",
                "description": (
                    "Optional serialization depth for the returned result. "
                    f"Range: 0-{MAX_DEPTH}. Defaults to {DEFAULT_DEPTH}."
                )
            },
            "result_variable": {
                "type": "string",
                "description": (
                    "Variable name to read after execution as the tool result. "
                    "Defaults to `result`."
                )
            }
        },
        "required": ["code"]
    }


def _parse_depth(query: dict) -> int:
    depth = query.get("depth", DEFAULT_DEPTH)

    if isinstance(depth, bool):
        raise Exception("'depth' must be an integer")

    if isinstance(depth, str):
        depth = depth.strip()
        if not depth:
            depth = DEFAULT_DEPTH
        elif depth.isdigit() or (depth.startswith("-") and depth[1:].isdigit()):
            depth = int(depth)
        else:
            raise Exception("'depth' must be an integer")

    if not isinstance(depth, int):
        raise Exception("'depth' must be an integer")

    if depth < 0 or depth > MAX_DEPTH:
        raise Exception(f"'depth' must be between 0 and {MAX_DEPTH}")

    return depth


def handle(query: dict, app, adsk) -> dict:
    code = query.get("code")
    if not isinstance(code, str) or not code.strip():
        raise Exception("'code' is required and must be a non-empty string")

    result_variable = query.get("result_variable", "result")
    if not isinstance(result_variable, str) or not result_variable.strip():
        raise Exception("'result_variable' must be a non-empty string when provided")

    depth = _parse_depth(query)

    context = {
        "app": app,
        "adsk": adsk,
        "__builtins__": __builtins__,
    }

    try:
        exec(code, context)
        result = context.get(result_variable.strip(), None)
        object2json = __import__("server").object2json

        return {
            "error": False,
            "message": "Script executed successfully",
            "result_variable": result_variable.strip(),
            "depth": depth,
            "result": object2json(result, max_depth=depth),
        }
    except Exception as exc:
        return {
            "error": True,
            "message": "Script execution failed",
            "details": str(exc),
            "traceback": traceback.format_exc(),
        }


if __name__ == "__main__":
    from _client_ import test

    test(
        __file__,
        {
            "code": "result = app.activeDocument.name if app.activeDocument else None",
            "depth": 2,
        },
        timeout=30,
    )
