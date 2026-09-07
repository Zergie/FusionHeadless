"""Select helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Annotated, Any
from routing import ApiParameter, api_route
from fusion_support import _value


def _find_occurrence(identity: Any, design: Any) -> Any:
    identities = [identity] if isinstance(identity, str) else identity
    for item in identities or []:
        for occurrence in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
            component = _value(occurrence, "component")
            if _value(component, "name") == item or _value(component, "id") == item:
                return occurrence
    return None


def _assembly_contexts(occurrence: Any) -> list[Any]:
    contexts: list[Any] = []
    context = _value(occurrence, "assemblyContext")
    while context is not None:
        contexts.append(context)
        context = _value(context, "assemblyContext")
    contexts.reverse()
    return contexts


@api_route("/select", methods=("POST",))
def select_route(
    context: Any,
    id: Annotated[
        str | list[str] | None,
        ApiParameter("Component identifier to select."),
    ] = None,
    name: Annotated[
        str | list[str] | None,
        ApiParameter("Component name to select."),
    ] = None,
    focus: Annotated[
        bool,
        ApiParameter("Bring the Fusion window to the foreground on Windows."),
    ] = True,
) -> dict[str, Any]:
    """Select and isolate a component occurrence on Fusion's UI thread."""
    app, ui = context.app, context.ui
    design = _value(app, "activeProduct")
    identity = id if id is not None else name
    occurrence = _find_occurrence(identity, design)
    if occurrence is None:
        raise RuntimeError(f"Occurrence with id or name '{identity}' not found.")
    contexts = _assembly_contexts(occurrence)
    if contexts:
        for context in contexts:
            context.isLightBulbOn = True
            context.isIsolated = True
        context_ids = {_value(_value(context, "component"), "id") for context in contexts}
        for context in contexts:
            for item in _value(context, "childOccurrences", []) or []:
                if (_value(item, "isVisible", True)
                        and _value(_value(item, "component"), "id") != _value(_value(occurrence, "component"), "id")
                        and _value(_value(item, "component"), "id") not in context_ids):
                    item.isLightBulbOn = False
    else:
        occurrence.isIsolated = True
    if not contexts and not _value(occurrence, "isVisible", True):
        for item in _value(_value(design, "rootComponent"), "allOccurrences", []) or []:
            item.isLightBulbOn = False
        occurrence.isLightBulbOn = True
        _value(occurrence, "component").isLightBulbOn = True
    selections = _value(ui, "activeSelections")
    selections.clear()
    selections.add(occurrence)
    command = _value(_value(ui, "commandDefinitions"), "itemById")("FindInBrowser")
    _value(command, "execute")()
    selections.clear()
    viewport = _value(app, "activeViewport")
    _value(viewport, "goHome")()
    _value(viewport, "fit")()
    if focus:
        try:
            import win32gui  # type: ignore
            windows: list[tuple[Any, str]] = []
            win32gui.EnumWindows(
                lambda hwnd, _: windows.append((hwnd, win32gui.GetWindowText(hwnd)))
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd)
                and "Fusion" in win32gui.GetWindowText(hwnd) else None,
                None,
            )
            if windows:
                hwnd, _ = sorted(windows, key=lambda item: len(item[1]))[-1]
                win32gui.ShowWindow(hwnd, 6)
                win32gui.ShowWindow(hwnd, 9)
        except Exception:
            pass
    return {"id": _value(_value(occurrence, "component"), "id"),
            "name": _value(_value(occurrence, "component"), "name")}
