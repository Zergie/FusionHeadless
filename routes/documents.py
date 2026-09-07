"""Documents helpers and operations for FusionHeadless."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from routing import ApiParameter, api_route
from fusion_support import _value


@api_route("/document", methods=("POST",))
def document_route(
    context: Any,
    open: Annotated[
        str | None,
        ApiParameter("Fusion data-file identifier to open."),
    ] = None,
    close: Annotated[
        bool | None,
        ApiParameter("Close the active document and optionally save changes."),
    ] = None,
) -> Any:
    """Perform the legacy document operation on Fusion's UI thread."""
    app, adsk = context.app, context.adsk
    if open is not None:
        identity = open.strip()
        active = _value(app, "activeDocument")
        if (_value(_value(active, "dataFile"), "id") == identity):
            return "File is already active."
        file = _value(_value(app, "data"), "findFileById")(identity)
        if not file:
            raise RuntimeError(f"File with ID '{identity}' not found.")
        _value(app, "documents").open(file)

        async def wait_until_active() -> None:
            while _value(_value(_value(app, "activeDocument"), "dataFile"), "id") != identity:
                adsk.doEvents()
                await asyncio.sleep(0.5)

        try:
            asyncio.run(asyncio.wait_for(wait_until_active(), timeout=30))
            return "File opened successfully."
        except asyncio.TimeoutError as error:
            raise RuntimeError(
                f"Failed to open file with ID '{identity}' within 30 seconds."
            ) from error
    elif close is not None:
        active = _value(app, "activeDocument")
        if active is not None and _value(active, "dataFile") is not None:
            active.close(close)
            return "File closed successfully."
        return "No active document to close."
    else:
        raise ValueError("Document operation must specify open or close.")
