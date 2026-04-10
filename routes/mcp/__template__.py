"""Template for new MCP tools.

Copy this file to create a new tool:
    cp __template__.py your_tool_name.py

Then:
1. Write a module-level docstring — it becomes the tool description (whitespace-normalized).
2. Implement get_input_schema() returning the full inputSchema object.
3. Implement the handle() function.
4. Test locally: python your_tool_name.py
5. Reload via /reload endpoint or restart Fusion

Tool name is derived from the filename stem (e.g. your_tool_name.py -> "your_tool_name").
Tool description is derived from the full module docstring with whitespace normalized.
Files starting with '_' are never considered tools.
"""


def get_input_schema() -> dict:
    """Return the full MCP inputSchema for this tool.

    Must return a dict with "type": "object". Include "required" directly
    in this dict for required parameters.
    """
    return {
        "type": "object",
        "properties": {
            # "param_name": {"type": "string", "description": "..."}
        },
        "required": []
    }


def handle(query: dict, app, adsk) -> any:
    """Tool handler function.

    Args:
        query: Tool parameters from HTTP request
        app: Fusion application instance
        adsk: Fusion API module

    Returns:
        Native Python object (auto JSON-serialized by server).
        Can be dict, list, str, int, float, bool, or BinaryResponse for binary data.

    Raises:
        Exception: For validation errors or tool execution failures
    """
    # Implement your tool logic here
    result = {"status": "ok", "message": "Tool executed successfully"}
    return result

if __name__ == "__main__":
    from _client_ import test
    test(__file__, {}, timeout=30)
