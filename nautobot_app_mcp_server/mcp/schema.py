"""JSON Schema auto-generation from Python function signatures."""

from __future__ import annotations

import inspect
from typing import Any, Callable, get_type_hints

# Map Python types to JSON Schema type strings
_PYTHON_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    bool: "boolean",
    str: "string",
    list: "array",
    dict: "object",
}


def _python_type_to_json_schema(hint: type | None) -> dict[str, Any]:
    """Convert a Python type hint to a JSON Schema dict."""
    if hint is None:
        return {"type": "string"}  # Safe default for unannotated params

    # Handle Optional[X] (Union[X, None] or X | None)
    origin = getattr(hint, "__origin__", None)
    if origin is not None:
        # typing.Union[...] or X | Y
        args = getattr(hint, "__args__", ())
        if type(None) in args and len(args) == 2:
            # Optional[X] — derive type from X, add default: None
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                schema = _python_type_to_json_schema(non_none[0])
                schema["default"] = None
                return schema

    # Handle list[X], dict[K, V]
    if origin is not None:
        args = getattr(hint, "__args__", ())
        if hint in (list, dict):
            return {"type": "object"}
        if origin is list and args:
            return {"type": "array", "items": _python_type_to_json_schema(args[0])}
        if origin is dict and len(args) == 2:
            return {"type": "object"}
        return {"type": "object"}  # Complex generics: fallback

    # Handle builtin types
    if hint in _PYTHON_TYPE_MAP:
        return {"type": _PYTHON_TYPE_MAP[hint]}

    # Fallback for unknown types (classes, etc.)
    return {"type": "string"}


def func_signature_to_input_schema(func: Callable) -> dict[str, Any]:
    """Derive a JSON Schema input_schema from a Python function signature.

    Reads all parameters except ``ctx`` (ToolContext) and generates a
    JSON Schema with ``required`` fields (those without defaults) and
    ``properties`` with ``default`` values for optional fields.

    Args:
        func: An async function with type-annotated parameters.

    Returns:
        A JSON Schema dict with type, properties, required, additionalProperties.

    Raises:
        RuntimeWarning: If ``inspect.signature`` fails on a built-in/C extension.
    """
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError) as exc:
        import warnings

        warnings.warn(f"Could not inspect signature of {func}: {exc}", RuntimeWarning)
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

    try:
        type_hints = get_type_hints(func)
    except Exception:
        # Forward reference resolution failed — use empty dict
        type_hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name == "ctx":
            # ToolContext is injected by FastMCP, not by the client — skip it
            continue

        hint = type_hints.get(name)
        schema = _python_type_to_json_schema(hint)

        if param.default is not inspect.Parameter.empty:
            schema["default"] = param.default
        else:
            required.append(name)

        properties[name] = schema

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
