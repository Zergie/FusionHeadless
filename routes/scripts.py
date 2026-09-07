"""Scripts helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Annotated, Any
from routing import ApiParameter, api_route
from fusion_support import _value


def _scripts(app: Any) -> dict[str, Any]:
    """Return Fusion scripts and add-ins indexed by their unique Script IDs."""
    scripts = _value(app, "scripts")
    item = _value(scripts, "item")
    count = _value(scripts, "count", 0)
    if not callable(item) or not isinstance(count, int):
        return {}
    return {
        str(_value(script, "id")): script
        for index in range(count)
        if (script := item(index)) is not None
    }


def _programming_language(value: Any) -> str:
    """Return Fusion's programming-language enum as a readable name."""
    return {
        0: "Prompt",
        1: "Python",
        2: "C++",
        3: "TypeScript",
    }.get(value, str(value))


def _script_details(scripts: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize Fusion scripts consistently after listing or changing them."""
    result = [
        {
            "id": _value(addin, "id"),
            "name": _value(addin, "name"),
            "author": _value(addin, "author"),
            "description": _value(addin, "description"),
            "folder": _value(addin, "folder"),
            "programmingLanguage": _programming_language(
                _value(addin, "programmingLanguage")
            ),
            "enabled": bool(_value(addin, "isRunOnStartup", False)),
            "running": bool(_value(addin, "isRunning", False)),
        }
        for addin in scripts.values()
    ]
    result.sort(key=lambda addin: (str(addin["name"]).lower(), str(addin["id"])))
    return result


@api_route("/scripts", methods=("GET", "POST"))
def scripts_route(
    context: Any,
    enable: Annotated[
        list[str] | None,
        ApiParameter("Add-in Script IDs to enable and start."),
    ] = None,
    disable: Annotated[
        list[str] | None,
        ApiParameter("Add-in Script IDs to stop and disable at startup."),
    ] = None,
) -> dict[str, list[dict[str, Any]]]:
    """List Fusion scripts and add-ins, or change add-ins in batches."""
    enable_ids = enable or []
    disable_ids = disable or []
    conflicting_ids = sorted(set(enable_ids) & set(disable_ids))
    if conflicting_ids:
        raise ValueError(
            "An add-in cannot be both enabled and disabled: "
            + ", ".join(repr(identifier) for identifier in conflicting_ids)
        )

    scripts = _scripts(context.app)
    addins = {
        identifier: script
        for identifier, script in scripts.items()
        if _value(script, "isAddIn", False)
    }
    requested_ids = [*enable_ids, *disable_ids]
    unknown_ids = sorted({identifier for identifier in requested_ids if identifier not in addins})
    if unknown_ids:
        raise ValueError(
            "Unknown add-in Script ID: "
            + ", ".join(repr(identifier) for identifier in unknown_ids)
        )

    for identifier in enable_ids:
        addin = addins[identifier]
        addin.isRunOnStartup = True
        if not _value(addin, "isRunning", False) and not addin.run(False):
            raise RuntimeError(f"Failed to start add-in {identifier!r}.")
    for identifier in disable_ids:
        addin = addins[identifier]
        addin.isRunOnStartup = False
        if _value(addin, "isRunning", False) and not addin.stop():
            raise RuntimeError(f"Failed to stop add-in {identifier!r}.")
    return {
        "scripts": _script_details({
            identifier: script
            for identifier, script in scripts.items()
            if not _value(script, "isAddIn", False)
        }),
        "addons": _script_details(addins),
    }
