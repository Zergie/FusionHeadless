"""Fusion 360 add-in entry point for FusionHeadless."""

from __future__ import annotations

from pathlib import Path
import sys
from threading import RLock, Thread
from typing import Any

import adsk.core
import adsk.fusion


_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from adapter import FusionAdapter
from fusion_host import FusionHost


_lock = RLock()
_adapter: FusionAdapter | None = None
_host: FusionHost | None = None


def run(context: Any) -> None:
    """Start the adapter without blocking Fusion's add-in startup callback."""
    global _adapter, _host
    with _lock:
        if _adapter is not None:
            return
        app = adsk.core.Application.get()
        host = FusionHost(app, adsk)
        host.start()
        adapter = FusionAdapter(host=host)
        _host = host
        _adapter = adapter
        Thread(target=_start_adapter, args=(adapter, host), daemon=True).start()


def stop(context: Any) -> None:
    """Stop the child adapter and release Fusion event resources."""
    global _adapter, _host
    with _lock:
        adapter = _adapter
        host = _host
        _adapter = None
        _host = None
    try:
        if adapter is not None:
            adapter.stop_from_ui_thread()
    finally:
        if host is not None:
            host.close()


def _start_adapter(adapter: FusionAdapter, host: FusionHost) -> None:
    try:
        started = adapter.start()
    except Exception:
        started = False
    if not started:
        _show_setup_guidance(host)


def _show_setup_guidance(host: FusionHost) -> None:
    try:
        host.dispatch(
            lambda: host.context()["ui"].messageBox(
                "FusionHeadless setup is incomplete. Complete setup and see README.md."
            )
        )
    except Exception:
        pass
