#!/usr/bin/env python3
"""OpenAPI-driven command line client for FusionHeadless."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:5000"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "FusionHeadless.manifest"
HTTP_METHODS = ("get", "post")


class CliError(RuntimeError):
    """A concise error safe to show to a command-line user."""


class _CommandHelpFormatter(argparse.HelpFormatter):
    """List commands without repeating their generated choice inventory."""

    def _format_action(self, action: argparse.Action) -> str:
        if isinstance(action, argparse._SubParsersAction):
            return "".join(
                self._format_action(subaction)
                for subaction in self._iter_indented_subactions(action)
            )
        return super()._format_action(action)


@dataclass(frozen=True)
class Option:
    wire_name: str
    flag: str
    powershell_name: str
    description: str
    schema: dict[str, Any]
    required: bool
    methods: frozenset[str]

    @property
    def kind(self) -> str:
        schema = _without_null(self.schema)
        if schema.get("type") == "array":
            return "array"
        return str(schema.get("type", "string"))


@dataclass(frozen=True)
class Operation:
    method: str
    body: bool
    opaque_body: bool
    required: frozenset[str]


@dataclass(frozen=True)
class Command:
    name: str
    path: str
    summary: str
    options: tuple[Option, ...]
    operations: dict[str, Operation]


@dataclass(frozen=True)
class EndpointResponse:
    status_code: int
    headers: dict[str, str]
    value: Any
    raw: bytes
    method: str
    url: str


def manifest_version(path: Path = MANIFEST_PATH) -> str:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise CliError(f"Manifest has no valid version: {path}")
    return version.strip()


def normalize_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise CliError(f"Invalid FusionHeadless URL: {value!r}")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def cache_root() -> Path:
    override = os.environ.get("FUSION_HEADLESS_CACHE_DIR")
    if override:
        return Path(override)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "FusionHeadless" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "FusionHeadless"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "fusionheadless"


def schema_cache_path(base_url: str, version: str) -> Path:
    origin_key = hashlib.sha256(normalize_base_url(base_url).encode("utf-8")).hexdigest()[:16]
    return cache_root() / f"openapi-{origin_key}-{version}.json"


def _fetch_schema(base_url: str, version: str, timeout: float = 5.0) -> dict[str, Any]:
    url = normalize_base_url(base_url) + "/openapi.json"
    try:
        with urlopen(url, timeout=timeout) as response:
            document = json.load(response)
    except (OSError, HTTPError, URLError, json.JSONDecodeError) as error:
        raise CliError(f"Could not load FusionHeadless schema from {url}: {error}") from error
    actual = document.get("info", {}).get("version") if isinstance(document, dict) else None
    if actual != version:
        raise CliError(
            f"FusionHeadless version mismatch: CLI expects {version}, server reports {actual!r}"
        )
    path = schema_cache_path(base_url, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
    temporary.replace(path)
    return document


def load_schema(base_url: str, *, refresh: bool = False) -> dict[str, Any]:
    version = manifest_version()
    path = schema_cache_path(base_url, version)
    if refresh or not path.exists():
        return _fetch_schema(base_url, version)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CliError(f"Invalid cached OpenAPI document {path}: {error}") from error
    if document.get("info", {}).get("version") != version:
        return _fetch_schema(base_url, version)
    return document


def _resolve_schema(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise CliError(f"Unsupported OpenAPI reference: {reference}")
    name = reference[len(prefix):]
    try:
        return document["components"]["schemas"][name]
    except KeyError as error:
        raise CliError(f"OpenAPI reference does not exist: {reference}") from error


def _without_null(schema: dict[str, Any]) -> dict[str, Any]:
    variants = schema.get("anyOf") or schema.get("oneOf")
    if not isinstance(variants, list):
        return schema
    concrete = [item for item in variants if item.get("type") != "null"]
    if len(concrete) == 1:
        return concrete[0]
    if any(item.get("type") == "array" for item in concrete):
        return next(item for item in concrete if item.get("type") == "array")
    return concrete[0] if concrete else schema


def _kebab_case(value: str) -> str:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    return separated.replace("_", "-").lower()


def _pascal_case(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in _kebab_case(value).split("-") if part)


def _option_names(wire_name: str, schema: dict[str, Any]) -> tuple[str, str]:
    display = wire_name
    if _without_null(schema).get("type") == "boolean" and re.match(r"^is[A-Z]", display):
        display = display[2:3].lower() + display[3:]
    kebab = _kebab_case(display)
    return "--" + kebab, _pascal_case(wire_name)


def commands_from_openapi(document: dict[str, Any]) -> dict[str, Command]:
    commands: dict[str, Command] = {}
    for path, path_item in document.get("paths", {}).items():
        operations: dict[str, Operation] = {}
        combined: dict[str, dict[str, Any]] = {}
        summaries = []
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            summaries.append(operation.get("summary") or operation.get("description") or "")
            required: set[str] = set()
            body = False
            opaque_body = False
            for parameter in operation.get("parameters", []):
                if parameter.get("in") != "query":
                    continue
                wire_name = parameter["name"]
                schema = _resolve_schema(document, parameter.get("schema", {}))
                entry = combined.setdefault(wire_name, {
                    "schema": schema,
                    "description": parameter.get("description") or schema.get("description") or "",
                    "required": False,
                    "methods": set(),
                })
                entry["methods"].add(method)
                entry["required"] = entry["required"] or bool(parameter.get("required"))
                if parameter.get("required"):
                    required.add(wire_name)
            request_body = operation.get("requestBody", {})
            content = request_body.get("content", {}).get("application/json", {})
            if content:
                body = True
                schema = _resolve_schema(document, content.get("schema", {}))
                properties = schema.get("properties", {})
                opaque_body = not properties and bool(schema.get("additionalProperties"))
                for wire_name, raw_property in properties.items():
                    property_schema = _resolve_schema(document, raw_property)
                    entry = combined.setdefault(wire_name, {
                        "schema": property_schema,
                        "description": property_schema.get("description") or "",
                        "required": False,
                        "methods": set(),
                    })
                    entry["methods"].add(method)
                    is_required = wire_name in schema.get("required", [])
                    entry["required"] = entry["required"] or is_required
                    if is_required:
                        required.add(wire_name)
            operations[method] = Operation(
                method,
                body,
                opaque_body,
                frozenset(required),
            )
        if not operations:
            continue
        options = []
        for wire_name, value in combined.items():
            flag, powershell_name = _option_names(wire_name, value["schema"])
            options.append(Option(
                wire_name,
                flag,
                powershell_name,
                value["description"],
                value["schema"],
                bool(value["required"]),
                frozenset(value["methods"]),
            ))
        name = path.strip("/").replace("/", "-") or "root"
        commands[name] = Command(
            name,
            path,
            next((text for text in summaries if text), name),
            tuple(sorted(options, key=lambda item: item.flag)),
            operations,
        )
    return commands


def _converter(option: Option):
    schema = _without_null(option.schema)
    kind = schema.get("type")
    if kind == "integer":
        return int
    if kind == "number":
        return float
    if kind == "object":
        return json.loads
    return str


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=argparse.SUPPRESS,
                        help=f"FusionHeadless origin (default: {DEFAULT_BASE_URL}).")
    parser.add_argument("--timeout", type=float, default=argparse.SUPPRESS,
                        help="HTTP timeout in seconds (default: 60).")
    parser.add_argument("--raw", action="store_true", default=argparse.SUPPRESS,
                        help="Emit only the unwrapped endpoint result.")
    parser.add_argument("--output", default=argparse.SUPPRESS,
                        help="Write the endpoint result to this path.")
    parser.add_argument("--query", action="append", default=argparse.SUPPRESS,
                        help="Transform the unwrapped result with JMESPath.")
    parser.add_argument("--data", default=argparse.SUPPRESS,
                        help="Merge a JSON object from a literal, file path, or '-' stdin.")


def build_parser(commands: dict[str, Command]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fusion_cli",
        description=__doc__,
        formatter_class=_CommandHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=manifest_version())
    parser.add_argument("--refresh", action="store_true",
                        help="Refresh the versioned OpenAPI cache and exit.")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    for command in sorted(commands.values(), key=lambda item: item.name):
        subparser = subparsers.add_parser(command.name, help=command.summary)
        _add_common_arguments(subparser)
        if any(option.wire_name == "code" for option in command.options):
            source = subparser.add_mutually_exclusive_group()
            source.add_argument("--file", default=argparse.SUPPRESS,
                                help="Read the code parameter from a UTF-8 file.")
            source.add_argument("--stdin", action="store_true", default=argparse.SUPPRESS,
                                help="Read the code parameter from stdin.")
        for option in command.options:
            kwargs: dict[str, Any] = {
                "dest": "route__" + option.wire_name,
                "default": argparse.SUPPRESS,
                "help": option.description,
            }
            schema = _without_null(option.schema)
            choices = schema.get("enum")
            if choices:
                kwargs["choices"] = choices
            if option.kind == "boolean":
                group = subparser.add_mutually_exclusive_group()
                group.add_argument(option.flag, action="store_true", **kwargs)
                negative = "--no-" + option.flag[2:]
                negative_kwargs = dict(kwargs)
                negative_kwargs["help"] = f"Disable {option.flag[2:].replace('-', ' ')}."
                group.add_argument(negative, action="store_false", **negative_kwargs)
            elif option.kind == "array":
                item = _without_null(schema.get("items", {}))
                item_option = Option(option.wire_name, option.flag, option.powershell_name,
                                     option.description, item, option.required, option.methods)
                kwargs["type"] = _converter(item_option)
                kwargs["action"] = "append"
                subparser.add_argument(option.flag, **kwargs)
            else:
                kwargs["type"] = _converter(option)
                subparser.add_argument(option.flag, **kwargs)
    return parser


def _scan_base_url(arguments: list[str]) -> str:
    base_url = os.environ.get("FUSION_HEADLESS_URL", DEFAULT_BASE_URL)
    for index, argument in enumerate(arguments):
        if argument.startswith("--base-url="):
            base_url = argument.split("=", 1)[1]
        elif argument == "--base-url" and index + 1 < len(arguments):
            base_url = arguments[index + 1]
    return normalize_base_url(base_url)


def _read_data(value: str) -> dict[str, Any]:
    if value == "-":
        text = sys.stdin.read()
    elif value.lstrip().startswith("{"):
        text = value
    else:
        path = Path(value)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise CliError(f"Could not read JSON input {path}: {error}") from error
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise CliError(f"Invalid JSON input: {error}") from error
    if not isinstance(result, dict):
        raise CliError("--data must contain a JSON object")
    return result


def _arguments_for_command(namespace: argparse.Namespace, command: Command) -> dict[str, Any]:
    values = vars(namespace)
    payload = _read_data(values["data"]) if "data" in values else {}
    for option in command.options:
        key = "route__" + option.wire_name
        if key in values:
            payload[option.wire_name] = values[key]
    if "file" in values or values.get("stdin"):
        if "route__code" in values:
            raise CliError("Use exactly one of --code, --file, or --stdin")
        if "file" in values:
            try:
                payload["code"] = Path(values["file"]).read_text(encoding="utf-8")
            except OSError as error:
                raise CliError(f"Could not read code file {values['file']}: {error}") from error
        else:
            payload["code"] = sys.stdin.read()
    return payload


def _choose_operation(command: Command, payload: dict[str, Any]) -> Operation:
    if len(command.operations) == 1:
        operation = next(iter(command.operations.values()))
    elif not payload and "get" in command.operations:
        operation = command.operations["get"]
    elif "post" in command.operations:
        operation = command.operations["post"]
    else:
        raise CliError(f"Cannot select an HTTP method for {command.name}")
    missing = operation.required.difference(payload)
    if missing:
        flags = ", ".join("--" + _kebab_case(name) for name in sorted(missing))
        raise CliError(f"{command.name} requires {flags}")
    return operation


def _request_endpoint(
    base_url: str,
    command: Command,
    operation: Operation,
    payload: dict[str, Any],
    timeout: float,
) -> EndpointResponse:
    url = base_url + command.path
    data = None
    headers = {"Accept": "application/json"}
    if operation.method == "get":
        if payload:
            url += "?" + urlencode(payload, doseq=True)
    else:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=operation.method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            status_code = response.status
    except HTTPError as error:
        raw = error.read()
        response_headers = {key.lower(): value for key, value in error.headers.items()}
        value = _decode_response(raw, response_headers)
        if isinstance(value, bytes):
            detail = value.decode("utf-8", errors="replace")
        elif isinstance(value, str):
            detail = value
        else:
            detail = json.dumps(value, ensure_ascii=False)
        raise CliError(f"HTTP {error.code} {error.reason}: {detail}") from error
    except (OSError, URLError) as error:
        raise CliError(f"Could not call {url}: {error}") from error
    return EndpointResponse(
        status_code,
        response_headers,
        _decode_response(raw, response_headers),
        raw,
        operation.method.upper(),
        url,
    )


def _decode_response(raw: bytes, headers: dict[str, str]) -> Any:
    content_type = headers.get("content-type", "").lower()
    if "json" in content_type:
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CliError(f"Server returned invalid JSON: {error}") from error
    if content_type.startswith("text/"):
        return raw.decode("utf-8", errors="replace")
    return raw


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and value.get("status") == "ok" and "result" in value:
        return value["result"]
    return value


def _apply_query(value: Any, expressions: list[str]) -> Any:
    if not expressions:
        return value
    try:
        import jmespath
    except ImportError as error:
        raise CliError(
            "JMESPath support is not installed; install cli/requirements.txt into cli/.venv"
        ) from error
    for expression in expressions:
        value = jmespath.search(expression, value)
    return value


def _filename(headers: dict[str, str], command: Command) -> str:
    disposition = headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.IGNORECASE)
    return Path(match.group(1) if match else f"{command.name}.bin").name


def _write_if_changed(path: Path, value: Any, raw: bytes | None = None) -> bool:
    if raw is not None:
        content = raw
        if path.exists() and path.read_bytes() == content:
            return False
        path.write_bytes(content)
        return True
    if isinstance(value, str):
        content = value
    else:
        content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _format_human_json(value: Any) -> str:
    """Format a JSON result for an interactive terminal."""
    source = json.dumps(value, indent=2, ensure_ascii=False)
    if not sys.stdout.isatty():
        return source
    from pygments import highlight
    from pygments.formatters import TerminalFormatter
    from pygments.lexers import JsonLexer
    return highlight(source, JsonLexer(), TerminalFormatter()).rstrip("\n")


def _emit(namespace: argparse.Namespace, command: Command, response: EndpointResponse) -> None:
    values = vars(namespace)
    result = _apply_query(_unwrap(response.value), values.get("query", []))
    binary = isinstance(result, bytes)
    output_path = Path(values["output"]) if "output" in values else None
    if binary and output_path is None:
        output_path = Path.cwd() / _filename(response.headers, command)
    if output_path is not None:
        changed = _write_if_changed(output_path, result, response.raw if binary else None)
        result = {"path": str(output_path), "changed": changed}
    if values.get("raw"):
        if isinstance(result, str):
            print(result)
        else:
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    elif output_path is not None:
        state = "updated" if result["changed"] else "unchanged"
        print(f"{result['path']} ({state})")
    elif isinstance(result, str):
        print(result)
    else:
        print(_format_human_json(result))


def powershell_parameters(document: dict[str, Any], verb: str) -> list[dict[str, Any]]:
    commands = commands_from_openapi(document)
    command = commands.get(verb)
    if command is None:
        raise CliError(f"Unknown FusionHeadless verb: {verb}")
    result = []
    for option in command.options:
        schema = _without_null(option.schema)
        entry = {
            "name": option.powershell_name,
            "flag": option.flag,
            "kind": option.kind,
            "description": option.description,
            # -Code has the equivalent static -File and -Stdin alternatives.
            "required": option.required and option.wire_name != "code",
            "choices": schema.get("enum", []),
        }
        if option.kind == "boolean":
            entry["falseFlag"] = "--no-" + option.flag[2:]
        result.append(entry)
    if any(option.wire_name == "code" for option in command.options):
        result.extend((
            {
                "name": "File",
                "flag": "--file",
                "kind": "string",
                "description": "Read the code parameter from a UTF-8 file.",
                "required": False,
                "choices": [],
            },
            {
                "name": "Stdin",
                "flag": "--stdin",
                "kind": "boolean",
                "description": "Read the code parameter from standard input.",
                "required": False,
                "choices": [],
            },
        ))
    return result


def powershell_verbs(document: dict[str, Any]) -> list[str]:
    """Return endpoint-derived verb names."""
    return sorted(commands_from_openapi(document))


def _describe_powershell_verbs(arguments: list[str]) -> int | None:
    if "--describe-powershell-verbs" not in arguments:
        return None
    base_url = _scan_base_url(arguments)
    document = load_schema(base_url)
    print(json.dumps(powershell_verbs(document), ensure_ascii=False))
    return 0


def _describe_powershell(arguments: list[str]) -> int | None:
    if "--describe-powershell" not in arguments:
        return None
    index = arguments.index("--describe-powershell")
    if index + 1 >= len(arguments):
        raise CliError("--describe-powershell requires a verb")
    verb = arguments[index + 1]
    base_url = _scan_base_url(arguments)
    document = load_schema(base_url)
    print(json.dumps(powershell_parameters(document, verb), ensure_ascii=False))
    return 0


def run(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments == ["--version"]:
        print(manifest_version())
        return 0
    described_verbs = _describe_powershell_verbs(arguments)
    if described_verbs is not None:
        return described_verbs
    described = _describe_powershell(arguments)
    if described is not None:
        return described
    base_url = _scan_base_url(arguments)
    if "--refresh" in arguments:
        parser = argparse.ArgumentParser(prog="fusion_cli")
        parser.add_argument("--refresh", action="store_true",
                            help="Refresh the versioned OpenAPI cache and exit.")
        parser.add_argument("--base-url", default=base_url,
                            help=f"FusionHeadless origin (default: {DEFAULT_BASE_URL}).")
        namespace = parser.parse_args(arguments)
        load_schema(normalize_base_url(namespace.base_url), refresh=True)
        print("OpenAPI schema refreshed.")
        return 0
    document = load_schema(base_url)
    commands = commands_from_openapi(document)
    verb = next((argument for argument in arguments if not argument.startswith("-")), None)
    if verb is not None and verb not in commands:
        document = load_schema(base_url, refresh=True)
        commands = commands_from_openapi(document)
    parser = build_parser(commands)
    namespace, unknown = parser.parse_known_args(arguments)
    if unknown:
        document = load_schema(base_url, refresh=True)
        commands = commands_from_openapi(document)
        parser = build_parser(commands)
        namespace, unknown = parser.parse_known_args(arguments)
    if unknown:
        parser.error("unrecognized arguments: " + " ".join(unknown))
    values = vars(namespace)
    base_url = normalize_base_url(values.get("base_url", base_url))
    command = commands[namespace.verb]
    payload = _arguments_for_command(namespace, command)
    operation = _choose_operation(command, payload)
    response = _request_endpoint(
        base_url,
        command,
        operation,
        payload,
        values.get("timeout", 60.0),
    )
    _emit(namespace, command, response)
    return 0


def main() -> int:
    try:
        return run()
    except CliError as error:
        print(f"fusion_cli: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
