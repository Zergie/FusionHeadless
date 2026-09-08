"""Child-only batch preparation, file staging, and slicer handoff."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from threading import Event, Thread
from time import monotonic
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import webbrowser

import routes
from routing import route_definitions
from startup.stl_export_contract import APPLICATIONS, BUILD_PLATE_APPEARANCE, BodySelection


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def prepare_exports(
    origin: str, bodies: list[BodySelection], *, orient: str | None = None,
    redirect_url: str | None = None, cancelled: Event | None = None,
) -> list[bytes] | list[str]:
    """Stage every response before saving files or opening application URLs."""
    path = next(d.path for d in route_definitions() if d.operation is routes.export_route)
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    files: list[bytes] = []
    redirects: list[str] = []
    redirect_deadline: float | None = None
    for index, body in enumerate(bodies, 1):
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("STL export cancelled")
        arguments = {
            "format": "stl",
            "component": body.component,
            "body": [body.name],
            "document": body.document,
            "entity_token": body.entity_token,
            "orient": orient,
            "redirect_url": redirect_url,
        }
        request = Request(
            origin + path,
            data=json.dumps(arguments).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            try:
                response = opener.open(request, timeout=300)
            except HTTPError as error:
                response = error
            with response:
                if redirect_url is not None and response.status == 303:
                    location = response.headers.get("Location", "")
                    if not location.startswith(redirect_url.split("{url}", 1)[0]):
                        raise RuntimeError("Export returned an unexpected application redirect")
                    redirects.append(location)
                    if redirect_deadline is None:
                        redirect_deadline = monotonic() + 285
                elif redirect_url is None and response.status == 200:
                    files.append(response.read())
                else:
                    detail = response.read().decode("utf-8", errors="replace")
                    try:
                        detail = json.loads(detail).get("error", detail)
                    except (ValueError, AttributeError):
                        pass
                    raise RuntimeError(f"Export HTTP {response.status}: {detail}")
        except (OSError, URLError, RuntimeError) as error:
            raise RuntimeError(f"Body {index} of {len(bodies)}: {error}") from error
    if cancelled is not None and cancelled.is_set():
        raise RuntimeError("STL export cancelled")
    if redirect_deadline is not None and monotonic() >= redirect_deadline:
        raise RuntimeError(
            "Application download URLs expired or are about to expire while preparing "
            "the batch. Export fewer bodies at once, or use Export only."
        )
    return redirects if redirect_url is not None else files


class StlExportOrchestrator:
    """Run complete export batches in the child after the Fusion event returns."""

    def __init__(
        self, origin: str, owner_token: str,
        finished: Callable[[dict[str, str], int, str | None], Any],
        *, open_url: Callable[[str], Any] = webbrowser.open,
    ) -> None:
        self.origin = origin
        self.owner_token = owner_token
        self.finished = finished
        self.open_url = open_url
        self.cancelled = Event()

    def enqueue(
        self, bodies: list[BodySelection], preferences: dict[str, str], paths: list[Path],
    ) -> None:
        Thread(
            target=self._run,
            args=(bodies, preferences, paths),
            name="fusionheadless-stl-export",
            daemon=True,
        ).start()

    def _run(
        self, bodies: list[BodySelection], preferences: dict[str, str], paths: list[Path],
    ) -> None:
        count = 0
        error_message = None
        try:
            results = prepare_exports(
                self.origin,
                bodies,
                orient=(BUILD_PLATE_APPEARANCE
                        if preferences["orient"] == "Appearance" else None),
                redirect_url=APPLICATIONS[preferences["application"]],
                cancelled=self.cancelled,
            )
            if paths:
                self._save(paths, results)
            else:
                self._open(preferences["application"], results)
            count = len(bodies)
        except Exception as error:
            if self.cancelled.is_set():
                return
            error_message = str(error)
        self.finished(preferences, count, error_message)

    def _save(self, paths: list[Path], results: list[bytes] | list[str]) -> None:
        staged: list[tuple[Path, Path]] = []
        try:
            for path, payload in zip(paths, results):
                if not isinstance(payload, bytes):
                    raise RuntimeError("Expected STL bytes from export")
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
                    temporary = Path(file.name)
                    staged.append((temporary, path))
                    file.write(payload)
            for temporary, path in staged:
                if self.cancelled.is_set():
                    return
                os.replace(temporary, path)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)

    def _open(self, application: str, results: list[bytes] | list[str]) -> None:
        for location in results:
            if self.cancelled.is_set():
                return
            if not isinstance(location, str):
                raise RuntimeError("Expected an application redirect from export")
            if not self.open_url(location):
                raise RuntimeError(
                    f"Could not open {application} URL; check its protocol-handler installation"
                )

    def close(self) -> None:
        self.cancelled.set()
