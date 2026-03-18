"""Generate typed Python wrapper modules from MCP Tool definitions.

Reads Tool objects (name, description, inputSchema) and writes one .py file per
tool into ``code_execution/tools/memory/``.  Each wrapper delegates to
``code_execution.bridge.call_tool`` so the generated code is usable both
in-process and inside a sandboxed subprocess.
"""

from __future__ import annotations

import keyword
import re
import textwrap
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# JSON-Schema → Python type mapping
# ---------------------------------------------------------------------------

_SCHEMA_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "boolean": "bool",
    "number": "float",
    "array": "list",
    "object": "dict",
}


def _schema_type_to_python(schema: dict[str, Any]) -> str:
    """Convert a JSON-Schema ``type`` field to a Python type hint string."""
    raw = schema.get("type", "Any")
    if isinstance(raw, list):
        # Union type, e.g. ["array", "string"]
        parts = [_SCHEMA_TYPE_MAP.get(t, "Any") for t in raw if t != "null"]
        return " | ".join(parts) if parts else "Any"
    return _SCHEMA_TYPE_MAP.get(raw, "Any")


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------


def _extract_params(input_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of parameter dicts from a JSON-Schema ``inputSchema``.

    Each dict has keys: name, type_hint, required, default, description.
    """
    properties: dict[str, Any] = input_schema.get("properties", {})
    required_set: set[str] = set(input_schema.get("required", []))
    params: list[dict[str, Any]] = []
    for name, prop in properties.items():
        safe_name = name + "_" if keyword.iskeyword(name) else name
        p: dict[str, Any] = {
            "name": safe_name,
            "original_name": name,
            "type_hint": _schema_type_to_python(prop),
            "required": name in required_set,
            "default": prop.get("default"),
            "description": prop.get("description", ""),
        }
        # Include enum values in description for documentation
        if "enum" in prop:
            p["description"] += f" (one of: {', '.join(repr(v) for v in prop['enum'])})"
        params.append(p)
    # Sort: required params first, then optional
    params.sort(key=lambda p: (not p["required"], p["name"]))
    return params


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def _generate_wrapper_source(
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
) -> str:
    """Return the full Python source for a single tool wrapper module."""
    params = _extract_params(input_schema)

    # Build function signature
    sig_parts: list[str] = []
    kwonly_parts: list[str] = []
    for p in params:
        hint = p["type_hint"]
        if p["required"]:
            sig_parts.append(f"{p['name']}: {hint}")
        else:
            default = repr(p["default"]) if p["default"] is not None else "None"
            if not p["required"] and p["default"] is None:
                hint = f"{hint} | None"
            kwonly_parts.append(f"{p['name']}: {hint} = {default}")

    # If there are both required and optional, use * separator
    all_parts = list(sig_parts)
    if kwonly_parts:
        if sig_parts:
            all_parts.append("*")
        all_parts.extend(kwonly_parts)

    signature = ",\n    ".join(all_parts)
    if signature:
        signature = "\n    " + signature + ",\n"

    # Build kwargs assembly (each line indented with 4 spaces inside function body)
    kwargs_lines: list[str] = []
    for p in params:
        if p["required"]:
            kwargs_lines.append(f'    kwargs["{p["original_name"]}"] = {p["name"]}')
        else:
            kwargs_lines.append(
                f'    if {p["name"]} is not None:\n'
                f'        kwargs["{p["original_name"]}"] = {p["name"]}'
            )

    kwargs_block = "\n".join(kwargs_lines) if kwargs_lines else "    pass"

    # Build parameter docstring lines
    param_docs = ""
    if params:
        doc_lines = []
        for p in params:
            opt = "" if p["required"] else " (optional)"
            desc = p["description"]
            doc_lines.append(f"        {p['name']}: {desc}{opt}")
        param_docs = "\n\n    Args:\n" + "\n".join(doc_lines)

    # Escape the description for use in a docstring
    safe_desc = description.replace('"""', r'\"\"\"')

    lines = [
        f'"""{tool_name} — {safe_desc}"""',
        "",
        "from __future__ import annotations",
        "",
        "from code_execution.bridge import call_tool",
        "",
        "",
        f"def {tool_name}({signature}) -> str:",
        f'    """{safe_desc}{param_docs}"""',
        "    kwargs: dict = {}",
        kwargs_block,
        f'    return call_tool("{tool_name}", **kwargs)',
        "",
    ]
    return "\n".join(lines)


def generate_wrappers(
    tools: list[Any],
    output_dir: Path | str,
) -> list[str]:
    """Generate wrapper modules for all tools.

    Parameters
    ----------
    tools:
        List of Tool objects (or any object with ``.name``, ``.description``,
        ``.inputSchema`` attributes).
    output_dir:
        Directory to write wrapper files into.

    Returns
    -------
    List of generated file names (without path).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated: list[str] = []
    export_names: list[str] = []

    for tool in tools:
        name: str = tool.name
        # Sanitize: only allow valid Python identifiers
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        if not safe_name.isidentifier():
            continue

        source = _generate_wrapper_source(
            tool_name=safe_name,
            description=tool.description,
            input_schema=tool.inputSchema,
        )

        filename = f"{safe_name}.py"
        (output_dir / filename).write_text(source, encoding="utf-8")
        generated.append(filename)
        export_names.append(safe_name)

    # Generate __init__.py that re-exports all tool functions
    init_lines = [
        "# Auto-generated by code_execution.generate — do not edit manually.",
        "",
    ]
    for func_name in sorted(export_names):
        init_lines.append(f"from .{func_name} import {func_name}")
    init_lines.append("")

    (output_dir / "__init__.py").write_text("\n".join(init_lines), encoding="utf-8")

    return generated
