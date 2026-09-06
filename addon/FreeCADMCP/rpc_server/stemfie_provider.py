"""Resource provider adapter for the external STEMFIE workbench."""

from __future__ import annotations

import importlib
import inspect as python_inspect
import math
from pathlib import Path
import re
import sys
from typing import Any
import uuid

from rpc_server.unit_safety import (
    preferred_internal, preferred_quantity, preferred_vector,
    require_explicit_quantity,
)


class StemfieProviderError(RuntimeError):
    pass


_EXCLUDED_GROUPS = {"Attachment", "computed", "version"}
_EXCLUDED_TYPES = {"App::PropertyPythonObject", "Part::PropertyPartShape"}


def find_root(addon_dirs: list[Path]) -> Path | None:
    return next(
        (
            root for root in addon_dirs
            if (root / "freecad" / "stemfie" / "Stemfie.py").is_file()
        ),
        None,
    )


def _load(addon_dirs: list[Path]):
    root = find_root(addon_dirs)
    if root is None:
        raise StemfieProviderError("STEMFIE addon is not installed")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root, importlib.import_module("freecad.stemfie.Stemfie")


def _commands(addon_dirs: list[Path]):
    _, module = _load(addon_dirs)
    commands = {}
    for candidate in vars(module).values():
        if not python_inspect.isclass(candidate) or candidate is module.BaseCommand:
            continue
        if not issubclass(candidate, module.BaseCommand):
            continue
        if not getattr(candidate, "NAME", "") or not callable(
            getattr(candidate, "FUNCTION", None)
        ):
            continue
        # The Python class name is stable and avoids one upstream NAME value
        # containing spaces while still matching the workbench's public API.
        commands[candidate.__name__] = candidate
    return module, commands


def provider(addon_dirs: list[Path]) -> dict[str, Any] | None:
    root = find_root(addon_dirs)
    if root is None:
        return None
    return {
        "id": "stemfie", "kind": "parametric", "installed": True,
        "root": str(root), "actions": ["search", "inspect", "insert"],
    }


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _category(command) -> str:
    return command.FUNCTION.__module__.rsplit(".", 1)[-1]


def search(addon_dirs: list[Path], query: str) -> list[dict[str, Any]]:
    _, commands = _commands(addon_dirs)
    query_text = query.casefold().strip()
    tokens = _tokens(query)
    normalized_query = " ".join(tokens)
    matches = []
    for name, command in commands.items():
        label = str(command.menutext)
        description = str(command.tooltip)
        category = _category(command)
        searchable = f"{name} {command.NAME} {label} {description} {category}".casefold()
        normalized_searchable = " ".join(_tokens(searchable))
        score = 100 if (
            query_text and (
                query_text in searchable
                or normalized_query in normalized_searchable
            )
        ) else 0
        score += sum(10 for token in tokens if token in searchable)
        if not score and query_text:
            continue
        matches.append({
            "id": f"stemfie:{name}", "provider": "stemfie",
            "label": label, "description": description, "category": category,
            "kind": "parametric", "_score": score,
        })
    return matches


def _resolve(addon_dirs: list[Path], resource_id: str):
    module, commands = _commands(addon_dirs)
    name = resource_id.removeprefix("stemfie:")
    if not resource_id.startswith("stemfie:") or name not in commands:
        raise StemfieProviderError(f"Unknown STEMFIE resource: {resource_id}")
    return module, commands[name]


def _modes(obj, name: str) -> list[str]:
    modes = obj.getEditorMode(name)
    if isinstance(modes, int):
        return {
            0: [], 1: ["ReadOnly"], 2: ["Hidden"],
            3: ["ReadOnly", "Hidden"],
        }.get(modes, [str(modes)])
    return list(modes) if isinstance(modes, (list, tuple)) else [str(modes)]


def _value(value):
    if value is None or type(value) in (bool, int, float, str):
        return value
    if hasattr(value, "Value") and hasattr(value, "Unit"):
        return preferred_quantity(value)
    return str(value)


def _parameters(obj, original_properties: set[str]) -> dict[str, dict[str, Any]]:
    result = {}
    for name in obj.PropertiesList:
        property_type = obj.getTypeIdOfProperty(name)
        modes = _modes(obj, name)
        if (
            name in original_properties
            or obj.getGroupOfProperty(name) in _EXCLUDED_GROUPS
            or property_type in _EXCLUDED_TYPES
            or "ReadOnly" in modes or "Hidden" in modes
        ):
            continue
        parameter = {
            "type": property_type.removeprefix("App::Property"),
            "default": _value(getattr(obj, name)),
        }
        description = obj.getDocumentationOfProperty(name).strip()
        if description:
            parameter["description"] = description
        if property_type == "App::PropertyEnumeration":
            parameter["choices"] = list(obj.getEnumerationsOfProperty(name))
        result[name] = parameter
    return result


def _apply_properties(obj, properties: dict[str, Any], allowed: set[str], doc) -> None:
    unknown = set(properties) - allowed
    if unknown:
        raise StemfieProviderError(f"Unsupported STEMFIE properties: {sorted(unknown)}")
    for name, value in properties.items():
        try:
            require_explicit_quantity(obj, name, value)
            setattr(obj, name, value)
        except ValueError as exc:
            raise StemfieProviderError(str(exc)) from exc
        except Exception as exc:
            raise StemfieProviderError(f"Invalid {name}={value!r}: {exc}") from exc
    doc.recompute()


def _shape(app, obj) -> dict[str, Any]:
    shape = obj.Shape
    if shape.isNull() or not shape.isValid() or not math.isfinite(shape.Volume):
        raise StemfieProviderError("STEMFIE generated an invalid shape")
    return {
        "solids": len(shape.Solids),
        "volume": preferred_internal(app, shape.Volume, "mm^3"),
        "bounds": preferred_vector(
            app,
            [shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength],
        ),
    }


def _create(doc, command):
    obj = doc.addObject("Part::FeaturePython", command.NAME)
    original = set(obj.PropertiesList)
    command.FUNCTION(obj)
    return obj, _parameters(obj, original)


def inspect_resource(
    app, addon_dirs: list[Path], resource_id: str,
    properties: dict[str, Any] | None,
) -> dict[str, Any]:
    _, command = _resolve(addon_dirs, resource_id)
    previous = app.activeDocument()
    document_name = f"MCPStemfieInspect{uuid.uuid4().hex}"
    doc = app.newDocument(document_name)
    try:
        obj, parameters = _create(doc, command)
        _apply_properties(obj, properties or {}, set(parameters), doc)
        result = {
            "id": resource_id, "provider": "stemfie",
            "label": str(command.menutext),
            "description": str(command.tooltip),
            "category": _category(command),
            "parameters": parameters, "shape": _shape(app, obj),
        }
        if properties:
            result["effective_properties"] = {
                name: _value(getattr(obj, name)) for name in properties
            }
        return result
    finally:
        app.closeDocument(doc.Name)
        if previous is not None and previous.Name in app.listDocuments():
            app.setActiveDocument(previous.Name)


def insert(
    app, _gui, addon_dirs: list[Path], resource_id: str, document,
    properties: dict[str, Any] | None, attach_to: str | None,
) -> dict[str, Any]:
    if attach_to:
        raise StemfieProviderError(
            "STEMFIE attach_to is not supported; set placement or attachment with ExecutePython"
        )
    module, command = _resolve(addon_dirs, resource_id)
    doc = document
    doc.openTransaction("Insert MCP resource")
    try:
        obj, parameters = _create(doc, command)
        if getattr(app, "GuiUp", False):
            module.ViewProvider(obj.ViewObject, command.pixmap)
        _apply_properties(obj, properties or {}, set(parameters), doc)
        shape = _shape(app, obj)
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    result = {
        "resource_id": resource_id, "document": doc.Name,
        "object": {"name": obj.Name, "label": obj.Label, "type": obj.TypeId},
        "category": _category(command),
        "properties": {
            name: _value(getattr(obj, name)) for name in (properties or {})
        },
        "shape": shape,
    }
    if "Code" in obj.PropertiesList:
        result["code"] = str(obj.Code)
    return result
