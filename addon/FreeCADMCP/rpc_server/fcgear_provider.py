"""Resource provider adapter for the external FCGear workbench."""

from __future__ import annotations

import importlib
import inspect as python_inspect
import math
from pathlib import Path
import re
import sys
import uuid
from typing import Any

from rpc_server.unit_safety import (
    preferred_internal, preferred_quantity, preferred_vector,
    require_explicit_quantity,
)


class FCGearProviderError(RuntimeError):
    pass


_UNSUPPORTED_COMMANDS = {"GearConnector", "PlanetaryGear"}
_EXCLUDED_GROUPS = {"Attachment", "computed", "version"}
_EXCLUDED_TYPES = {"App::PropertyPythonObject", "Part::PropertyPartShape"}


def find_root(addon_dirs: list[Path]) -> Path | None:
    return next(
        (
            root for root in addon_dirs
            if (root / "freecad" / "gears" / "commands.py").is_file()
        ),
        None,
    )


def _load(addon_dirs: list[Path]):
    root = find_root(addon_dirs)
    if root is None:
        raise FCGearProviderError("FCGear addon is not installed")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    module = importlib.import_module("freecad.gears.commands")
    return root, module


def _commands(addon_dirs: list[Path]):
    _, module = _load(addon_dirs)
    commands = {}
    for candidate in vars(module).values():
        if not python_inspect.isclass(candidate) or candidate is module.BaseCommand:
            continue
        if not issubclass(candidate, module.BaseCommand):
            continue
        name = getattr(candidate, "NAME", "")
        if not name or name in _UNSUPPORTED_COMMANDS or candidate.GEAR_FUNCTION is None:
            continue
        commands[name] = candidate
    return module, commands


def provider(addon_dirs: list[Path]) -> dict[str, Any] | None:
    root = find_root(addon_dirs)
    if root is None:
        return None
    return {
        "id": "fcgear", "kind": "parametric", "installed": True,
        "root": str(root), "actions": ["search", "inspect", "insert"],
    }


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def search(addon_dirs: list[Path], query: str) -> list[dict[str, Any]]:
    _, commands = _commands(addon_dirs)
    query_text = query.casefold().strip()
    tokens = _tokens(query)
    matches = []
    for name, command in commands.items():
        label = str(command.MenuText)
        description = str(command.ToolTip)
        text = f"{name} {label} {description}".casefold()
        score = (100 if query_text and query_text in text else 0)
        score += sum(10 for token in tokens if token in text)
        if not score and query_text:
            continue
        matches.append({
            "id": f"fcgear:{name}", "provider": "fcgear",
            "label": label, "description": description,
            "kind": "parametric", "_score": score,
        })
    return matches


def _resolve(addon_dirs: list[Path], resource_id: str):
    module, commands = _commands(addon_dirs)
    name = resource_id.removeprefix("fcgear:")
    if not resource_id.startswith("fcgear:") or name not in commands:
        raise FCGearProviderError(f"Unknown FCGear resource: {resource_id}")
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
        result[name] = {
            "type": property_type.removeprefix("App::Property"),
            "default": _value(getattr(obj, name)),
        }
    return result


def _apply_properties(obj, properties: dict[str, Any], allowed: set[str], doc) -> None:
    unknown = set(properties) - allowed
    if unknown:
        raise FCGearProviderError(f"Unsupported FCGear properties: {sorted(unknown)}")
    for name, value in properties.items():
        try:
            require_explicit_quantity(obj, name, value)
            setattr(obj, name, value)
        except ValueError as exc:
            raise FCGearProviderError(str(exc)) from exc
        except Exception as exc:
            raise FCGearProviderError(f"Invalid {name}={value!r}: {exc}") from exc
    doc.recompute()


def _shape(app, obj) -> dict[str, Any]:
    shape = obj.Shape
    if shape.isNull() or not shape.isValid() or not math.isfinite(shape.Volume):
        raise FCGearProviderError("FCGear generated an invalid shape")
    return {
        "solids": len(shape.Solids),
        "volume": preferred_internal(app, shape.Volume, "mm^3"),
        "bounds": preferred_vector(
            app,
            [shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength],
        ),
    }


def inspect_resource(
    app, addon_dirs: list[Path], resource_id: str,
    properties: dict[str, Any] | None,
) -> dict[str, Any]:
    module, command = _resolve(addon_dirs, resource_id)
    previous = app.activeDocument()
    document_name = f"MCPFCGearInspect{uuid.uuid4().hex}"
    doc = app.newDocument(document_name)
    try:
        probe = doc.addObject("Part::FeaturePython", command.NAME)
        original = set(probe.PropertiesList)
        command.GEAR_FUNCTION(probe)
        parameters = _parameters(probe, original)
        _apply_properties(probe, properties or {}, set(parameters), doc)
        result = {
            "id": resource_id, "provider": "fcgear",
            "label": str(command.MenuText), "description": str(command.ToolTip),
            "parameters": parameters, "shape": _shape(app, probe),
        }
        if properties:
            result["effective_properties"] = {
                name: _value(getattr(probe, name)) for name in properties
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
        raise FCGearProviderError("FCGear attach_to is not supported; set attachment with ExecutePython")
    module, command = _resolve(addon_dirs, resource_id)
    doc = document
    doc.openTransaction("Insert MCP resource")
    try:
        probe = doc.addObject("Part::FeaturePython", command.NAME)
        original = set(probe.PropertiesList)
        if getattr(app, "GuiUp", False):
            module.ViewProviderGear(probe.ViewObject, command.Pixmap)
        command.GEAR_FUNCTION(probe)
        parameters = _parameters(probe, original)
        _apply_properties(probe, properties or {}, set(parameters), doc)
        shape = _shape(app, probe)
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    computed = {
        name: _value(getattr(probe, name))
        for name in ("pitch_diameter", "addendum_diameter", "root_diameter")
        if name in probe.PropertiesList
    }
    return {
        "resource_id": resource_id, "document": doc.Name,
        "object": {"name": probe.Name, "label": probe.Label, "type": probe.TypeId},
        "properties": {
            name: _value(getattr(probe, name)) for name in (properties or {})
        },
        "computed": computed, "shape": shape,
    }
