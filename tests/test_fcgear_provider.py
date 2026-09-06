import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


PROVIDER_PATH = (
    Path(__file__).resolve().parents[1]
    / "addon" / "FreeCADMCP" / "rpc_server" / "fcgear_provider.py"
)
_spec = importlib.util.spec_from_file_location("_fcgear_provider_test", PROVIDER_PATH)
fcgear = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcgear)


def test_find_root_and_provider_metadata(tmp_path):
    unrelated = tmp_path / "other"
    unrelated.mkdir()
    root = tmp_path / "freecad.gears"
    (root / "freecad" / "gears").mkdir(parents=True)
    (root / "freecad" / "gears" / "commands.py").write_text("")

    assert fcgear.find_root([unrelated, root]) == root
    assert fcgear.provider([unrelated, root]) == {
        "id": "fcgear", "kind": "parametric", "installed": True,
        "root": str(root), "actions": ["search", "inspect", "insert"],
    }


def test_search_exposes_creatable_gears_but_not_relational_commands(monkeypatch, tmp_path):
    class BaseCommand:
        NAME = ""
        GEAR_FUNCTION = None

    class Involute(BaseCommand):
        NAME = "InvoluteGear"
        GEAR_FUNCTION = object()
        MenuText = "Involute Gear"
        ToolTip = "Create an external involute gear"

    class Connector(BaseCommand):
        NAME = "GearConnector"
        GEAR_FUNCTION = object()
        MenuText = "Combine gears"
        ToolTip = "Combine two existing gears"

    module = SimpleNamespace(
        BaseCommand=BaseCommand, Involute=Involute, Connector=Connector,
    )
    monkeypatch.setattr(fcgear, "_load", lambda _dirs: (tmp_path, module))

    assert fcgear.search([tmp_path], "involute") == [{
        "id": "fcgear:InvoluteGear", "provider": "fcgear",
        "label": "Involute Gear", "description": "Create an external involute gear",
        "kind": "parametric", "_score": 110,
    }]


def test_parameter_application_rejects_unknown_names():
    obj = SimpleNamespace(
        module="1 mm",
        getTypeIdOfProperty=lambda name: {
            "module": "App::PropertyLength",
        }[name],
    )
    doc = SimpleNamespace(recompute=lambda: None)
    fcgear._apply_properties(obj, {"module": "2 mm"}, {"module"}, doc)
    assert obj.module == "2 mm"
    with pytest.raises(fcgear.FCGearProviderError, match="explicit unit string"):
        fcgear._apply_properties(obj, {"module": 2.0}, {"module"}, doc)
    with pytest.raises(fcgear.FCGearProviderError, match="Unsupported"):
        fcgear._apply_properties(obj, {"made_up": 3}, {"module"}, doc)
