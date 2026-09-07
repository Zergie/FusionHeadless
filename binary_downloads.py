"""Child-owned binary downloads with event-loop expiry and single-use tokens."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import secrets
from typing import AsyncIterator
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response


def validate_redirect_url(template: str) -> None:
    """Reject malformed templates before performing an expensive export."""
    remainder = template.replace("{url}", "")
    if (template.count("{url}") != 1 or "{" in remainder or "}" in remainder
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127
                   for character in template)):
        raise ValueError("redirect_url must be an absolute URL containing exactly one {url} and no whitespace or control characters")
    try:
        scheme = urlsplit(template).scheme
    except ValueError as error:
        raise ValueError(f"Invalid redirect_url: {error}") from error
    if not scheme:
        raise ValueError("redirect_url must include a URL scheme")


@dataclass(frozen=True)
class Download:
    """File content and explicit metadata, independent of token scheduling."""

    payload: bytes
    media_type: str
    filename: str
    disposition: str = "attachment"

    def response(self) -> Response:
        if self.filename.isascii():
            escaped = self.filename.replace("\\", "\\\\").replace('"', '\\"')
            filename_header = f'filename="{escaped}"'
        else:
            filename_header = "filename*=UTF-8''" + quote(self.filename, safe="")
        return Response(self.payload, media_type=self.media_type, headers={
            "Content-Disposition": f"{self.disposition}; {filename_header}",
        })


@dataclass
class _PendingDownload:
    file: Download
    expires_at: float
    expiry: asyncio.TimerHandle


class DownloadStore:
    """Owned by one HTTP event loop; operations do not yield while claiming tokens."""

    def __init__(self, ttl: float = 300) -> None:
        self._loop = asyncio.get_running_loop()
        self._ttl = ttl
        self._downloads: dict[str, _PendingDownload] = {}

    def __len__(self) -> int:
        """Number of retained files, without performing cleanup."""
        return len(self._downloads)

    def add(self, file: Download) -> str:
        token = secrets.token_urlsafe(32)
        deadline = self._loop.time() + self._ttl
        expiry = self._loop.call_at(deadline, self.discard, token)
        self._downloads[token] = _PendingDownload(file, deadline, expiry)
        return token

    def take(self, token: str, filename: str) -> Download | None:
        pending = self._downloads.get(token)
        if pending is None or pending.file.filename != filename:
            return None
        self.discard(token)
        if self._loop.time() >= pending.expires_at:
            return None
        return pending.file

    def discard(self, token: str) -> None:
        pending = self._downloads.pop(token, None)
        if pending is not None:
            pending.expiry.cancel()

    def clear(self) -> None:
        for token in tuple(self._downloads):
            self.discard(token)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    store = DownloadStore()
    app.state.downloads = store
    try:
        yield
    finally:
        store.clear()


router = APIRouter(lifespan=lifespan)


@router.get("/downloads/{token}/{filename}", name="binary_download",
            response_class=Response, include_in_schema=False)
async def download_binary(request: Request, token: str, filename: str) -> Response:
    file = request.app.state.downloads.take(token, filename)
    if file is None:
        raise HTTPException(404, "Download token is invalid, expired, or already used",
                            headers={"Cache-Control": "no-store"})
    # Only the response retains the bytes after the atomic claim. Interrupted
    # transmission releases them without making the token reusable.
    response = file.response()
    response.headers["Cache-Control"] = "no-store"
    return response


def redirect_download(request: Request, template: str, file: Download) -> RedirectResponse:
    store = request.app.state.downloads
    token = store.add(file)
    try:
        path = request.app.url_path_for("binary_download", token=token, filename=file.filename)
        # Use the actual listener port, never the client-supplied Host header.
        port = request.scope["server"][1]
        url = f"http://127.0.0.1:{port}" + quote(str(path), safe="/")
        return RedirectResponse(template.replace("{url}", quote(url, safe="")),
                                status_code=303, headers={"Cache-Control": "no-store"})
    except Exception:
        store.discard(token)
        raise
