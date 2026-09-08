from __future__ import annotations

import os
from pathlib import Path
import socket
import tempfile
from threading import Event
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from tests.test_stl_batch import StlExportFixture
from tests.test_stl_batch import BatchHost
from adapter import FusionAdapter


class Signal:
    def __init__(self):
        self.handlers = []

    def add(self, handler):
        self.handlers.append(handler)

    def remove(self, handler):
        self.handlers.remove(handler)

    def fire(self, **kwargs):
        for handler in self.handlers[:]:
            handler.notify(NS(**kwargs))


class Items(list):
    @property
    def count(self):
        return len(self)

    def item(self, index):
        return self[index]

    def add(self, name, selected, *args):
        item = NS(name=name, isSelected=selected, index=len(self))
        self.append(item)
        return item


class Input:
    def __init__(self, identity):
        self.id = identity
        self.listItems = Items()
        self.entities = []
        self.isVisible = True
        self.isEnabled = True

    @property
    def selectedItem(self):
        return next((item for item in self.listItems if item.isSelected), None)

    def choose(self, name):
        for item in self.listItems:
            item.isSelected = item.name == name

    def addSelectionFilter(self, value):
        self.filter = value

    def setSelectionLimits(self, minimum, maximum):
        self.limits = (minimum, maximum)

    def addSelection(self, entity):
        self.entities.append(entity)
        return True

    @property
    def selectionCount(self):
        return len(self.entities)

    def selection(self, index):
        return NS(entity=self.entities[index])


class Inputs(dict):
    def itemById(self, identity):
        return self[identity]

    def addSelectionInput(self, identity, *args):
        self[identity] = Input(identity)
        return self[identity]

    addDropDownCommandInput = addSelectionInput

    def addTextBoxCommandInput(self, identity, name, text, rows, read_only):
        self[identity] = Input(identity)
        self[identity].name = name
        self[identity].text = text
        self[identity].rows = rows
        self[identity].isReadOnly = read_only
        return self[identity]


class Definition:
    __slots__ = ("commandCreated", "controlDefinition", "deleted", "isPromotedByDefault", "isPromoted")

    def __init__(self):
        self.commandCreated = Signal()
        self.controlDefinition = NS(isEnabled=True)
        self.deleted = False

    def deleteMe(self):
        self.deleted = True


class NativeUI:
    def __init__(self, bodies, filename):
        self.definition = Definition()
        self.control = Definition()
        self.activeSelections = Items([NS(entity=body) for body in bodies])
        self.commandDefinitions = NS(addButtonDefinition=lambda *a: self.definition)
        panel = NS(controls=NS(addCommand=lambda *a: self.control))
        workspace = NS(toolbarPanels=NS(itemById=lambda identity: panel))
        self.workspaces = NS(itemById=lambda identity: workspace)
        self.filename = str(filename)
        self.messages = []
        self.finished = Event()
        self.save_calls = 0
        self.answer = "yes"
        self.save_result = "ok"
        self.definition_calls = 0

        def add_definition(*args):
            self.definition_calls += 1
            return self.definition

        self.commandDefinitions = NS(addButtonDefinition=add_definition)

    def createFileDialog(self):
        self.save_calls += 1
        return NS(filename=self.filename, showSave=lambda: self.save_result)

    def messageBox(self, message, *args):
        self.messages.append(message)
        if message.startswith("Exported") or message.startswith("STL export failed"):
            self.finished.set()
        return self.answer


class ChildStartupTests(unittest.TestCase):
    def start_child(self, host, ui, directory):
        host.app.userInterface = ui
        host.adsk.core = NS(
            CommandCreatedEventHandler=object,
            CommandEventHandler=object,
            InputChangedEventHandler=object,
            ValidateInputsEventHandler=object,
            DropDownStyles=NS(TextListDropDownStyle="text"),
            DialogResults=NS(DialogOK="ok", DialogYes="yes"),
            MessageBoxButtonTypes=NS(YesNoButtonType="yesno"),
        )
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(directory)})
        environment.start()
        self.addCleanup(environment.stop)
        adapter = FusionAdapter(host=host, port=port)
        self.addCleanup(adapter.stop)
        self.assertTrue(adapter.start(timeout=5))
        return adapter

    def test_active_child_installs_and_removes_export_stl_ui(self):
        host = BatchHost()
        with tempfile.TemporaryDirectory() as directory:
            ui = NativeUI(host.bodies, Path(directory) / "chosen.stl")
            adapter = self.start_child(host, ui, Path(directory))
            self.assertEqual(ui.definition_calls, 1)
            self.assertEqual(len(ui.definition.commandCreated.handlers), 1)
            adapter.stop()
            self.assertTrue(ui.definition.deleted)
            self.assertTrue(ui.control.deleted)

    def test_export_event_completes_a_child_owned_batch(self):
        host = BatchHost()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "chosen.stl"
            ui = NativeUI(host.bodies, destination)
            self.start_child(host, ui, Path(directory))
            command = NS(
                commandInputs=Inputs(), activate=Signal(), inputChanged=Signal(),
                validateInputs=Signal(), execute=Signal(), destroy=Signal(),
            )
            ui.definition.commandCreated.fire(command=command)
            command.activate.fire()
            command.execute.fire()
            self.assertTrue(ui.finished.wait(10), ui.messages)
            self.assertTrue(destination.exists(), ui.messages)
            self.assertTrue((Path(directory) / "chosen_2.stl").exists())
            self.assertTrue(ui.definition.controlDefinition.isEnabled)

    def test_replacement_child_reinstalls_export_stl_ui(self):
        host = BatchHost()
        with tempfile.TemporaryDirectory() as directory:
            ui = NativeUI(host.bodies, Path(directory) / "chosen.stl")
            adapter = self.start_child(host, ui, Path(directory))
            request = Request(
                f"http://127.0.0.1:{adapter.port}/restart",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(ui.definition_calls, 2)
            self.assertEqual(len(ui.definition.commandCreated.handlers), 1)

    def test_fingerprint_mismatch_does_not_install_startup_ui(self):
        host = BatchHost()
        with tempfile.TemporaryDirectory() as directory:
            ui = NativeUI(host.bodies, Path(directory) / "chosen.stl")
            host.app.userInterface = ui
            host.adsk.core = NS(
                CommandCreatedEventHandler=object,
                CommandEventHandler=object,
                ValidateInputsEventHandler=object,
                DropDownStyles=NS(TextListDropDownStyle="text"),
                DialogResults=NS(DialogOK="ok", DialogYes="yes"),
                MessageBoxButtonTypes=NS(YesNoButtonType="yesno"),
            )
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            adapter = FusionAdapter(host=host, port=port)
            adapter._extension_fingerprint = "mismatch"
            self.addCleanup(adapter.stop)
            self.assertFalse(adapter.start(timeout=5))
            self.assertEqual(ui.definition_calls, 0)


class StlCommandTests(StlExportFixture, unittest.TestCase):
    # Reuse the real HTTP/bridge fixture; tests below enter through native events.
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.ui = NativeUI(self.host.bodies, self.folder / "chosen.stl")
        self.host.app.userInterface = self.ui
        self.host.adsk.core = NS(CommandCreatedEventHandler=object, CommandEventHandler=object,
            InputChangedEventHandler=object, ValidateInputsEventHandler=object,
            DropDownStyles=NS(TextListDropDownStyle="text"),
            DialogResults=NS(DialogOK="ok", DialogYes="yes"),
            MessageBoxButtonTypes=NS(YesNoButtonType="yesno"))
        self.opened = []

    def open_command(self):
        from startup.stl_export_contract import BodySelection
        from startup.stl_export_job import StlExportOrchestrator
        from startup.stl_export_ui import StlExportCommand

        owner_box = {}

        orchestrator = StlExportOrchestrator(
            self.origin, "test-owner",
            lambda preferences, count, error: owner_box["owner"].finished(
                preferences, count, error
            ),
            open_url=lambda url: self.opened.append(url) or True,
        )

        def enqueue(bodies, preferences, paths, owner_token):
            self.assertEqual(owner_token, "test-owner")
            orchestrator.enqueue(
                [BodySelection(item["component"], item["name"]) for item in bodies],
                preferences,
                [Path(path) for path in paths],
            )

        context = NS(ui=self.ui, adsk=self.host.adsk, app=self.host.app)
        owner = StlExportCommand(
            context, "test-owner", enqueue,
            settings_path=self.folder / "settings.json",
        )
        owner_box["owner"] = owner
        owner.start()
        self.addCleanup(orchestrator.close)
        self.addCleanup(owner.close)
        command = NS(commandInputs=Inputs(), activate=Signal(), inputChanged=Signal(),
                     validateInputs=Signal(), execute=Signal(), destroy=Signal())
        self.ui.definition.commandCreated.fire(command=command)
        command.activate.fire()
        return owner, command

    def test_save_as_numbers_files_and_prefills_only_body_selection(self):
        owner, command = self.open_command()
        self.assertEqual(set(command.commandInputs), {"object", "orient", "appearance_note", "application"})
        self.assertEqual(command.commandInputs["appearance_note"].text, "Uses 'Build Plate' appearances.")
        self.assertFalse(command.commandInputs["appearance_note"].isVisible)
        self.assertEqual(command.commandInputs["object"].selectionCount, 2)
        self.assertEqual(command.commandInputs["object"].limits, (1, 0))
        command.execute.fire()
        self.assertTrue(self.ui.finished.wait(10), self.ui.messages)
        self.assertEqual(self.ui.save_calls, 1)
        self.assertTrue((self.folder / "chosen.stl").exists(), self.ui.messages)
        self.assertTrue((self.folder / "chosen_2.stl").exists())
        self.assertEqual(self.opened, [])
        owner.close()
        self.assertTrue(self.ui.definition.deleted)
        self.assertTrue(self.ui.control.deleted)

    def test_later_invalid_body_leaves_existing_files_untouched(self):
        existing = self.folder / "chosen.stl"
        existing.write_bytes(b"original")
        owner, command = self.open_command()
        self.host.bodies[1].isValid = False
        command.execute.fire()
        self.assertTrue(self.ui.finished.wait(10), self.ui.messages)
        self.assertTrue(any("body 2" in message.lower() for message in self.ui.messages))
        self.assertEqual(existing.read_bytes(), b"original")
        self.assertFalse((self.folder / "chosen_2.stl").exists())
        self.assertTrue(self.ui.definition.controlDefinition.isEnabled)

    def test_redirects_open_only_after_all_bodies_succeed_and_application_is_remembered(self):
        owner, command = self.open_command()
        command.commandInputs["application"].choose("Cura")
        command.execute.fire()
        self.assertTrue(self.ui.finished.wait(10), self.ui.messages)
        self.assertEqual(len(self.opened), 2)
        self.assertTrue(all(url.startswith("cura://open?file=") for url in self.opened))
        self.assertEqual(self.ui.save_calls, 0)
        owner.close()
        _, reopened = self.open_command()
        self.assertEqual(reopened.commandInputs["application"].selectedItem.name, "Cura")

    def test_later_invalid_body_opens_no_application_urls(self):
        _, command = self.open_command()
        command.commandInputs["application"].choose("OrcaSlicer")
        self.host.bodies[1].isValid = False
        command.execute.fire()
        self.assertTrue(self.ui.finished.wait(10), self.ui.messages)
        self.assertEqual(self.opened, [])

    def test_declining_overwrite_does_not_export(self):
        (self.folder / "chosen_2.stl").write_bytes(b"keep")
        self.ui.answer = "no"
        _, command = self.open_command()
        command.execute.fire()
        self.assertEqual(self.host.exported, [])
        self.assertEqual((self.folder / "chosen_2.stl").read_bytes(), b"keep")

    def test_cancel_save_as_does_not_export_or_change_preferences(self):
        self.ui.save_result = "cancel"
        _, command = self.open_command()
        command.execute.fire()
        self.assertEqual(self.host.exported, [])
        self.assertFalse((self.folder / "settings.json").exists())

    def test_appearance_orientation_uses_build_plate_marker_and_is_remembered(self):
        self.mark_bodies()
        for body in self.host.bodies:
            body.faces[0].appearance.name = "YAMMU Build Plate"
        owner, command = self.open_command()
        inputs = command.commandInputs
        inputs["orient"].choose("Appearance")
        command.inputChanged.fire(input=inputs["orient"])
        self.assertTrue(inputs["appearance_note"].isVisible)
        inputs["orient"].choose("Original")
        command.inputChanged.fire(input=inputs["orient"])
        self.assertFalse(inputs["appearance_note"].isVisible)
        inputs["orient"].choose("Appearance")
        command.inputChanged.fire(input=inputs["orient"])
        command.execute.fire()
        self.assertTrue(self.ui.finished.wait(10), self.ui.messages)
        self.assertTrue((self.folder / "chosen.stl").exists(), self.ui.messages)
        owner.close()
        _, reopened = self.open_command()
        self.assertEqual(reopened.commandInputs["orient"].selectedItem.name, "Appearance")
        self.assertTrue(reopened.commandInputs["appearance_note"].isVisible)

    def test_appearance_orientation_ignores_other_appearance_names(self):
        self.mark_bodies()
        _, command = self.open_command()
        command.commandInputs["orient"].choose("Appearance")
        command.execute.fire()
        self.assertTrue(self.ui.finished.wait(10), self.ui.messages)
        self.assertTrue(any("Build Plate" in message for message in self.ui.messages))
        self.assertFalse((self.folder / "chosen.stl").exists())

    def test_saved_appearance_marker_name_is_not_migrated(self):
        (self.folder / "settings.json").write_text(
            '{"orient": "Appearance marker", "application": "Export only"}', encoding="utf-8")
        _, command = self.open_command()
        self.assertEqual(command.commandInputs["orient"].selectedItem.name, "Original")
        self.assertFalse(command.commandInputs["appearance_note"].isVisible)
