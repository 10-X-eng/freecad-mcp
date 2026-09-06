import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

RESOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "addon" / "FreeCADMCP" / "rpc_server" / "resource_operations.py"
)
_spec = importlib.util.spec_from_file_location("_resource_operations_test", RESOURCE_PATH)
resources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resources)


class FakeApp:
    def __init__(self, user_root: Path, home_root: Path, document=None):
        self.user_root = user_root
        self.home_root = home_root
        self.document = document

    def getUserAppDataDir(self):
        return str(self.user_root)

    def getHomePath(self):
        return str(self.home_root)

    def getDocument(self, name):
        if self.document is None or name != self.document.Name:
            raise NameError(name)
        return self.document


def make_library(tmp_path):
    user = tmp_path / "user"
    library = user / "Mod" / "parts_library"
    part = library / "Mechanical Parts" / "Bearings" / "608_Bearing.FCStd"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"FCStd fixture")
    (library / "LICENSE-Assets").write_text("CC-BY-3.0")
    return FakeApp(user, tmp_path / "home"), part


def test_file_provider_search_and_inspection_are_compact(tmp_path):
    resources._FILE_CACHE.clear()
    app, part = make_library(tmp_path)
    assert resources.resource_operations(app, None, "providers") == {
        "providers": [{
            "id": "parts_library", "kind": "file", "installed": True,
            "root": str(part.parents[2]),
            "actions": ["search", "inspect", "insert"],
        }],
    }
    found = resources.resource_operations(app, None, "search", query="608 bearing")
    assert found == {
        "matches": [{
            "id": "parts_library:Mechanical Parts/Bearings/608_Bearing.FCStd",
            "provider": "parts_library", "label": "608_Bearing",
            "path": "Mechanical Parts/Bearings/608_Bearing.FCStd",
            "kind": "fcstd",
        }],
        "truncated": False,
    }
    detail = resources.resource_operations(
        app, None, "inspect", resource_id=found["matches"][0]["id"],
    )
    assert detail["path"] == str(part)
    assert detail["bytes"] == len(b"FCStd fixture")
    assert detail["license"].endswith("LICENSE-Assets")


def test_file_insert_returns_only_created_objects(tmp_path):
    resources._FILE_CACHE.clear()
    app, part = make_library(tmp_path)
    original = SimpleNamespace(Name="Existing", Label="Existing", TypeId="Part::Box")
    added = SimpleNamespace(Name="Bearing", Label="608 bearing", TypeId="PartDesign::Feature")

    class Document:
        Name = "Assembly"
        Objects = [original]

        def openTransaction(self, _label): pass
        def commitTransaction(self): pass
        def abortTransaction(self): pass
        def recompute(self): pass

        def mergeProject(self, path):
            assert path == str(part)
            self.Objects.append(added)

    app.document = Document()
    result = resources.resource_operations(
        app, None, "insert",
        resource_id="parts_library:Mechanical Parts/Bearings/608_Bearing.FCStd",
        document="Assembly",
    )
    assert result == {
        "resource_id": "parts_library:Mechanical Parts/Bearings/608_Bearing.FCStd",
        "document": "Assembly",
        "objects": [{"name": "Bearing", "label": "608 bearing", "type": "PartDesign::Feature"}],
        "truncated": False,
    }


def test_resource_paths_and_required_arguments_are_guarded(tmp_path):
    resources._FILE_CACHE.clear()
    app, _ = make_library(tmp_path)
    with pytest.raises(resources.ResourceOperationError, match="query is required"):
        resources.resource_operations(app, None, "search")
    with pytest.raises(resources.ResourceOperationError, match="escapes"):
        resources.resource_operations(
            app, None, "inspect", resource_id="parts_library:../secret.FCStd",
        )
    with pytest.raises(resources.ResourceOperationError, match="Document is not open"):
        resources.resource_operations(
            app, None, "insert",
            resource_id="parts_library:Mechanical Parts/Bearings/608_Bearing.FCStd",
            document="Missing",
        )


def test_search_merges_installed_provider_results(monkeypatch, tmp_path):
    app = FakeApp(tmp_path / "user", tmp_path / "home")
    monkeypatch.setattr(resources, "_providers", lambda _app: [
        {"id": "fasteners"}, {"id": "parts_library"},
    ])
    monkeypatch.setattr(resources, "_file_providers", lambda _app: {
        "parts_library": tmp_path,
    })
    monkeypatch.setattr(resources, "_fastener_matches", lambda _app, _query: [{
        "id": "fasteners:ISO4762", "provider": "fasteners",
        "label": "ISO 4762 socket screw", "kind": "parametric", "_score": 20,
    }])
    monkeypatch.setattr(resources, "_file_matches", lambda *_args: [{
        "id": "parts_library:bearing.FCStd", "provider": "parts_library",
        "label": "bearing", "kind": "fcstd", "_score": 10,
    }])
    result = resources.resource_operations(app, None, "search", query="socket", limit=1)
    assert [item["id"] for item in result["matches"]] == ["fasteners:ISO4762"]
    assert result["truncated"] is True
    assert "_score" not in result["matches"][0]
