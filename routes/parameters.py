"""Parameters helpers and operations for FusionHeadless."""

from __future__ import annotations

import re
from typing import Annotated, Any
from routing import ApiParameter, api_route
from fusion_support import _value


class GenericParameter:
    """Adapter for Fusion properties that expose parameter-like values."""

    def __init__(self, name: str, parent: Any, prop: str) -> None:
        self.name = name
        self.parent = parent
        self.property = prop

    @property
    def expression(self) -> Any:
        return getattr(self.parent, self.property)

    @expression.setter
    def expression(self, value: Any) -> None:
        prop_type = type(self.expression)
        if isinstance(value, str):
            if prop_type is bool:
                value = value.lower() in ("true", "1", "yes", "on")
            elif prop_type is int:
                value = int(value)
            elif prop_type is float:
                value = float(value)
            elif prop_type is not str:
                try:
                    value = prop_type(value)
                except Exception:
                    pass
        try:
            limits = getattr(self.parent, f"{self.property[:-5]}Limits", None)
            if limits is not None and limits.minimumValue != limits.maximumValue:
                value = max(limits.minimumValue, min(limits.maximumValue, value))
        except Exception:
            pass
        setattr(self.parent, self.property, value)


def _iter_parameters_in_component(design: Any, component: Any):
    for sketch in _value(component, "sketches", []) or []:
        for dimension in _value(sketch, "sketchDimensions", []) or []:
            yield _value(dimension, "parameter")
        for index, text in enumerate(_value(sketch, "sketchTexts", []) or []):
            yield GenericParameter(f"{_value(sketch, 'name', '')}-{index}", text, "text")
    for joint in _value(component, "joints", []) or []:
        motion = _value(joint, "jointMotion")
        if _value(motion, "jointType") == 0:
            continue
        for prop in sorted(name for name in dir(motion)
                           if not name.startswith("_") and name.endswith("Value")):
            yield GenericParameter(f"{_value(joint, 'name', '')}-{prop[:-5]}", motion, prop)
    if _value(design, "designType") == 1:
        yield from (_value(component, "modelParameters", []) or [])


def _iter_parameters(design: Any):
    if _value(design, "designType") == 1:
        yield from (_value(design, "userParameters", []) or [])
    yield from _iter_parameters_in_component(design, _value(design, "rootComponent"))
    for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
        yield from _iter_parameters_in_component(design, _value(occurrence, "component"))


def _parameter_sort(item: tuple[str, Any]) -> tuple[Any, ...]:
    match = re.match(r"^d(\d+)", item[0])
    if match:
        return (2, int(match.group(1)))
    elif match := re.match(r"^([^\d]+)(\d+)", item[0]):
        return (1, match.group(1), int(match.group(2)))
    else:
        return (0, item[0].lower())


@api_route("/parameter", methods=("GET", "POST"))
def parameter_route(
    context: Any,
    set: Annotated[
        list[str] | None,
        ApiParameter("Repeated NAME=EXPRESSION design-parameter updates."),
    ] = None,
) -> dict[str, Any]:
    """List or update design parameters on Fusion's UI thread."""
    app = context.app
    design = _value(app, "activeProduct")
    updates: dict[str, str] = {}
    if set is not None:
        if not set:
            raise ValueError("'set' must contain at least one NAME=EXPRESSION value")
        for assignment in set:
            if "=" not in assignment:
                raise ValueError(
                    f"Invalid parameter update '{assignment}'; expected NAME=EXPRESSION"
                )
            name, expression = assignment.split("=", 1)
            name = name.strip()
            if not name:
                raise ValueError(
                    f"Invalid parameter update '{assignment}'; name must not be empty"
                )
            updates[name] = expression
    requested = list(updates)
    result: dict[str, Any] = {}
    for parameter in _iter_parameters(design):
        if parameter is None:
            continue
        if not requested:
            result[parameter.name] = parameter.expression
        elif parameter.name in requested:
            requested.remove(parameter.name)
            parameter.expression = updates[parameter.name]
            result[parameter.name] = parameter.expression
        if requested == [] and updates:
            break
    for name in requested:
        result[name] = f"Parameter '{name}' not found."
    return dict(sorted(result.items(), key=_parameter_sort))
