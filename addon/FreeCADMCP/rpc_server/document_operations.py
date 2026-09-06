"""Safe lifecycle operations for live FreeCAD documents."""

import os


ACTIONS = (
    "list", "new", "open", "activate", "save", "save_as", "reload", "close",
)


class DocumentOperationError(ValueError):
    """An invalid or unsafe document operation requested by an MCP client."""


def _document(app, name=None):
    if name:
        try:
            doc = app.getDocument(name)
        except Exception as exc:
            raise DocumentOperationError(f"Document {name!r} is not open") from exc
        if doc is None:
            raise DocumentOperationError(f"Document {name!r} is not open")
        return doc
    doc = app.activeDocument()
    if doc is None:
        raise DocumentOperationError("No active document")
    return doc


def _modified(gui, doc):
    return bool(_gui_document(gui, doc).Modified)


def _gui_document(gui, doc):
    gui_doc = gui.getDocument(doc.Name)
    if gui_doc is None:
        raise DocumentOperationError(f"Document {doc.Name!r} has no GUI document")
    return gui_doc


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


def _path(value, *, must_exist):
    if not value:
        raise DocumentOperationError("path is required")
    expanded = os.path.abspath(os.path.expanduser(value))
    if not expanded.lower().endswith(".fcstd"):
        raise DocumentOperationError("path must end in .FCStd")
    if must_exist:
        if not os.path.isfile(expanded):
            raise DocumentOperationError(f"FreeCAD document does not exist: {expanded}")
    elif not os.path.isdir(os.path.dirname(expanded)):
        raise DocumentOperationError(f"Parent directory does not exist: {os.path.dirname(expanded)}")
    return expanded


def perform_document_operation(
    app,
    gui,
    action,
    document=None,
    path=None,
    discard_changes=False,
    overwrite=False,
):
    """Perform one document operation on FreeCAD's GUI thread."""
    if action not in ACTIONS:
        raise DocumentOperationError(
            f"Unknown action {action!r}; expected one of {', '.join(ACTIONS)}"
        )

    if action == "list":
        return {
            "documents": [_metadata(app, gui, doc) for doc in app.listDocuments().values()]
        }

    if action == "new":
        if not document or not document.strip():
            raise DocumentOperationError("document is required for new")
        doc = app.newDocument(document)
        app.setActiveDocument(doc.Name)
        return _metadata(app, gui, doc)

    if action == "open":
        file_path = _path(path, must_exist=True)
        for doc in app.listDocuments().values():
            if doc.FileName and os.path.realpath(doc.FileName) == os.path.realpath(file_path):
                app.setActiveDocument(doc.Name)
                result = _metadata(app, gui, doc)
                result["already_open"] = True
                return result
        doc = app.openDocument(file_path)
        app.setActiveDocument(doc.Name)
        return _metadata(app, gui, doc)

    doc = _document(app, document)

    if action == "activate":
        app.setActiveDocument(doc.Name)
        return _metadata(app, gui, doc)

    if action == "save":
        if not doc.FileName:
            raise DocumentOperationError("Document has no path; use save_as")
        if _gui_document(gui, doc).save() is False:
            raise DocumentOperationError(f"FreeCAD could not save {doc.FileName}")
        return _metadata(app, gui, doc)

    if action == "save_as":
        file_path = _path(path, must_exist=False)
        same_file = bool(doc.FileName) and os.path.realpath(doc.FileName) == os.path.realpath(file_path)
        if os.path.exists(file_path) and not same_file and not overwrite:
            raise DocumentOperationError(
                f"Refusing to overwrite existing file: {file_path}; set overwrite=true"
            )
        if same_file:
            saved = _gui_document(gui, doc).save()
        else:
            saved = doc.saveAs(file_path)
            # App.Document.saveAs writes the file but does not clear the GUI's
            # modified marker in FreeCAD 1.1. Save once through Gui as well so
            # the tab and our close/reload protection agree with the disk state.
            if saved is not False:
                saved = _gui_document(gui, doc).save()
        if saved is False:
            raise DocumentOperationError(f"FreeCAD could not save {file_path}")
        return _metadata(app, gui, doc)

    if action == "reload":
        if _modified(gui, doc) and not discard_changes:
            raise DocumentOperationError(
                "Document has unsaved changes; save it or set discard_changes=true"
            )
        file_path = _path(doc.FileName, must_exist=True)
        if doc.load(file_path) is False:
            raise DocumentOperationError(f"FreeCAD could not reload {file_path}")
        return _metadata(app, gui, doc)

    if _modified(gui, doc) and not discard_changes:
        raise DocumentOperationError(
            "Document has unsaved changes; save it or set discard_changes=true"
        )
    name = doc.Name
    app.closeDocument(name)
    return {"closed": name}
