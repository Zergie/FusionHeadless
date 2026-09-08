""" bodies helpers and operations for FusionHeadless."""

from __future__ import annotations

import hashlib
from typing import Any
from fusion_support import _value


def _round(value: Any, places: int) -> float:
    result = round(value, places)
    return 0.0 if -10 ** -places < result < 10 ** -places else result


def _uuid_hash(value: str) -> str:
    digest = hashlib.md5(value.encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:]}"


def _array_signature(value: Any, label: str) -> tuple[float, ...]:
    values = _value(value, "asArray")
    if not callable(values):
        return ()
    try:
        return tuple(_round(item, 5) for item in values())
    except Exception as error:
        raise RuntimeError(f"Failed to read {label}: {error}") from error


def _face_appearance_signatures(body: Any) -> list[tuple[Any, ...]]:
    """Bind every face appearance to stable geometric properties for hashing."""
    signatures = []
    body_name = str(_value(body, "name", ""))
    for index, face in enumerate(_value(body, "faces", []) or []):
        geometry = _value(face, "geometry")
        bounding = _value(face, "boundingBox")
        label = f"body {body_name!r} face {index}"
        signatures.append((
            str(_value(_value(face, "appearance"), "name", "")),
            str(_value(geometry, "objectType", "")),
            str(_value(geometry, "surfaceType", "")),
            bool(_value(face, "isParamReversed", False)),
            _array_signature(_value(geometry, "normal"), f"{label} normal"),
            _array_signature(_value(geometry, "origin"), f"{label} origin"),
            _array_signature(_value(bounding, "minPoint"), f"{label} minimum"),
            _array_signature(_value(bounding, "maxPoint"), f"{label} maximum"),
            _round(_value(face, "area", 0), 5),
        ))
    return sorted(signatures, key=repr)


def _body_orientation(body: Any) -> list[tuple[float, ...]]:
    orientations: set[tuple[float, ...]] = set()
    body_name = str(_value(body, "name", ""))
    for index, face in enumerate(_value(body, "faces", []) or []):
        appearance_name = _value(_value(face, "appearance"), "name")
        if not isinstance(appearance_name, str) or "Build Plate" not in appearance_name:
            continue
        normal = _array_signature(
            _value(_value(face, "geometry"), "normal"),
            f"body {body_name!r} face {index} normal",
        )
        if not normal:
            continue
        reversed_normal = bool(_value(face, "isParamReversed", False))
        orientations.add(tuple(
            -value if reversed_normal else value
            for value in normal
        ))
    return list(orientations)


def _body_dict(
    body: Any, *, include_orientation: bool = True, **extra: Any,
) -> dict[str, Any]:
    parent = _value(body, "parentComponent")
    name = str(_value(body, "name", ""))
    parent_id = str(_value(parent, "id", ""))
    identifier = _uuid_hash(f"{name}-{parent_id}")
    physical = _value(body, "physicalProperties")
    center = _value(_value(physical, "centerOfMass"), "asArray")
    center = center() if callable(center) else []
    bounding = _value(body, "boundingBox")
    minimum = _value(_value(bounding, "minPoint"), "asArray")
    maximum = _value(_value(bounding, "maxPoint"), "asArray")
    minimum = minimum() if callable(minimum) else []
    maximum = maximum() if callable(maximum) else []
    appearance = _value(body, "appearance")
    properties = _value(appearance, "appearanceProperties", []) or []
    color = "00000000"
    for prop in properties:
        if _value(prop, "name") == "Color":
            value = _value(prop, "value")
            if value is not None:
                color = "%0.2X%0.2X%0.2XFF" % (
                    _value(value, "red", 0), _value(value, "green", 0),
                    _value(value, "blue", 0),
                )
            break
    result: dict[str, Any] = {
        "id": identifier, "hash": None, "name": name,
        "volume": _round(_value(physical, "volume", 0), 5),
        "mass": _round(_value(physical, "mass", 0), 5),
        "area": _round(_value(physical, "area", 0), 5), "color": color,
        "centerOfMass": [_round(value, 3) for value in center],
        "material": _value(_value(body, "material"), "name"),
        "boundingBox": {"min": [_round(value, 3) for value in minimum],
                         "max": [_round(value, 3) for value in maximum]},
    }
    if include_orientation:
        result["orientation"] = _body_orientation(body)
    hash_input = {
        **{key: value for key, value in result.items() if key != "orientation"},
        "faceAppearances": _face_appearance_signatures(body),
    }
    result["hash"] = _uuid_hash(str(hash_input))
    result.update(extra)
    return result


def _all_bodies(design: Any) -> list[Any]:
    root = _value(design, "rootComponent")
    if root is None:
        raise RuntimeError("Design does not have a rootComponent.")
    result = list(_value(root, "bRepBodies", []) or [])
    for occurrence in _value(root, "allOccurrences", []) or []:
        result.extend(_value(_value(occurrence, "component"), "bRepBodies", []) or [])
    return result


def _all_bodies_and_occurrences(design: Any):
    root = _value(design, "rootComponent")
    for body in _value(root, "bRepBodies", []) or []:
        yield body
    for occurrence in _value(root, "allOccurrences", []) or []:
        for body in _value(_value(occurrence, "component"), "bRepBodies", []) or []:
            yield body
