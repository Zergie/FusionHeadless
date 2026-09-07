"""List documents helpers and operations for FusionHeadless."""

from __future__ import annotations

from typing import Any
from fusion_support import _value
from mcp.registry import mcp_tool


@mcp_tool(
    "list_open_documents",
    description="List all currently open Fusion 360 documents.",
    input_schema={"type": "object", "properties": {}},
)
def mcp_list_open_documents(query: dict[str, Any], context: Any) -> dict[str, Any]:
    app = context.app
    documents = []
    for index in range(_value(_value(app, "documents"), "count", 0)):
        doc = app.documents.item(index)
        try:
            _ = doc.documentReferences
        except Exception:
            continue
        data_file = _value(doc, "dataFile")
        documents.append({
            "name": _value(doc, "name"),
            "is_active": bool(_value(doc, "isActive", False)),
            "id": _value(data_file, "id") if data_file else None,
        })
    active = _value(app, "activeDocument")
    return {"count": len(documents), "active_document": _value(active, "name"),
            "documents": documents}
