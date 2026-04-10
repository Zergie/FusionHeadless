"""Search Fusion API documentation by class/member names and docstrings.

This tool introspects the `adsk` module available in Fusion and returns a bounded
set of matches with structured metadata.
"""

import inspect
import re
import traceback
from types import FunctionType, ModuleType

MAX_RESULTS = 3
ALLOWED_CATEGORIES = ["class_name", "member_name", "description", "all"]


def get_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "search_term": {
                "type": "string",
                "description": (
                    "Search text. Optional prefixes: 'namespace.term' or "
                    "'namespace.class.term'. For non-description categories, "
                    "only text before first whitespace is used."
                )
            },
            "category": {
                "type": "string",
                "enum": ALLOWED_CATEGORIES,
                "description": "Search category. Defaults to 'all'."
            }
        },
        "required": ["search_term"]
    }


def _short_description(member: property | FunctionType, member_name: str) -> dict:
    doc = member.__doc__ or ""
    first_sentence = doc[:doc.find(".")].strip() if "." in doc else doc.strip()
    return {"name": member_name, "doc": first_sentence}


def _class_doc(class_obj: type, namespace_name: str) -> dict:
    result = {
        "type": "class",
        "name": class_obj.__name__,
        "namespace": f"adsk.{namespace_name}",
        "doc": class_obj.__doc__
    }
    properties = []
    functions = []
    for member_name, member in class_obj.__dict__.items():
        if member_name.startswith("_") or member_name in ["thisown", "cast"]:
            continue
        if isinstance(member, property):
            properties.append(_short_description(member, member_name))
        elif isinstance(member, FunctionType):
            functions.append(_short_description(member, member_name))

    if properties:
        result["properties"] = properties
    if functions:
        result["functions"] = functions
    return result


def _property_doc(prop: property, prop_name: str, class_name: str, namespace_name: str) -> dict:
    result = {
        "type": "property",
        "name": prop_name,
        "class": class_name,
        "namespace": f"adsk.{namespace_name}",
        "doc": prop.__doc__
    }
    if prop.fset is None:
        result["readonly"] = True
    return result


def _function_doc(func: FunctionType, class_name: str, namespace_name: str) -> dict:
    result = {
        "type": "function",
        "name": func.__name__,
        "class": class_name,
        "namespace": f"adsk.{namespace_name}",
        "doc": func.__doc__
    }

    signature_str = str(inspect.signature(func))
    if signature_str.startswith("(self"):
        signature_str = signature_str.replace("(self, ", "(").replace("(self)", "()")

    signature_str = signature_str.replace("'", "")
    signature_str = signature_str.replace("::", ".")
    signature_str = re.sub(r"adsk\.core\.Ptr<([^>]+)>", r"\1", signature_str)

    result["signature"] = signature_str
    return result


def _parse_search(search_term: str, category: str) -> tuple[str | None, str | None, str, str | None]:
    normalized = search_term.lower().strip()

    if normalized.startswith("adsk."):
        normalized = normalized[5:]

    namespace_prefix = None
    class_name_prefix = None

    if "." in normalized:
        namespace_prefix, normalized = normalized.split(".", 1)

    if "." in normalized:
        class_name_prefix, normalized = normalized.split(".", 1)

    ignored_term = None
    if category != "description":
        parts = re.split(r"\s", normalized, 1)
        normalized = parts[0] if parts else ""
        ignored_term = parts[1] if len(parts) > 1 else None

    return namespace_prefix, class_name_prefix, normalized, ignored_term


def handle(query: dict, app, adsk) -> dict:
    """Search Fusion API docs from module/class/member metadata."""
    try:
        search_term = query.get("search_term")
        category = query.get("category", "all")

        if not isinstance(search_term, str) or not search_term.strip():
            return {
                "error": True,
                "message": "Missing or empty 'search_term'",
                "matches": [],
                "count": 0
            }

        if not isinstance(category, str):
            return {
                "error": True,
                "message": "Invalid 'category' type; expected string",
                "matches": [],
                "count": 0
            }

        category = category.lower().strip()
        if category not in ALLOWED_CATEGORIES:
            return {
                "error": True,
                "message": f"Invalid category '{category}'. Allowed: class_name, member_name, description, all",
                "matches": [],
                "count": 0
            }

        namespace_prefix, class_name_prefix, normalized, ignored_term = _parse_search(search_term, category)
        if not normalized:
            return {
                "error": True,
                "message": "Empty search term after normalization",
                "matches": [],
                "count": 0
            }

        exact_matches = []
        partial_matches = []

        for namespace_name, namespace in adsk.__dict__.items():
            if namespace_name.startswith("_") or not isinstance(namespace, ModuleType):
                continue
            if namespace_prefix and namespace_prefix != namespace_name:
                continue

            for class_name_raw, class_obj in namespace.__dict__.items():
                if class_name_raw.startswith("_") or not isinstance(class_obj, type):
                    continue

                class_name = class_name_raw.lower()
                if class_name_prefix and class_name_prefix != class_name:
                    continue

                if category in ["class_name", "all"]:
                    if normalized == class_name:
                        exact_matches.append((namespace_name, class_obj, None))
                    elif normalized in class_name:
                        partial_matches.append((namespace_name, class_obj, None))

                if category in ["description", "all"]:
                    class_doc = class_obj.__doc__.lower() if class_obj.__doc__ else ""
                    if normalized in class_doc:
                        partial_matches.append((namespace_name, class_obj, None))

                if category in ["member_name", "description", "all"]:
                    for member_name_raw, member_obj in class_obj.__dict__.items():
                        if member_name_raw.startswith("_") or not isinstance(member_obj, (property, FunctionType)):
                            continue
                        member_name = member_name_raw.lower()
                        if member_name in ["thisown", "cast"]:
                            continue

                        if category in ["member_name", "all"]:
                            if normalized == member_name:
                                exact_matches.append((namespace_name, class_obj, member_obj))
                            elif normalized in member_name:
                                partial_matches.append((namespace_name, class_obj, member_obj))

                        if category in ["description", "all"]:
                            member_doc = member_obj.__doc__.lower() if member_obj.__doc__ else ""
                            if normalized in member_doc:
                                partial_matches.append((namespace_name, class_obj, member_obj))

                        if len(exact_matches) >= MAX_RESULTS:
                            break

                if len(exact_matches) >= MAX_RESULTS:
                    break

            if len(exact_matches) >= MAX_RESULTS:
                break

        matches = []
        for namespace_name, class_obj, member_obj in (exact_matches + partial_matches)[:MAX_RESULTS]:
            if member_obj is None:
                matches.append(_class_doc(class_obj, namespace_name))
            elif isinstance(member_obj, property):
                prop_name = "unknown"
                for name, member in class_obj.__dict__.items():
                    if member is member_obj:
                        prop_name = name
                        break
                matches.append(_property_doc(member_obj, prop_name, class_obj.__name__, namespace_name))
            elif isinstance(member_obj, FunctionType):
                matches.append(_function_doc(member_obj, class_obj.__name__, namespace_name))

        response = {
            "error": False,
            "message": f"Found {len(matches)} result{'s' if len(matches) != 1 else ''}",
            "count": len(matches),
            "category": category,
            "search_term": normalized,
            "matches": matches,
        }
        if ignored_term:
            response["ignored_after_whitespace"] = ignored_term
        return response

    except Exception as exc:
        return {
            "error": True,
            "message": "Error searching documentation",
            "details": str(exc),
            "traceback": traceback.format_exc(),
            "matches": [],
            "count": 0
        }


if __name__ == "__main__":
    from _client_ import test
    test(__file__, {"search_term": "Application", "category": "class_name"}, timeout=30)
