import types

import pytest

from rpc_server.document_inspection import DocumentInspectionError, inspect_document


class FakeView:
    def __init__(self, children=None, visible=True, modified=False):
        self._children = children or []
        self.Visibility = visible
        self.Modified = modified

    def claimChildren(self):
        return self._children


class FakeObject:
    def __init__(self, name, type_id="Part::Feature", label=None):
        self.Name = name
        self.Label = label or name
        self.TypeId = type_id
        self.State = ["Up-to-date"]
        self.ViewObject = FakeView()
        self.OutList = []
        self.InList = []
        self.PropertiesList = []
        self._types = {}

    def property(self, name, value, type_id):
        self.PropertiesList.append(name)
        self._types[name] = type_id
        setattr(self, name, value)
        return self

    def getTypeIdOfProperty(self, name):
        return self._types[name]


class FakeDocument:
    def __init__(self, objects):
        self.Name = "Model"
        self.Label = "Model label"
        self.FileName = "/tmp/model.FCStd"
        self.Objects = objects

    def getObject(self, name):
        return next((obj for obj in self.Objects if obj.Name == name), None)


class FakeFreeCAD:
    def __init__(self, doc):
        self.doc = doc

    def activeDocument(self):
        return self.doc

    def getDocument(self, name):
        if name != self.doc.Name:
            raise NameError(name)
        return self.doc


def fixture():
    box = FakeObject("Box", "Part::Box", "Main box").property(
        "Length", types.SimpleNamespace(Value=20.0, Unit="mm"),
        "App::PropertyLength",
    )
    box.property("Count", 4, "App::PropertyInteger")
    group = FakeObject("Group", "App::DocumentObjectGroup")
    group.State = ["Touched", "Expanded"]
    group.ViewObject = FakeView([box], visible=False)
    group.OutList = [box]
    box.InList = [group]
    doc = FakeDocument([group, box])
    app = FakeFreeCAD(doc)
    gui = types.SimpleNamespace(
        getDocument=lambda name: types.SimpleNamespace(Modified=name == doc.Name),
    )
    return app, gui


def test_tree_uses_gui_claimed_hierarchy_and_omits_benign_state():
    app, gui = fixture()

    result = inspect_document(app, gui)

    assert result["document"] == {
        "name": "Model", "label": "Model label", "path": "/tmp/model.FCStd",
        "active": True, "modified": True, "object_count": 2,
    }
    assert result["tree"] == [{
        "name": "Group", "type": "App::DocumentObjectGroup", "hidden": True,
        "state": ["Touched"],
        "children": [{"name": "Box", "type": "Part::Box", "label": "Main box"}],
    }]


def test_depth_limit_reports_unexpanded_child_count():
    app, gui = fixture()
    result = inspect_document(app, gui, max_depth=1)
    assert result["tree"][0]["child_count"] == 1
    assert "children" not in result["tree"][0]
    assert len(result["tree"]) == 1


def test_object_detail_returns_dependencies_and_only_requested_values():
    app, gui = fixture()

    result = inspect_document(
        app, gui, object_name="Box", properties=["Length", "Count"],
    )

    detail = result["object"]
    assert detail["parents"] == ["Group"]
    assert detail["dependencies"] == []
    assert detail["dependents"] == ["Group"]
    assert detail["property_names"] == ["Length", "Count"]
    assert detail["properties"] == {
        "Length": {
            "type": "App::PropertyLength", "value": {"value": 20.0, "unit": "mm"},
        },
        "Count": {"type": "App::PropertyInteger", "value": 4},
    }


def test_unknown_document_object_and_property_are_errors():
    app, gui = fixture()
    with pytest.raises(DocumentInspectionError, match="Document 'Other' is not open"):
        inspect_document(app, gui, document="Other")
    with pytest.raises(DocumentInspectionError, match="Object 'Missing'"):
        inspect_document(app, gui, object_name="Missing")
    with pytest.raises(DocumentInspectionError, match="no property 'Width'"):
        inspect_document(app, gui, object_name="Box", properties=["Width"])
