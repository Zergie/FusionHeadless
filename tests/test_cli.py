from __future__ import annotations

import copy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from cli import fusion_cli
import server


class FusionCliContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = server.app.openapi()
        cls.commands = fusion_cli.commands_from_openapi(cls.document)

    def test_endpoint_paths_become_verbs_and_choose_confirmed_methods(self) -> None:
        self.assertEqual(set(self.commands), {
            "bodies", "components", "document", "eval", "exec", "export",
            "files", "mcp", "parameter", "projects", "render", "restart",
            "scripts", "select", "status",
        })
        self.assertEqual(set(self.commands["files"].operations), {"get"})
        self.assertEqual(set(self.commands["render"].operations), {"post"})
        self.assertEqual(set(self.commands["parameter"].operations), {"get", "post"})
        self.assertEqual(set(self.commands["scripts"].operations), {"get", "post"})
        self.assertEqual(fusion_cli.powershell_verbs(self.document),
                         sorted((*self.commands, "cli")))

    def test_openapi_parameters_drive_native_cli_and_powershell_names(self) -> None:
        render = self.commands["render"]
        options = {option.wire_name: option for option in render.options}

        self.assertEqual(options["focalLength"].flag, "--focal-length")
        self.assertEqual(options["focalLength"].powershell_name, "FocalLength")
        self.assertEqual(options["isAntiAliased"].flag, "--anti-aliased")
        self.assertEqual(options["isAntiAliased"].powershell_name, "IsAntiAliased")
        definitions = {
            item["name"]: item
            for item in fusion_cli.powershell_parameters(self.document, "render")
        }
        self.assertEqual(definitions["IsAntiAliased"]["flag"], "--anti-aliased")
        self.assertEqual(definitions["IsAntiAliased"]["falseFlag"],
                         "--no-anti-aliased")
        self.assertNotIn("AntiAliased", definitions)
        self.assertNotIn("NoAntiAliased", definitions)

    def test_repeated_switches_and_boolean_negation_build_json_payload(self) -> None:
        parser = fusion_cli.build_parser(self.commands)
        namespace = parser.parse_args([
            "render", "--hide", "Body A", "--hide", "Body B",
            "--no-anti-aliased", "--width", "640",
        ])

        payload = fusion_cli._arguments_for_command(namespace, self.commands["render"])

        self.assertEqual(payload, {
            "hide": ["Body A", "Body B"],
            "isAntiAliased": False,
            "width": 640,
        })

    def test_query_replaces_the_public_jmespath_option(self) -> None:
        parser = fusion_cli.build_parser(self.commands)
        namespace = parser.parse_args(["status", "--query", "result.document"])

        self.assertEqual(namespace.query, ["result.document"])
        for removed_option in ("--jmespath", "--json"):
            with (
                self.assertRaises(SystemExit),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                parser.parse_args(["status", removed_option, "result.document"])

    def test_parameter_reads_with_get_and_writes_with_repeated_set(self) -> None:
        command = self.commands["parameter"]

        self.assertEqual(fusion_cli._choose_operation(command, {}).method, "get")
        operation = fusion_cli._choose_operation(command, {"set": ["d1=3.5"]})
        self.assertEqual(operation.method, "post")

    def test_exec_supports_inline_file_and_stdin_alternatives(self) -> None:
        command = self.commands["exec"]
        powershell = fusion_cli.powershell_parameters(self.document, "exec")
        code = next(item for item in powershell if item["name"] == "Code")
        self.assertFalse(code["required"])
        self.assertEqual(
            {item["name"] for item in powershell if item["name"] in {"File", "Stdin"}},
            {"File", "Stdin"},
        )

        parser = fusion_cli.build_parser(self.commands)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "operation.py"
            source.write_text("return 40 + 2\n", encoding="utf-8")
            namespace = parser.parse_args(["exec", "--file", str(source)])
            payload = fusion_cli._arguments_for_command(namespace, command)
        self.assertEqual(payload, {"code": "return 40 + 2\n"})

    def test_cache_key_uses_normalized_origin_and_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"FUSION_HEADLESS_CACHE_DIR": directory}
        ):
            first = fusion_cli.schema_cache_path("HTTP://LOCALHOST:5000/", "0.2.0")
            same = fusion_cli.schema_cache_path("http://localhost:5000", "0.2.0")
            newer = fusion_cli.schema_cache_path("http://localhost:5000", "0.3.0")

        self.assertEqual(first, same)
        self.assertNotEqual(first, newer)
        self.assertTrue(first.name.endswith("-0.2.0.json"))

    def test_cached_openapi_is_used_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"FUSION_HEADLESS_CACHE_DIR": directory}
        ):
            path = fusion_cli.schema_cache_path(fusion_cli.DEFAULT_BASE_URL, "0.2.0")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.document), encoding="utf-8")
            with patch.object(fusion_cli, "_fetch_schema") as fetch:
                loaded = fusion_cli.load_schema(fusion_cli.DEFAULT_BASE_URL)

        self.assertEqual(loaded["info"]["version"], "0.2.0")
        fetch.assert_not_called()

    def test_unknown_switch_refreshes_schema_once_before_parsing_again(self) -> None:
        refreshed = copy.deepcopy(self.document)
        reference = refreshed["paths"]["/render"]["post"]["requestBody"][
            "content"
        ]["application/json"]["schema"]["$ref"]
        model = reference.rsplit("/", 1)[1]
        refreshed["components"]["schemas"][model]["properties"]["newFlag"] = {
            "type": "string", "description": "A newly installed route option."
        }
        response = fusion_cli.EndpointResponse(
            200, {"content-type": "application/json"}, {"status": "ok", "result": {}},
            b'{}', "POST", "http://127.0.0.1:5000/render",
        )

        with (
            patch.object(fusion_cli, "load_schema",
                         side_effect=[self.document, refreshed]) as load,
            patch.object(fusion_cli, "_request_endpoint", return_value=response) as request,
            patch.object(fusion_cli, "_emit"),
        ):
            self.assertEqual(fusion_cli.run(["render", "--new-flag", "ready"]), 0)

        self.assertEqual(load.call_count, 2)
        self.assertFalse(load.call_args_list[0].kwargs.get("refresh", False))
        self.assertTrue(load.call_args_list[1].kwargs["refresh"])
        self.assertEqual(request.call_args.args[3], {"newFlag": "ready"})

    def test_cli_refreshes_schema_without_calling_an_endpoint(self) -> None:
        with patch.object(fusion_cli, "load_schema") as load:
            self.assertEqual(fusion_cli.run(["cli", "--refresh"]), 0)

        load.assert_called_once_with(fusion_cli.DEFAULT_BASE_URL, refresh=True)

    def test_cli_management_verb_exposes_refresh(self) -> None:
        definitions = fusion_cli.powershell_parameters({}, "cli")

        self.assertEqual([item["name"] for item in definitions], ["Refresh"])
        self.assertEqual([item["flag"] for item in definitions], ["--refresh"])

    def test_platform_wrappers_are_thin_and_keep_cli_in_its_own_venv(self) -> None:
        directory = Path(fusion_cli.__file__).parent
        self.assertIn(".venv\\Scripts\\python.exe",
                      (directory / "fusion_cli.cmd").read_text(encoding="utf-8"))
        self.assertIn(".venv/bin/python",
                      (directory / "fusion_cli.sh").read_text(encoding="utf-8"))
        powershell = (directory / "fusion_cli.ps1").read_text(encoding="utf-8")
        self.assertIn("dynamicparam", powershell.lower())
        self.assertIn("RuntimeDefinedParameter", powershell)
        self.assertEqual(
            (directory / "requirements.txt").read_text(encoding="utf-8").splitlines(),
            ["jmespath==1.0.1", "Pygments==2.19.2"],
        )

    def test_human_json_output_is_syntax_highlighted(self) -> None:
        pygments = types.ModuleType("pygments")
        pygments.highlight = lambda source, lexer, formatter: "<color>" + source
        formatters = types.ModuleType("pygments.formatters")
        formatters.TerminalFormatter = object
        lexers = types.ModuleType("pygments.lexers")
        lexers.JsonLexer = object
        with patch.dict(sys.modules, {
            "pygments": pygments,
            "pygments.formatters": formatters,
            "pygments.lexers": lexers,
        }):
            formatted = fusion_cli._format_human_json({"status": "ok"})

        self.assertTrue(formatted.startswith("<color>"))
        self.assertIn('"status"', formatted)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is not installed")
    def test_powershell_completes_verbs_and_boolean_switches_from_openapi(self) -> None:
        cli_directory = Path(fusion_cli.__file__).parent
        cli_python = next((candidate for candidate in (
            cli_directory / ".venv" / "Scripts" / "python.exe",
            cli_directory / ".venv" / "bin" / "python",
        ) if candidate.exists()), None)
        if cli_python is None:
            self.skipTest("the explicit cli/.venv setup has not been completed")
        wrapper = str(cli_directory / "fusion_cli.ps1")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"FUSION_HEADLESS_CACHE_DIR": directory}
        ):
            path = fusion_cli.schema_cache_path(fusion_cli.DEFAULT_BASE_URL, "0.2.0")
            path.write_text(json.dumps(self.document), encoding="utf-8")
            environment = os.environ.copy()
            verb_line = f"& '{wrapper}' "
            switch_line = f"& '{wrapper}' render -I"
            script = (
                "$verbLine = '" + verb_line.replace("'", "''") + "'; "
                "$switchLine = '" + switch_line.replace("'", "''") + "'; "
                "$result = [pscustomobject]@{ "
                "verbs = @((TabExpansion2 $verbLine $verbLine.Length).CompletionMatches.CompletionText); "
                "switches = @((TabExpansion2 $switchLine $switchLine.Length).CompletionMatches.CompletionText) "
                "}; $result | ConvertTo-Json -Compress"
            )
            completed = subprocess.run(
                [shutil.which("pwsh") or "pwsh", "-NoProfile", "-Command", script],
                cwd=Path(__file__).parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        completions = json.loads(completed.stdout)
        self.assertIn("status", completions["verbs"])
        self.assertIn("-IsAntiAliased", completions["switches"])
        self.assertNotIn("-AntiAliased", completions["switches"])
        self.assertNotIn("-NoAntiAliased", completions["switches"])


if __name__ == "__main__":
    unittest.main()
