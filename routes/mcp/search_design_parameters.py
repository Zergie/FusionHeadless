"""Search design parameters by name and optional expression matching.

Searches user/model/sketch/joint parameters in the active Fusion design with
plain text or regex matching.
"""

import re


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search text or regex pattern."
            },
            "use_regex": {
                "type": "boolean",
                "description": "Use Python regex matching (case-insensitive). Default false."
            },
            "search_expression": {
                "type": "boolean",
                "description": "Also search within parameter expression text. Default false."
            },
            "include_user": {
                "type": "boolean",
                "description": "Include user parameters. Default true."
            },
            "include_non_user": {
                "type": "boolean",
                "description": "Include model/sketch/joint parameters. Default true."
            }
        },
        "required": ["query"]
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


def _iter_parameters(design, include_user: bool, include_non_user: bool):
    if include_user and _is_parametric(design):
        for parameter in design.userParameters:
            yield parameter, "user"

    if not include_non_user:
        return

    for parameter, category in _iter_parameters_in_component(design, design.rootComponent):
        yield parameter, category

    for occurrence in design.rootComponent.allOccurrences:
        for parameter, category in _iter_parameters_in_component(design, occurrence.component):
            yield parameter, category


def _matches(text: str, pattern: str, use_regex: bool, compiled) -> bool:
    if use_regex:
        return bool(compiled.search(text))
    return pattern.lower() in text.lower()


def handle(query: dict, app, adsk) -> dict:
    design = app.activeProduct
    if not design:
        raise Exception("No active product")

    search_query = query.get("query")
    if not isinstance(search_query, str) or not search_query.strip():
        raise Exception("'query' is required and must be a non-empty string")

    search_query = search_query.strip()
    use_regex = _parse_bool(query, "use_regex", False)
    search_expression = _parse_bool(query, "search_expression", False)
    include_user = _parse_bool(query, "include_user", True)
    include_non_user = _parse_bool(query, "include_non_user", True)

    compiled = None
    if use_regex:
        try:
            compiled = re.compile(search_query, re.IGNORECASE)
        except re.error as exc:
            raise Exception(f"Invalid regex pattern '{search_query}': {exc}")

    matches = []
    for parameter, category in _iter_parameters(design, include_user, include_non_user):
        if parameter is None:
            continue

        name = getattr(parameter, "name", None)
        expression = getattr(parameter, "expression", None)
        if not isinstance(name, str):
            continue

        matched_field = None
        if _matches(name, search_query, use_regex, compiled):
            matched_field = "name"
        elif search_expression and isinstance(expression, str) and _matches(expression, search_query, use_regex, compiled):
            matched_field = "expression"

        if matched_field:
            matches.append({
                "name": name,
                "expression": expression,
                "category": category,
                "type": type(parameter).__name__,
                "matched_field": matched_field,
                "is_deletable": bool(category == "user"),
            })

    matches = sorted(matches, key=lambda x: (x["name"].lower(), x["category"].lower()))

    return {
        "count": len(matches),
        "query": search_query,
        "use_regex": use_regex,
        "search_expression": search_expression,
        "matches": matches,
    }


if __name__ == "__main__":
    from _client_ import test

    test(__file__, {"query": "d"}, timeout=30)
