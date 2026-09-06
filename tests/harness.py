"""Fusion-independent helpers for process-level bridge tests.

The fake deliberately models only the adapter boundary: dispatching onto the
UI thread, application context, and displaying message boxes.  It is not a
Fusion API emulator.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from bridge import FramedConnection


def route_path(endpoint: Callable[..., Any]) -> str:
    """Resolve an HTTP path from its FastAPI-decorated endpoint."""
    from fastapi.routing import APIRoute
    import server

    for route in server.app.routes:
        definition = getattr(route.endpoint, "__fusionheadless_route__", None)
        if (isinstance(route, APIRoute)
                and (route.endpoint is endpoint
                     or getattr(definition, "operation", None) is endpoint
                     or getattr(getattr(definition, "operation", None), "__name__", None)
                     == getattr(endpoint, "__name__", None))):
            return route.path
    raise LookupError(f"No FastAPI route registered for {endpoint.__name__}")


class FakeUserInterface:
    def __init__(self) -> None:
        self.message_boxes: list[str] = []

    def messageBox(self, message: str) -> None:
        self.message_boxes.append(message)


class FakeApplication:
    def __init__(self) -> None:
        self.userInterface = FakeUserInterface()
        self.dispatched: list[Callable[..., Any]] = []


class FakeFusionHost:
    """Synchronous stand-in for the adapter's UI-thread boundary."""

    def __init__(self) -> None:
        self.app = FakeApplication()

    def dispatch(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self.app.dispatched.append(callback)
        return callback(*args, **kwargs)

    def context(self) -> dict[str, Any]:
        return {"app": self.app, "ui": self.app.userInterface, "adsk": None}


class ChildProcessHarness:
    """Launch a real child process connected through the framed protocol."""

    def __init__(self, arguments: list[str], *, cwd: str | Path | None = None) -> None:
        environment = os.environ.copy()
        root = str(Path(__file__).resolve().parents[1])
        environment["PYTHONPATH"] = root + os.pathsep + environment.get("PYTHONPATH", "")
        self.process = subprocess.Popen(
            [sys.executable, *arguments],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd or root,
            env=environment,
        )
        assert self.process.stdin is not None and self.process.stdout is not None
        self.bridge = FramedConnection(self.process.stdout, self.process.stdin)

    @property
    def returncode(self) -> int | None:
        return self.process.poll()

    def write(self, value: Any) -> None:
        self.bridge.write(value)

    def read(self) -> Any:
        return self.bridge.read()

    def close(self) -> int:
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            returncode = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            returncode = self.process.wait(timeout=5)
        for stream in (self.process.stdout, self.process.stderr):
            if stream and not stream.closed:
                stream.close()
        return returncode
