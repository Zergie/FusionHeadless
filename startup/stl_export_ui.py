"""Fusion-only UI adapter for the child-owned Export STL feature."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event
from typing import Any, Callable

from startup.stl_export_contract import APPLICATIONS, BodySelection


COMMAND_ID = "FusionHeadlessExportSTL"


class StlExportCommand:
    """Collect native input and submit one complete job to the child."""

    def __init__(
        self, context: Any, owner_token: str,
        enqueue: Callable[..., Any], *, settings_path: Path | None = None,
    ) -> None:
        self.context = context
        self.ui, self.adsk = context.ui, context.adsk
        self.owner_token = owner_token
        self.enqueue = enqueue
        self.settings_path = settings_path or (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            / "FusionHeadless" / "stl-export.json"
        )
        self.preferences: dict[str, str] = {}
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.preferences = {
                    key: value for key, value in saved.items() if isinstance(value, str)
                }
        except (OSError, ValueError):
            pass
        self.cancelled = Event()
        self.definition: Any = None
        self.control: Any = None
        self.handlers: list[tuple[Any, Any]] = []
        self.dialogs: list[_Dialog] = []

    def connect(
        self, event: Any, event_type: Any, callback: Callable[..., Any],
        handlers: list[tuple[Any, Any]],
    ) -> None:
        owner = self

        class Handler(event_type):
            def notify(self, args: Any) -> None:
                if owner.cancelled.is_set():
                    return
                try:
                    callback(args)
                except Exception as error:
                    owner.ui.messageBox(f"STL export failed: {error}")

        handler = Handler()
        event.add(handler)
        handlers.append((event, handler))

    def start(self) -> None:
        if self.definition is not None:
            return
        workspace = self.ui.workspaces.itemById("FusionSolidEnvironment")
        panel = workspace.toolbarPanels.itemById("SolidScriptsAddinsPanel") if workspace else None
        if panel is None:
            raise RuntimeError("Fusion Design Utilities / Add-Ins panel is unavailable")
        self.definition = self.ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID,
            "Export STL",
            "Export selected bodies to STL, Cura, or OrcaSlicer.",
            str(Path(__file__).resolve().parents[1] / "resources" / "export-stl"),
        )
        self.connect(
            self.definition.commandCreated,
            self.adsk.core.CommandCreatedEventHandler,
            self._created,
            self.handlers,
        )
        self.control = panel.controls.addCommand(self.definition)
        self.control.isPromotedByDefault = True
        self.control.isPromoted = True

    def _created(self, args: Any) -> None:
        self.dialogs.append(_Dialog(self, args.command))

    def submit(
        self, bodies: list[BodySelection], preferences: dict[str, str], paths: list[Path],
    ) -> None:
        self.definition.controlDefinition.isEnabled = False
        try:
            self.enqueue(
                [{
                    "component": body.component,
                    "name": body.name,
                    "document": body.document,
                    "entity_token": body.entity_token,
                } for body in bodies],
                preferences,
                [str(path) for path in paths],
                self.owner_token,
            )
        except Exception:
            self.definition.controlDefinition.isEnabled = True
            raise

    def finished(
        self, preferences: dict[str, str], count: int, error: str | None,
    ) -> None:
        if self.cancelled.is_set():
            return
        self.definition.controlDefinition.isEnabled = True
        if error is not None:
            self.ui.messageBox(f"STL export failed: {error}")
            return
        self.preferences = preferences
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(preferences), encoding="utf-8")
        self.ui.messageBox(f"Exported {count} STL file(s) to {preferences['application']}.")

    def close(self) -> None:
        self.cancelled.set()
        for dialog in self.dialogs[:]:
            dialog.close()
        for event, handler in self.handlers:
            event.remove(handler)
        self.handlers.clear()
        for item in (self.control, self.definition):
            if item is not None:
                item.deleteMe()
        self.control = self.definition = None


class _Dialog:
    """Translate native selection and dialogs into one child job request."""

    def __init__(self, owner: StlExportCommand, command: Any) -> None:
        self.owner = owner
        self.handlers: list[tuple[Any, Any]] = []
        self.initialized = False
        self.initial_bodies = [
            selection.entity for selection in owner.ui.activeSelections
            if owner.adsk.fusion.BRepBody.cast(selection.entity) is not None
        ]
        inputs, core = command.commandInputs, owner.adsk.core
        self.objects = inputs.addSelectionInput(
            "object", "Object", "Select bodies to export as separate STL files"
        )
        self.objects.addSelectionFilter("Bodies")
        self.objects.setSelectionLimits(1, 0)
        self.objects.isUseCurrentSelections = False
        self.orient = inputs.addDropDownCommandInput(
            "orient", "Orient", core.DropDownStyles.TextListDropDownStyle
        )
        mode = owner.preferences.get("orient", "Original")
        if mode not in ("Original", "Appearance"):
            mode = "Original"
        for name in ("Original", "Appearance"):
            self.orient.listItems.add(name, name == mode)
        self.appearance_note = inputs.addTextBoxCommandInput(
            "appearance_note", "", "Uses 'Build Plate' appearances.", 1, True
        )
        self._sync_appearance_note()
        self.application = inputs.addDropDownCommandInput(
            "application", "Application", core.DropDownStyles.TextListDropDownStyle
        )
        application = owner.preferences.get("application", "Export only")
        for name in APPLICATIONS:
            self.application.listItems.add(name, name == application)
        command.okButtonText = "Export"
        owner.connect(command.activate, core.CommandEventHandler, self.activate, self.handlers)
        owner.connect(
            command.inputChanged,
            core.InputChangedEventHandler,
            self.input_changed,
            self.handlers,
        )
        owner.connect(
            command.validateInputs, core.ValidateInputsEventHandler, self.validate, self.handlers
        )
        owner.connect(command.execute, core.CommandEventHandler, self.execute, self.handlers)
        owner.connect(
            command.destroy,
            core.CommandEventHandler,
            lambda args: self.close(),
            self.handlers,
        )

    def activate(self, args: Any) -> None:
        if not self.initialized:
            self.initialized = True
            for body in self.initial_bodies:
                if body.isValid:
                    self.objects.addSelection(body)
            self.initial_bodies.clear()

    def validate(self, args: Any) -> None:
        args.areInputsValid = (
            self.objects.selectionCount > 0
            and self.orient.selectedItem is not None
            and self.application.selectedItem is not None
        )

    def input_changed(self, args: Any) -> None:
        self._sync_appearance_note()

    def _sync_appearance_note(self) -> None:
        selected = self.orient.selectedItem
        self.appearance_note.isVisible = (
            selected is not None and selected.name == "Appearance"
        )

    def execute(self, args: Any) -> None:
        owner = self.owner
        bodies = []
        document = owner.context.app.activeDocument
        data_file = getattr(document, "dataFile", None)
        document_identity = getattr(data_file, "id", None)
        if not document_identity:
            document_identity = f"name:{getattr(document, 'name', '')}"
        root = owner.context.app.activeProduct.rootComponent
        for index in range(self.objects.selectionCount):
            body = self.objects.selection(index).entity
            if not body.isValid:
                raise ValueError(f"Selected body {index + 1} is no longer available")
            component = body.parentComponent
            if sum(item.name == body.name for item in component.bRepBodies) != 1:
                raise ValueError(
                    f"Body name '{body.name}' is ambiguous in component "
                    f"'{component.name}'. Rename it before exporting."
                )
            entity_token = getattr(body, "entityToken", None)
            if not entity_token:
                raise ValueError(f"Selected body {index + 1} has no stable entity token")
            bodies.append(BodySelection(
                None if component == root else component.id,
                body.name,
                str(document_identity),
                str(entity_token),
            ))
        if not bodies:
            raise ValueError("Select at least one body")
        preferences = {
            "orient": self.orient.selectedItem.name,
            "application": self.application.selectedItem.name,
        }
        paths = []
        if preferences["application"] == "Export only":
            dialog = owner.ui.createFileDialog()
            dialog.title = "Export STL"
            dialog.filter = "STL files (*.stl)"
            dialog.isMultiSelectEnabled = False
            if dialog.showSave() != owner.adsk.core.DialogResults.DialogOK:
                return
            first = Path(dialog.filename).with_suffix(".stl")
            paths = [first] + [
                first.with_name(f"{first.stem}_{index}.stl")
                for index in range(2, len(bodies) + 1)
            ]
            existing = [str(path) for path in paths if path.exists()]
            if existing:
                answer = owner.ui.messageBox(
                    "Replace existing STL files?\n" + "\n".join(existing),
                    "Export STL",
                    owner.adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                )
                if answer != owner.adsk.core.DialogResults.DialogYes:
                    return
        owner.submit(bodies, preferences, paths)

    def close(self) -> None:
        for event, handler in self.handlers:
            event.remove(handler)
        self.handlers.clear()
        if self in self.owner.dialogs:
            self.owner.dialogs.remove(self)
