"""Fusion UI-thread host for the adapter's process boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Callable
import uuid


@dataclass
class _PendingDispatch:
    callback: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    complete: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    cancelled: bool = False


class FusionHost:
    """Run adapter callbacks on Fusion's UI thread through a custom event."""

    EVENT_ID = "FusionHeadless.ExecOnUiThread"

    def __init__(self, app: Any, adsk: Any, *, event_id: str = EVENT_ID) -> None:
        self._app = app
        self._adsk = adsk
        self._event_id = event_id
        self._event: Any = None
        self._handler: Any = None
        self._pending: dict[str, _PendingDispatch] = {}
        self._lock = threading.RLock()
        self._closed = False

    def start(self) -> None:
        """Register and retain the custom event handler once per host."""
        with self._lock:
            if self._event is not None:
                return
            self._closed = False
            host = self

            class DispatchHandler(self._adsk.core.CustomEventHandler):
                def notify(self, event_args: Any) -> None:
                    host._notify(getattr(event_args, "additionalInfo", ""))

            self._event = self._app.registerCustomEvent(self._event_id)
            self._handler = DispatchHandler()
            self._event.add(self._handler)

    def context(self) -> dict[str, Any]:
        """Return a fresh view of the live Fusion application context."""
        return {
            "app": self._app,
            "ui": self._app.userInterface,
            "adsk": self._adsk,
        }

    def dispatch(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Synchronously execute one callback through Fusion's UI event loop."""
        request_id = uuid.uuid4().hex
        pending = _PendingDispatch(callback, args, kwargs)
        with self._lock:
            if self._event is None or self._closed:
                raise RuntimeError("FusionHeadless UI dispatcher is not running")
            self._pending[request_id] = pending
        try:
            self._app.fireCustomEvent(self._event_id, request_id)
        except BaseException:
            with self._lock:
                self._pending.pop(request_id, None)
            raise
        pending.complete.wait()
        with self._lock:
            self._pending.pop(request_id, None)
        if pending.error is not None:
            raise pending.error
        return pending.result

    def close(self) -> None:
        """Cancel pending work and unregister the retained Fusion event."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            event_registered = self._event is not None
            self._event = None
            self._handler = None
            pending = tuple(self._pending.values())
            for request in pending:
                request.cancelled = True
                request.error = RuntimeError("FusionHeadless is stopping")
                request.complete.set()
        if event_registered:
            unregister = getattr(self._app, "unregisterCustomEvent", None)
            if callable(unregister):
                try:
                    unregister(self._event_id)
                except Exception:
                    pass

    def _notify(self, request_id: str) -> None:
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or pending.cancelled:
                return
        try:
            result = pending.callback(*pending.args, **pending.kwargs)
        except BaseException as error:
            with self._lock:
                if not pending.cancelled:
                    pending.error = error
                pending.complete.set()
        else:
            with self._lock:
                if not pending.cancelled:
                    pending.result = result
                pending.complete.set()
