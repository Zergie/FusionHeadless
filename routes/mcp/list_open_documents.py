"""List all currently open Fusion 360 documents."""


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {}
    }


def _safe_datafile_fields(doc) -> dict:
    data_file = getattr(doc, "dataFile", None)
    if not data_file:
        return {
            "id": None,
        }

    return {
        "id": getattr(data_file, "id", None),
    }


def _is_top_level_document(doc) -> bool:
    """Top-level docs allow access to documentReferences; non-top-level docs throw."""
    try:
        _ = doc.documentReferences
        return True
    except Exception:
        return False


def handle(query: dict, app, adsk) -> dict:
    """Return open top-level documents and mark the active one."""
    active = app.activeDocument

    documents = []
    for i in range(app.documents.count):
        doc = app.documents.item(i)

        if not _is_top_level_document(doc):
            continue

        item = {
            "name": getattr(doc, "name", None),
            "is_active": bool(getattr(doc, "isActive", False)),
        }
        item.update(_safe_datafile_fields(doc))
        documents.append(item)

    return {
        "count": len(documents),
        "active_document": getattr(active, "name", None) if active else None,
        "documents": documents,
    }


if __name__ == "__main__":
    from _client_ import test
    test(__file__, {}, timeout=30)
