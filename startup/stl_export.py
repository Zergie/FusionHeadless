"""Lifecycle and process-boundary declarations for Export STL."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from context import fusion, server
from startup.stl_export_contract import BodySelection


_orchestrator: Any = None
_command: Any = None


def install(runtime: Any, origin: str, owner_token: str) -> bool:
    """Let this child own orchestration, then install its Fusion UI adapter."""
    global _orchestrator
    from startup.stl_export_job import StlExportOrchestrator

    def finished(preferences: dict[str, str], count: int, error: str | None) -> Any:
        return runtime.invoke_fusion(
            finish_stl_export,
            {
                "owner_token": owner_token,
                "preferences": preferences,
                "count": count,
                "error": error,
            },
        )

    orchestrator = StlExportOrchestrator(origin, owner_token, finished)
    _orchestrator = orchestrator
    try:
        result = runtime.invoke_fusion(install_stl_export, {"owner_token": owner_token})
    except Exception:
        orchestrator.close()
        if _orchestrator is orchestrator:
            _orchestrator = None
        raise
    if not result.get("installed", False):
        orchestrator.close()
        if _orchestrator is orchestrator:
            _orchestrator = None
        return False
    return True


def uninstall(runtime: Any, owner_token: str) -> None:
    """Cancel child work and remove only the UI owned by this child."""
    global _orchestrator
    orchestrator = _orchestrator
    if orchestrator is not None and orchestrator.owner_token == owner_token:
        orchestrator.close()
        _orchestrator = None
    runtime.invoke_fusion(uninstall_stl_export, {"owner_token": owner_token})


def cancel(owner_token: str) -> None:
    """Cancel work owned by a retiring child without touching Fusion UI."""
    global _orchestrator
    if _orchestrator is not None and _orchestrator.owner_token == owner_token:
        _orchestrator.close()
        _orchestrator = None


@server
def enqueue_stl_export(
    bodies: list[dict[str, str | None]], preferences: dict[str, str],
    paths: list[str], owner_token: str,
) -> dict[str, bool]:
    """Accept a UI request quickly so Fusion can release its UI thread."""
    orchestrator = _orchestrator
    if orchestrator is None or orchestrator.owner_token != owner_token:
        raise RuntimeError("Export STL is not owned by the active child")
    selections = [BodySelection(
        item.get("component"),
        str(item["name"]),
        item.get("document"),
        item.get("entity_token"),
    ) for item in bodies]
    orchestrator.enqueue(selections, dict(preferences), [Path(path) for path in paths])
    return {"queued": True}


@fusion
def install_stl_export(context: Any, owner_token: str) -> dict[str, bool]:
    """Install the retained Fusion UI adapter for the active child."""
    global _command
    if getattr(context.ui, "workspaces", None) is None:
        return {"installed": False}
    from startup.stl_export_ui import StlExportCommand

    if _command is not None:
        if _command.owner_token == owner_token:
            return {"installed": True}
        _command.close()
    command = StlExportCommand(
        context,
        owner_token,
        context.bind_server(enqueue_stl_export),
    )
    try:
        command.start()
    except Exception:
        command.close()
        raise
    _command = command
    return {"installed": True}


@fusion
def finish_stl_export(
    context: Any, owner_token: str, preferences: dict[str, str], count: int,
    error: str | None = None,
) -> None:
    """Complete one child-owned export on Fusion's UI thread."""
    if _command is not None and _command.owner_token == owner_token:
        _command.finished(preferences, count, error)


@fusion
def uninstall_stl_export(context: Any, owner_token: str) -> None:
    """Remove the command only when it still belongs to this child."""
    global _command
    if _command is not None and _command.owner_token == owner_token:
        _command.close()
        _command = None


def close_fusion_ui() -> None:
    """Remove retained UI before this Fusion-side module is unloaded."""
    global _command
    if _command is not None:
        _command.close()
        _command = None
