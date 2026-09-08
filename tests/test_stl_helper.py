from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from cli.match_with_files import main, match_with_files, str2hash


def component(name="Bracket", identity="component-1", material="ABS"):
    return {
        "id": identity, "name": name,
        "occurrences": [{"path": f"{name}:1"}, {"path": f"{name}:2"}],
        "bodies": [{"name": "Body1", "hash": "geometry-hash",
                    "material": material}],
    }


class StlHelperTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.diagnostics = io.StringIO()
        self.enterContext(contextlib.redirect_stderr(self.diagnostics))

    def match(self, *components):
        return match_with_files({item["id"]: item for item in components},
                                str(self.folder), "ABS", "Red ABS")

    def test_legacy_records_matching_grouping_and_input_preservation(self):
        path = self.folder / "bracket_x2.stl"
        path.write_bytes(b"existing mesh")
        part = component()
        part["bodies"].append({**part["bodies"][0], "name": "Body2", "hash": "second-hash"})
        original = copy.deepcopy(part)
        result = self.match(part)
        identity = str2hash(str(path))
        self.assertEqual(result, {identity + ".json": {
            "id": identity, "path": str(path), "bodies": ["Body1", "Body2"],
            "body_hashes": ["geometry-hash", "second-hash"],
            "component_id": "component-1", "component_name": "Bracket",
            "suggested_name": "bracket_x2.stl",
        }})
        self.assertEqual(part, original)
        self.assertEqual(path.read_bytes(), b"existing mesh")

    def test_material_filter_accent_naming_and_missing_file(self):
        result = self.match(component("Lever", material="Red ABS"),
                            component("Bolt", "bolt", "Steel"))
        item = next(iter(result.values()))
        self.assertEqual(len(result), 1)
        self.assertEqual(item["suggested_name"], "[a]_lever_x2.stl")
        self.assertFalse(Path(item["path"]).exists())

    def test_body_subfolder_and_legacy_quantity_insensitive_matching(self):
        part = component()
        part["bodies"][0]["name"] = "Plate"
        folder = self.folder / "plate"
        folder.mkdir()
        path = folder / "Bracket_x4.stl"
        path.touch()
        item = next(iter(self.match(part).values()))
        self.assertEqual(item["path"], str(path))
        self.assertEqual(item["suggested_name"], "plate/bracket_x2.stl")

    def test_ambiguous_files_and_cross_component_collisions_fail(self):
        for directory in ("a", "b"):
            folder = self.folder / directory
            folder.mkdir()
            (folder / "bracket.stl").touch()
        with self.assertRaisesRegex(ValueError, "multiple matching"):
            self.match(component())
        (self.folder / "b" / "bracket.stl").unlink()
        with self.assertRaisesRegex(ValueError, "different components"):
            self.match(component(), component(identity="component-2"))

    def test_cli_writes_combined_and_individual_manifests_without_timestamp_churn(self):
        source, output = self.folder / "components.json", self.folder / "obj" / "printed.json"
        outdir = self.folder / "obj" / "STLs"
        source.write_text(json.dumps({"status": "ok", "result": {"one": component()}}))
        arguments = ["--file", str(source), "--match-with-files", str(self.folder),
                     "--base-material", "ABS", "--accent-material", "Red ABS",
                     "--output", str(output), "--outdir", str(outdir)]
        self.assertEqual(main(arguments), 0)
        manifest = json.loads(output.read_text())
        name, item = next(iter(manifest.items()))
        individual = outdir / name
        self.assertEqual(json.loads(individual.read_text()), item)
        before = [path.stat().st_mtime_ns for path in (output, individual)]
        self.assertEqual(main(arguments), 0)
        self.assertEqual([path.stat().st_mtime_ns for path in (output, individual)], before)

    def test_cli_rejects_invalid_data_before_writing(self):
        source, output = self.folder / "bad.json", self.folder / "result.json"
        source.write_text("[]")
        self.assertEqual(main(["--file", str(source), "--folder", str(self.folder),
                               "--base-material", "ABS", "--accent-material", "Red ABS",
                               "--output", str(output)]), 1)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
