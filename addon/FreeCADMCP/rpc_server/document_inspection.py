"""Compact, read-only inspection of native FreeCAD document structure."""


MAX_TREE_OBJECTS = 500
MAX_PROPERTY_ITEMS = 100
MAX_TEXT = 1000
BENIGN_STATES = {"Up-to-date", "Expanded"}


class DocumentInspectionError(ValueError):
    """An invalid document inspection request."""


def _document(app, name):
    if name:
        try:
            doc = app.getDocument(name)
        except Exception as exc:
            raise DocumentInspectionError(f"Document {name!r} is not open") from exc
    else:
        doc = app.activeDocument()
    if doc is None:
        raise DocumentInspectionError("No active document")
    return doc


def _modified(gui, doc):
    gui_doc = gui.getDocument(doc.Name)
    return bool(gui_doc.Modified) if gui_doc is not None else False


def _metadata(app, gui, doc):
    active = app.activeDocument()
    return {
        "name": doc.Name,
        "label": doc.Label,
        "path": doc.FileName or None,
        "active": active is not None and active.Name == doc.Name,
        "modified": _modified(gui, doc),
        "object_count": len(doc.Objects),
    }


def _children(obj, object_names):
    try:
        claimed = obj.ViewObject.claimChildren()
    except Exception:
        claimed = []
    return [
        child for child in claimed
        if getattr(child, "Name", None) in object_names and child is not obj
    ]


def _states(obj):
    try:
        return [state for state in obj.State if state not in BENIGN_STATES]
    except Exception:
        return []


def _node(obj, children=None):
    node = {"name": obj.Name, "type": obj.TypeId}
    if obj.Label != obj.Name:
        node["label"] = obj.Label
    try:
        if not obj.ViewObject.Visibility:
            node["hidden"] = True
    except Exception:
        pass
    states = _states(obj)
    if states:
        node["state"] = states
    if children:
        node["children"] = children
    return node


def _tree(doc, max_depth):
    objects = list(doc.Objects)
    object_names = {obj.Name for obj in objects}
    children = {obj.Name: _children(obj, object_names) for obj in objects}
    claimed = {child.Name for group in children.values() for child in group}
    roots = [obj for obj in objects if obj.Name not in claimed]
    reachable = set()

    def mark_reachable(obj):
        if obj.Name in reachable:
            return
        reachable.add(obj.Name)
        for child in children[obj.Name]:
            mark_reachable(child)

    for root in roots:
        mark_reachable(root)
    # A malformed or custom view-provider cycle has no natural root. Include
    # one representative so it is visible instead of silently disappearing.
    for obj in objects:
        if obj.Name not in reachable:
            roots.append(obj)
            mark_reachable(obj)

    emitted = set()
    truncated = len(objects) > MAX_TREE_OBJECTS

    def visit(obj, depth, ancestors):
        nonlocal truncated
        if len(emitted) >= MAX_TREE_OBJECTS:
            truncated = True
            return None
        if obj.Name in ancestors:
            return {"name": obj.Name, "cycle": True}
        if obj.Name in emitted:
            return {"name": obj.Name, "reference": True}
        emitted.add(obj.Name)
        descendants = children[obj.Name]
        if depth >= max_depth:
            node = _node(obj)
            if descendants:
                node["child_count"] = len(descendants)
            return node
        nested = [
            child_node for child in descendants
            if (child_node := visit(child, depth + 1, ancestors | {obj.Name})) is not None
        ]
        return _node(obj, nested)

    tree = [node for root in roots if (node := visit(root, 1, set())) is not None]
    return tree, truncated


def _vector(value):
    return [value.x, value.y, value.z]


def _shape(value):
    if value.isNull():
        return {"null": True}
    bounds = value.BoundBox
    return {
        "shape_type": value.ShapeType,
        "solids": len(value.Solids),
        "volume": value.Volume,
        "bounds": [bounds.XLength, bounds.YLength, bounds.ZLength],
    }


def _value(value, property_type, depth=0):
    if value is None or type(value) in (bool, int, float, str):
        return value
    if depth >= 4:
        return "<nested>"
    if property_type == "Part::PropertyPartShape":
        return _shape(value)
    if property_type == "App::PropertyPlacement" or (
        hasattr(value, "Base") and hasattr(value, "Rotation")
    ):
        return {"base": _vector(value.Base), "rotation": list(value.Rotation.Q)}
    if property_type == "App::PropertyVector" or all(
        hasattr(value, coordinate) for coordinate in ("x", "y", "z")
    ):
        return _vector(value)
    if hasattr(value, "Value") and hasattr(value, "Unit"):
        try:
            _display, conversion, unit = value.getUserPreferred()
            return {"value": value.Value / float(conversion), "unit": unit}
        except Exception:
            return {"value": value.Value, "unit": str(value.Unit)}
    if hasattr(value, "Name") and hasattr(value, "Document"):
        return {"object": value.Name}
    if isinstance(value, (list, tuple)):
        items = [_value(item, "", depth + 1) for item in value[:MAX_PROPERTY_ITEMS]]
        if len(value) > MAX_PROPERTY_ITEMS:
            items.append("<truncated>")
        return items
    if isinstance(value, dict):
        items = list(value.items())
        result = {
            str(key): _value(item, "", depth + 1)
            for key, item in items[:MAX_PROPERTY_ITEMS]
        }
        if len(items) > MAX_PROPERTY_ITEMS:
            result["<truncated>"] = True
        return result
    text = repr(value)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "<truncated>"


def _property_modes(obj, name):
    try:
        modes = obj.getEditorMode(name)
    except Exception:
        return []
    if isinstance(modes, int):
        return {
            0: [], 1: ["ReadOnly"], 2: ["Hidden"],
            3: ["ReadOnly", "Hidden"],
        }.get(modes, [str(modes)])
    return list(modes) if isinstance(modes, (list, tuple)) else [str(modes)]


def _object_detail(obj, children, parents, requested_properties):
    detail = _node(obj)
    detail["parents"] = parents.get(obj.Name, [])
    detail["children"] = [child.Name for child in children[obj.Name]]
    detail["dependencies"] = [item.Name for item in obj.OutList]
    detail["dependents"] = [item.Name for item in obj.InList]
    property_names = [
        name for name in obj.PropertiesList
        if "Hidden" not in _property_modes(obj, name)
    ]
    detail["property_names"] = property_names[:MAX_PROPERTY_ITEMS]
    if len(property_names) > MAX_PROPERTY_ITEMS:
        detail["property_names_truncated"] = True
    if requested_properties:
        values = {}
        for name in requested_properties:
            if name not in obj.PropertiesList:
                raise DocumentInspectionError(
                    f"Object {obj.Name!r} has no property {name!r}"
                )
            property_type = obj.getTypeIdOfProperty(name)
            value = {
                "type": property_type,
                "value": _value(getattr(obj, name), property_type),
            }
            modes = _property_modes(obj, name)
            if modes:
                value["mode"] = modes
            values[name] = value
        detail["properties"] = values
    return detail


def inspect_document(app, gui, document=None, object_name=None, properties=None, max_depth=6):
    """Return either a native GUI tree or focused details for one object."""
    doc = _document(app, document)
    if object_name:
        obj = doc.getObject(object_name)
        if obj is None:
            raise DocumentInspectionError(
                f"Object {object_name!r} is not in document {doc.Name!r}"
            )
        objects = list(doc.Objects)
        object_names = {item.Name for item in objects}
        children = {item.Name: _children(item, object_names) for item in objects}
        parents = {}
        for parent, descendants in children.items():
            for child in descendants:
                parents.setdefault(child.Name, []).append(parent)
        return {
            "document": doc.Name,
            "object": _object_detail(
                obj, children, parents, properties or [],
            ),
        }

    tree, truncated = _tree(doc, max_depth)
    result = {"document": _metadata(app, gui, doc), "tree": tree}
    if truncated:
        result["truncated"] = True
    return result
