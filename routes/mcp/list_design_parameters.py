"""List design parameters from the active Fusion 360 design.

Includes user parameters and discovered model/sketch/joint parameters. Results are
grouped by name with occurrence counts.
"""


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "include_user": {
                "type": "boolean",
                "description": "Include user parameters. Default true."
            },
            "include_non_user": {
                "type": "boolean",
                "description": "Include model/sketch/joint parameters. Default true."
            }
        }
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


def _to_entry(parameter, category: str) -> dict:
    name = getattr(parameter, "name", None)
    expression = getattr(parameter, "expression", None)

    return {
        "name": name,
        "expression": expression,
        "category": category,
        "type": type(parameter).__name__,
        "is_deletable": bool(category == "user"),
    }


def handle(query: dict, app, adsk) -> dict:
    design = app.activeProduct
    if not design:
        raise Exception("No active product")

    include_user = _parse_bool(query, "include_user", True)
    include_non_user = _parse_bool(query, "include_non_user", True)

    grouped = {}
    for parameter, category in _iter_parameters(design, include_user, include_non_user):
        if parameter is None:
            continue

        entry = _to_entry(parameter, category)
        name = entry["name"]
        if not name:
            continue

        if name not in grouped:
            grouped[name] = {
                "name": name,
                "expression": entry["expression"],
                "count": 0,
                "categories": set(),
                "types": set(),
                "is_deletable": False,
            }

        grouped[name]["count"] += 1
        grouped[name]["categories"].add(entry["category"])
        grouped[name]["types"].add(entry["type"])
        grouped[name]["is_deletable"] = grouped[name]["is_deletable"] or entry["is_deletable"]

    items = []
    for name in sorted(grouped, key=str.lower):
        item = grouped[name]
        items.append({
            "name": item["name"],
            "expression": item["expression"],
            "count": item["count"],
            "categories": sorted(item["categories"]),
            "types": sorted(item["types"]),
            "is_deletable": item["is_deletable"],
        })

    return {
        "count": len(items),
        "include_user": include_user,
        "include_non_user": include_non_user,
        "parameters": items,
    }


if __name__ == "__main__":
    from _client_ import test

    test(__file__, {}, timeout=30)
