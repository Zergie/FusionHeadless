"""Own temporary Fusion mutations and files for one operation.

Only built-in dependencies belong here: cleanup runs on Fusion's UI thread.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable
import uuid

from fusion_support import _value


class TemporaryEffects:
    """Snapshot before mutation; attempt every cleanup even after failures."""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._preserved: set[tuple[int, str]] = set()
        self._errors: list[tuple[str, Exception]] = []

    def __enter__(self) -> TemporaryEffects:
        self._stack.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._stack.__exit__(exc_type, exc, traceback)
        if self._errors:
            details = "; ".join(f"{label}: {error}" for label, error in self._errors)
            message = f"Temporary Fusion cleanup failed: {details}"
            if exc is not None:
                message = f"Operation failed: {exc}; {message}"
            raise RuntimeError(message) from (exc if exc is not None else self._errors[0][1])
        return False

    def _attempt_cleanup(self, label: str, action: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        try:
            action(*args, **kwargs)
        except Exception as error:
            self._errors.append((label, error))

    def temporary_file(self, suffix: str) -> str:
        path = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}{suffix}"
        self._stack.callback(self._attempt_cleanup, f"remove temporary file '{path}'",
                             path.unlink, missing_ok=True)
        return str(path)

    def preserve(self, item: Any, attribute: str, *, label: str | None = None) -> None:
        """Remember the first value, even when an operation changes it repeatedly."""
        identity = (id(item), attribute)
        if identity not in self._preserved:
            original = getattr(item, attribute)
            label = label or f"restore {type(item).__name__} '{_value(item, 'name', '')}'.{attribute}"
            self._stack.callback(self._attempt_cleanup, label, setattr, item, attribute, original)
            self._preserved.add(identity)

    def set_attributes(self, changes: Iterable[tuple[Any, str, Any]]) -> None:
        """Capture all affected values before any setter can change other items."""
        changes = list(changes)
        for item, attribute, _ in changes:
            self.preserve(item, attribute)
        for item, attribute, value in changes:
            setattr(item, attribute, value)

    def set_control(self, ui: Any, identity: str, value: Any) -> None:
        """Temporarily change a Fusion list control, including exclusive controls."""
        if value is None:
            return
        command = ui.commandDefinitions.itemById(identity)
        items = _value(_value(command, "controlDefinition"), "listItems")
        if items is None:
            raise RuntimeError(f"Fusion control '{identity}' does not expose list items")
        entries = [items.item(index) for index in range(items.count)]
        if isinstance(value, list):
            if len(value) != len(entries):
                raise ValueError(f"Fusion control '{identity}' requires {len(entries)} selection values")
            changes = [(item, bool(selected)) for item, selected in zip(entries, value)]
        elif isinstance(value, bool):
            changes = [(item, value) for item in entries]
        elif isinstance(value, int):
            if not 0 <= value < len(entries):
                raise ValueError(f"Fusion control '{identity}' selection {value} is outside 0..{len(entries) - 1}")
            changes = [(entries[value], True)]
        else:
            raise ValueError(f"Fusion control '{identity}' requires a boolean, integer, or list")
        # ExitStack unwinds in reverse. Clear originally unselected entries
        # before selecting the original choice, preserving exclusive controls.
        originals = [(index, item, item.isSelected) for index, item in enumerate(entries)]
        for index, item, _ in sorted(originals, key=lambda entry: not entry[2]):
            self.preserve(item, "isSelected", label=f"restore Fusion control '{identity}' item {index}")
        for item, selected in changes:
            item.isSelected = selected
