"""Eval helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Annotated, Any
from routing import ApiParameter, api_route


def _eval_attribute(value: Any, attribute: str) -> Any:
    if attribute in ("this", "objectType"):
        return None
    try:
        return getattr(value, attribute)
    except Exception:
        return None


def _eval_sort_attribute(attribute: str) -> str:
    order = {"id": 0, "name": 1, "description": 2}
    return f"{order.get(attribute, 3):02d}_{attribute}"


def _eval_to_json(value: Any, max_depth: int, depth: int = 0) -> Any:
    if type(value).__name__ in ("method", "function", "NoneType") or value is None:
        result = None
    elif isinstance(value, (int, float, str, bool)):
        result = value
    elif isinstance(value, (list, tuple)):
        result = ([_eval_to_json(item, max_depth, depth + 1) for item in value]
                  if depth < max_depth else [])
    elif isinstance(value, dict):
        result = ({key: _eval_to_json(item, max_depth, depth + 1)
                   for key, item in value.items()} if depth < max_depth else {})
    elif hasattr(value, "asArray") and callable(value.asArray):
        result = ([_eval_to_json(item, max_depth, depth + 1) for item in value.asArray()]
                  if depth < max_depth else [])
    elif hasattr(value, "asDict") and callable(value.asDict):
        result = ({key: _eval_to_json(item, max_depth, depth + 1)
                   for key, item in value.asDict().items()} if depth < max_depth else {})
    elif hasattr(value, "__iter__") and callable(value.__iter__):
        result = ({key: _eval_to_json(item, max_depth, depth + 1) for key, item in value}
                  if depth < max_depth else {})
    else:
        result = ({key: _eval_to_json(_eval_attribute(value, key), max_depth, depth + 1)
                   for key in sorted(dir(value), key=_eval_sort_attribute)
                   if not key.startswith("_")} if depth < max_depth else {})

    if isinstance(type(value), type) and type(value).__module__ == "builtins":
        return result
    elif isinstance(result, (list, tuple)):
        return {"items": [item for item in result if item is not None],
                "objectType": f"https://help.autodesk.com/view/fusion360/ENU/?cg=Developer%27s%20Documentation&query={type(value).__name__}%20Object"}
    elif isinstance(result, dict):
        result["objectType"] = f"https://help.autodesk.com/view/fusion360/ENU/?cg=Developer%27s%20Documentation&query={type(value).__name__}%20Object"
        return {key: item for key, item in result.items() if item is not None}
    else:
        return result


@api_route("/eval", methods=("POST",))
def fusion_eval(
    context: Any,
    code: Annotated[str, ApiParameter("Python expression to evaluate in Fusion.")],
    depth: Annotated[
        int | None,
        ApiParameter("Optional depth for serializing Fusion objects."),
    ] = None,
) -> Any:
    app, ui, adsk = context.app, context.ui, context.adsk
    namespace = {"__builtins__": __builtins__, "app": app, "ui": ui, "adsk": adsk}
    result = eval(code, namespace)
    if depth is not None:
        result = _eval_to_json(result, int(depth))
    return result
