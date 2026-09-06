"""Provider-based discovery and insertion of installed FreeCAD resources."""

from __future__ import annotations

import importlib
import math
import os
from pathlib import Path
import re
import sys
from typing import Any

from rpc_server import fcgear_provider


COMPONENT_SUFFIXES = {".fcstd", ".step", ".stp"}
_FILE_CACHE: dict[str, list[Path]] = {}


class ResourceOperationError(RuntimeError):
    pass


def _mod_roots(app) -> list[Path]:
    roots = []
    for value in (app.getUserAppDataDir(), app.getHomePath()):
        root = Path(value).resolve() / "Mod"
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def _addon_dirs(app) -> list[Path]:
    seen: set[str] = set()
    result = []
    for root in _mod_roots(app):
        for addon in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if addon.is_dir() and addon.name.casefold() not in seen:
                seen.add(addon.name.casefold())
                result.append(addon.resolve())
    return result


def _fasteners_root(app) -> Path | None:
    return next((root for root in _addon_dirs(app) if (root / "FastenersCmd.py").is_file()), None)


def _component_files(root: Path) -> list[Path]:
    key = str(root)
    if key not in _FILE_CACHE:
        files = []
        for directory, names, filenames in os.walk(root):
            names[:] = [name for name in names if name != ".git"]
            files.extend(
                Path(directory, name) for name in filenames
                if Path(name).suffix.casefold() in COMPONENT_SUFFIXES
            )
        _FILE_CACHE[key] = sorted(files, key=lambda path: str(path).casefold())
    return _FILE_CACHE[key]


def _file_providers(app) -> dict[str, Path]:
    providers = {}
    user_mod = Path(app.getUserAppDataDir()).resolve() / "Mod"
    user_addons = (
        sorted(user_mod.iterdir(), key=lambda path: path.name.casefold())
        if user_mod.is_dir() else []
    )
    excluded = {
        candidate for candidate in (
            _fasteners_root(app), fcgear_provider.find_root(_addon_dirs(app)),
        ) if candidate is not None
    }
    for root in user_addons:
        if not root.is_dir():
            continue
        root = root.resolve()
        if root in excluded:
            continue
        if root.name.casefold() in {"parts_library", "freecad-library"}:
            providers["parts_library"] = root
        elif _component_files(root):
            providers[f"files:{root.name}"] = root
    return providers


def _fastener_modules(app):
    root = _fasteners_root(app)
    if root is None:
        raise ResourceOperationError("Fasteners addon is not installed")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root, importlib.import_module("FastenersCmd")


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _score(query: str, text: str, *, ignore_dimensions=False) -> int:
    query_text, text_value = query.casefold().strip(), text.casefold()
    tokens = _tokens(query_text)
    if ignore_dimensions:
        tokens = [token for token in tokens if not token.isdigit() and not re.fullmatch(r"m\d+", token)]
    score = 100 if query_text and query_text in text_value else 0
    score += sum(10 for token in tokens if token in text_value)
    return score if score or not query_text else -1


def _metric_diameters(query: str) -> list[str]:
    """Extract metric fastener diameters without treating ordinary words as sizes."""
    return [
        "M" + match.group(1)
        for match in re.finditer(r"(?<![A-Za-z0-9])M\s*(\d+(?:\.\d+)?)", query, re.I)
    ]


def _fastener_matches(app, query: str) -> list[dict[str, Any]]:
    _, module = _fastener_modules(app)
    matches = []
    requested_diameters = _metric_diameters(query)
    for standard, data in module.FSScrewCommandTable.items():
        if requested_diameters:
            supported = {
                str(value).strip("()").upper()
                for value in module.screwMaker.GetAllDiams(standard)
            }
            if not all(diameter in supported for diameter in requested_diameters):
                continue
        description = module.FSGetDescription(standard)
        group = str(data[module.CMD_GROUP])
        score = _score(query, f"{standard} {description} {group}", ignore_dimensions=True)
        if score >= 0:
            matches.append({
                "id": f"fasteners:{standard}",
                "provider": "fasteners",
                "label": description,
                "group": group,
                "kind": "parametric",
                "_score": score,
            })
    return matches


def _file_matches(provider: str, root: Path, query: str) -> list[dict[str, Any]]:
    matches = []
    for path in _component_files(root):
        relative = path.relative_to(root).as_posix()
        score = _score(query, relative.replace("_", " ").replace("-", " "))
        if score >= 0:
            matches.append({
                "id": f"{provider}:{relative}",
                "provider": provider,
                "label": path.stem,
                "path": relative,
                "kind": path.suffix.lstrip(".").casefold(),
                "_score": score,
            })
    return matches


def _providers(app) -> list[dict[str, Any]]:
    result = []
    fasteners = _fasteners_root(app)
    if fasteners is not None:
        result.append({
            "id": "fasteners", "kind": "parametric", "installed": True,
            "root": str(fasteners), "actions": ["search", "inspect", "insert"],
        })
    fcgear = fcgear_provider.provider(_addon_dirs(app))
    if fcgear is not None:
        result.append(fcgear)
    for provider, root in _file_providers(app).items():
        result.append({
            "id": provider, "kind": "file", "installed": True,
            "root": str(root), "actions": ["search", "inspect", "insert"],
        })
    return result


def _split_file_id(app, resource_id: str) -> tuple[str, Path, Path]:
    providers = _file_providers(app)
    for provider, root in providers.items():
        prefix = provider + ":"
        if resource_id.startswith(prefix):
            relative = resource_id[len(prefix):]
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ResourceOperationError("Resource path escapes its provider") from exc
            if not path.is_file() or path.suffix.casefold() not in COMPONENT_SUFFIXES:
                raise ResourceOperationError(f"Resource does not exist: {resource_id}")
            return provider, root, path
    raise ResourceOperationError(f"Unknown resource: {resource_id}")


def _fastener_details(app, resource_id: str, properties: dict | None) -> dict[str, Any]:
    _, module = _fastener_modules(app)
    standard = resource_id.removeprefix("fasteners:")
    if standard not in module.FSScrewCommandTable:
        raise ResourceOperationError(f"Unknown fastener standard: {standard}")
    maker = module.screwMaker
    diameters = maker.GetAllDiams(standard)
    result = {
        "id": resource_id,
        "provider": "fasteners",
        "label": module.FSGetDescription(standard),
        "parameters": sorted(module.FSGetParams(standard)),
        "diameters": diameters,
    }
    diameter = (properties or {}).get("Diameter")
    if diameter is not None:
        if diameter not in diameters:
            raise ResourceOperationError(f"Invalid Diameter {diameter!r}")
        if "Length" in module.FSGetParams(standard):
            result["lengths"] = maker.GetAllLengths(standard, diameter)
    return result


def _file_details(app, resource_id: str) -> dict[str, Any]:
    provider, root, path = _split_file_id(app, resource_id)
    siblings = [
        candidate.relative_to(root).as_posix()
        for candidate in path.parent.glob(path.stem + ".*")
        if candidate.suffix.casefold() in COMPONENT_SUFFIXES
    ]
    license_path = next(
        (candidate for pattern in ("LICENSE*", "LICENCE*") for candidate in root.glob(pattern)),
        None,
    )
    return {
        "id": resource_id,
        "provider": provider,
        "path": str(path),
        "format": path.suffix.lstrip("."),
        "bytes": path.stat().st_size,
        "alternates": sorted(siblings),
        "license": str(license_path) if license_path else None,
    }


def _document(app, name: str | None):
    if not name:
        raise ResourceOperationError("document is required for insert")
    try:
        return app.getDocument(name)
    except Exception as exc:
        raise ResourceOperationError(f"Document is not open: {name}") from exc


def _attachment(doc, value: str | None):
    if not value:
        return None
    object_name, separator, subelement = value.rpartition(".")
    if not separator or not object_name or not re.fullmatch(r"(?:Edge|Face)\d+", subelement):
        raise ResourceOperationError("attach_to must look like ObjectName.Edge1 or ObjectName.Face1")
    obj = doc.getObject(object_name)
    if obj is None:
        raise ResourceOperationError(f"Attachment object does not exist: {object_name}")
    try:
        shape = obj.getSubObject(subelement)
    except Exception as exc:
        raise ResourceOperationError(f"Attachment subelement does not exist: {value}") from exc
    if shape is None:
        raise ResourceOperationError(f"Attachment subelement does not exist: {value}")
    return obj, [subelement]


def _set_fastener_properties(obj, properties: dict[str, Any], allowed: set[str], doc) -> None:
    unknown = set(properties) - allowed
    if unknown:
        raise ResourceOperationError(f"Unsupported fastener properties: {sorted(unknown)}")
    ordered = [name for name in ("Diameter", "Width", "Length") if name in properties]
    ordered += [name for name in properties if name not in ordered]
    for name in ordered:
        value = properties[name]
        if name == "Length" and "LengthCustom" in obj.PropertiesList:
            choices = obj.getEnumerationsOfProperty("Length")
            if str(value) not in choices:
                obj.Length = "Custom"
                obj.LengthCustom = value if isinstance(value, (int, float)) else str(value)
                continue
        try:
            setattr(obj, name, value)
        except Exception as exc:
            raise ResourceOperationError(f"Invalid {name}={value!r}: {exc}") from exc
        if name in {"Diameter", "Width"}:
            doc.recompute()


def _insert_fastener(app, resource_id, document, properties, attach_to) -> dict[str, Any]:
    _, module = _fastener_modules(app)
    standard = resource_id.removeprefix("fasteners:")
    if not resource_id.startswith("fasteners:") or standard not in module.FSScrewCommandTable:
        raise ResourceOperationError(f"Unknown fastener resource: {resource_id}")
    doc = _document(app, document)
    attachment = _attachment(doc, attach_to)
    doc.openTransaction("Insert MCP resource")
    try:
        obj = doc.addObject("Part::FeaturePython", module.screwMaker.GetTypeName(standard))
        module.FSScrewObject(obj, standard, attachment)
        if getattr(app, "GuiUp", False) and hasattr(module, "FSViewProviderTree"):
            module.FSViewProviderTree(obj.ViewObject)
        allowed = set(module.FSGetParams(standard)) | {"Invert", "Offset", "OffsetAngle"}
        _set_fastener_properties(obj, properties or {}, allowed, doc)
        doc.recompute()
        if obj.Shape.isNull() or not obj.Shape.isValid() or not math.isfinite(obj.Shape.Volume):
            raise ResourceOperationError("Fasteners generated an invalid shape")
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    effective = {
        name: str(getattr(obj, name))
        for name in ("Type", "Diameter", "Length", "Thread", "BaseObject")
        if name in obj.PropertiesList
    }
    return {
        "resource_id": resource_id,
        "document": doc.Name,
        "object": {"name": obj.Name, "label": obj.Label, "type": obj.TypeId},
        "properties": effective,
        "shape": {"solids": len(obj.Shape.Solids), "volume": obj.Shape.Volume},
    }


def _insert_file(app, resource_id, document) -> dict[str, Any]:
    _, _, path = _split_file_id(app, resource_id)
    doc = _document(app, document)
    before = {obj.Name for obj in doc.Objects}
    doc.openTransaction("Insert MCP resource")
    try:
        if path.suffix.casefold() == ".fcstd":
            doc.mergeProject(str(path))
        else:
            import Import
            Import.insert(str(path), doc.Name)
        doc.recompute()
        added = [obj for obj in doc.Objects if obj.Name not in before]
        if not added:
            raise ResourceOperationError("Resource insertion created no document objects")
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    return {
        "resource_id": resource_id,
        "document": doc.Name,
        "objects": [
            {"name": obj.Name, "label": obj.Label, "type": obj.TypeId}
            for obj in added[:50]
        ],
        "truncated": len(added) > 50,
    }


def resource_operations(
    app,
    gui,
    action: str,
    query: str | None = None,
    provider: str | None = None,
    resource_id: str | None = None,
    document: str | None = None,
    properties: dict[str, Any] | None = None,
    attach_to: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Dispatch one resource operation against installed provider adapters."""
    if action == "providers":
        return {"providers": _providers(app)}
    if action == "search":
        if not query:
            raise ResourceOperationError("query is required for search")
        matches = []
        installed = {item["id"] for item in _providers(app)}
        if provider in (None, "fasteners") and "fasteners" in installed:
            matches.extend(_fastener_matches(app, query))
        if provider in (None, "fcgear") and "fcgear" in installed:
            matches.extend(fcgear_provider.search(_addon_dirs(app), query))
        for current, root in _file_providers(app).items():
            if provider in (None, current):
                matches.extend(_file_matches(current, root, query))
        if provider is not None and provider not in installed:
            raise ResourceOperationError(f"Provider is not installed: {provider}")
        matches.sort(key=lambda item: (-item["_score"], item["label"].casefold()))
        for item in matches:
            item.pop("_score", None)
        return {"matches": matches[:limit], "truncated": len(matches) > limit}
    if action == "inspect":
        if not resource_id:
            raise ResourceOperationError("resource_id is required for inspect")
        if resource_id.startswith("fasteners:"):
            return _fastener_details(app, resource_id, properties)
        if resource_id.startswith("fcgear:"):
            return fcgear_provider.inspect_resource(
                app, _addon_dirs(app), resource_id, properties,
            )
        return _file_details(app, resource_id)
    if action == "insert":
        if not resource_id:
            raise ResourceOperationError("resource_id is required for insert")
        if resource_id.startswith("fasteners:"):
            return _insert_fastener(app, resource_id, document, properties, attach_to)
        if resource_id.startswith("fcgear:"):
            return fcgear_provider.insert(
                app, gui, _addon_dirs(app), resource_id, _document(app, document),
                properties, attach_to,
            )
        return _insert_file(app, resource_id, document)
    raise ResourceOperationError(f"Unsupported resource action: {action}")
