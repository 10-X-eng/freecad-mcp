from pathlib import Path

import pytest

from rpc_server.document_operations import (
    DocumentOperationError,
    perform_document_operation,
)


class FakeDocument:
    def __init__(self, name, path="", modified=False):
        self.Name = name
        self.Label = name
        self.FileName = path
        self.Modified = modified
        self.Objects = []
        self.loaded = []

    def save(self):
        self.Modified = False

    def saveAs(self, path):
        self.FileName = path
        Path(path).touch()
        self.Modified = False

    def load(self, path):
        self.loaded.append(path)
        self.Modified = False


class FakeFreeCAD:
    def __init__(self):
        self.documents = {}
        self.active = None

    def activeDocument(self):
        return self.documents.get(self.active)

    def listDocuments(self):
        return self.documents

    def getDocument(self, name):
        if name not in self.documents:
            raise NameError(name)
        return self.documents[name]

    def newDocument(self, name):
        actual = name.replace(" ", "_")
        doc = FakeDocument(actual)
        self.documents[actual] = doc
        self.active = actual
        return doc

    def openDocument(self, path):
        name = Path(path).stem.replace("-", "_")
        doc = FakeDocument(name, path)
        self.documents[name] = doc
        self.active = name
        return doc

    def setActiveDocument(self, name):
        if name not in self.documents:
            raise NameError(name)
        self.active = name

    def closeDocument(self, name):
        del self.documents[name]
        if self.active == name:
            self.active = next(iter(self.documents), None)


def test_new_list_and_activate_report_actual_document_state():
    app = FakeFreeCAD()

    created = perform_document_operation(app, app, "new", "My Document")
    perform_document_operation(app, app, "new", "Other")
    activated = perform_document_operation(app, app, "activate", "My_Document")
    listed = perform_document_operation(app, app, "list")

    assert created == {
        "name": "My_Document", "label": "My_Document", "path": None,
        "active": True, "modified": False, "object_count": 0,
    }
    assert activated["active"] is True
    assert [doc["name"] for doc in listed["documents"]] == ["My_Document", "Other"]
    assert [doc["active"] for doc in listed["documents"]] == [True, False]


def test_save_as_then_save_without_requiring_overwrite(tmp_path):
    app = FakeFreeCAD()
    doc = app.newDocument("Model")
    path = tmp_path / "model.FCStd"

    saved_as = perform_document_operation(app, app, "save_as", path=str(path))
    doc.Modified = True
    saved = perform_document_operation(app, app, "save")
    saved_again = perform_document_operation(app, app, "save_as", path=str(path))

    assert saved_as["path"] == str(path)
    assert saved["modified"] is False
    assert saved_again["path"] == str(path)


def test_save_as_refuses_to_overwrite_another_file(tmp_path):
    app = FakeFreeCAD()
    app.newDocument("Model")
    path = tmp_path / "existing.FCStd"
    path.write_bytes(b"existing")

    with pytest.raises(DocumentOperationError, match="Refusing to overwrite"):
        perform_document_operation(app, app, "save_as", path=str(path))

    result = perform_document_operation(app, app, "save_as", path=str(path), overwrite=True)
    assert result["path"] == str(path)


def test_open_is_idempotent_for_the_same_file(tmp_path):
    app = FakeFreeCAD()
    path = tmp_path / "model.FCStd"
    path.touch()

    opened = perform_document_operation(app, app, "open", path=str(path))
    reopened = perform_document_operation(app, app, "open", path=str(path))

    assert opened["name"] == "model"
    assert reopened["already_open"] is True
    assert len(app.documents) == 1


@pytest.mark.parametrize("action", ["close", "reload"])
def test_destructive_operations_protect_unsaved_changes(tmp_path, action):
    app = FakeFreeCAD()
    path = tmp_path / "model.FCStd"
    path.touch()
    doc = FakeDocument("Model", str(path), modified=True)
    app.documents[doc.Name] = doc
    app.active = doc.Name

    with pytest.raises(DocumentOperationError, match="unsaved changes"):
        perform_document_operation(app, app, action)

    result = perform_document_operation(app, app, action, discard_changes=True)
    if action == "close":
        assert result == {"closed": "Model"}
        assert not app.documents
    else:
        assert result["modified"] is False
        assert doc.loaded == [str(path)]


def test_save_requires_a_path():
    app = FakeFreeCAD()
    app.newDocument("Scratch")

    with pytest.raises(DocumentOperationError, match="use save_as"):
        perform_document_operation(app, app, "save")


@pytest.mark.parametrize("action", ["invalid", "OPEN", ""])
def test_unknown_action_is_rejected(action):
    with pytest.raises(DocumentOperationError, match="Unknown action"):
        app = FakeFreeCAD()
        perform_document_operation(app, app, action)
