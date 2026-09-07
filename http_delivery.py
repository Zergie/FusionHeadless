"""Compile route delivery metadata into child-side response preparation."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import Response

from binary_downloads import Download, redirect_download, validate_redirect_url
from routing import RouteDefinition, RouteParameter


ResponseFactory = Callable[[Any], Any]
PrepareResponse = Callable[[Request, dict[str, Any]], ResponseFactory]


def compile_delivery(definition: RouteDefinition, parameters: tuple[RouteParameter, ...]
                     ) -> tuple[PrepareResponse, dict[str, Any]]:
    """Resolve server-owned controls once, before accepting requests."""
    redirects = [parameter for parameter in parameters if parameter.redirect]
    if len(redirects) > 1:
        raise TypeError(f"Route '{definition.path}' may declare only one RedirectURL parameter")
    redirect = redirects[0] if redirects else None
    binary = definition.binary
    if redirect is not None and (binary is None or redirect.annotation != str | None
                                 or redirect.default is not None):
        raise TypeError(f"Route '{definition.path}' RedirectURL parameter '{redirect.name}' must be an optional str defaulting to None on a binary route")
    if binary is None:
        def prepare_json(request: Request, arguments: dict[str, Any]) -> ResponseFactory:
            return lambda result: {"status": "ok", "result": result}
        return prepare_json, {}

    responses: dict[int, Any] = {
        200: {
            "description": "Successful binary response",
            "content": {binary.media_type: {"schema": {"type": "string", "format": "binary"}}},
            "headers": {"Content-Disposition": {
                "description": "Suggested output filename.", "schema": {"type": "string"},
            }},
        },
    }
    if redirect is not None:
        responses[303] = {
            "description": "Redirect to the supplied URL with a five-minute, single-use download URL",
            "headers": {"Location": {"schema": {"type": "string"}}},
        }

    def prepare_binary(request: Request, arguments: dict[str, Any]) -> ResponseFactory:
        template = arguments.pop(redirect.name, None) if redirect is not None else None
        if template is not None:
            try:
                validate_redirect_url(template)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        filename = binary.resolve_filename(arguments)

        def respond(payload: Any) -> Response:
            if not isinstance(payload, bytes):
                raise RuntimeError("Fusion binary route returned a non-binary response")
            file = Download(payload, binary.media_type, filename, binary.disposition)
            if template is None:
                return file.response()
            return redirect_download(request, template, file)

        return respond

    return prepare_binary, {"response_class": Response, "responses": responses}
