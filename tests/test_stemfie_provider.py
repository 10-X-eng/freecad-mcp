import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ADDON = Path(__file__).resolve().parents[1] / "addon" / "FreeCADMCP"
sys.path.insert(0, str(ADDON))
PROVIDER_PATH = ADDON / "rpc_server" / "stemfie_provider.py"
_spec = importlib.util.spec_from_file_location("_stemfie_provider_test", PROVIDER_PATH)
stemfie = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stemfie)


def test_find_root_and_provider_metadata(tmp_path):
    unrelated = tmp_path / "other"
    unrelated.mkdir()
    root = tmp_path / "StemfieWB"
    module = root / "freecad" / "stemfie" / "Stemfie.py"
    module.parent.mkdir(parents=True)
    module.write_text("")

    assert stemfie.find_root([unrelated, root]) == root
    assert stemfie.provider([unrelated, root]) == {
        "id": "stemfie", "kind": "parametric", "installed": True,
        "root": str(root), "actions": ["search", "inspect", "insert"],
    }


def test_search_exposes_creatable_parts_with_category(monkeypatch, tmp_path):
    class BaseCommand:
        NAME = ""
        FUNCTION = None

    def beam(_obj):
        pass

    beam.__module__ = "freecad.stemfie.Beams"

    class StraightBeam(BaseCommand):
        NAME = "STR_ESS"
        FUNCTION = beam
        menutext = "STR ESS"
        tooltip = "Beam - Straight - Ending Square Square"

    module = SimpleNamespace(BaseCommand=BaseCommand, StraightBeam=StraightBeam)
    monkeypatch.setattr(stemfie, "_load", lambda _dirs: (tmp_path, module))

    assert stemfie.search([tmp_path], "straight beam") == [{
        "id": "stemfie:StraightBeam", "provider": "stemfie",
        "label": "STR ESS", "description": "Beam - Straight - Ending Square Square",
        "category": "Beams", "kind": "parametric", "_score": 20,
    }]


def test_property_application_distinguishes_units_from_block_units():
    angle = SimpleNamespace(Value=90, Unit="deg")
    obj = SimpleNamespace(Angle=angle, Height=0.5)
    obj.getTypeIdOfProperty = lambda name: {
        "Angle": "App::PropertyAngle",
        "Height": "App::PropertyFloatConstraint",
    }[name]
    doc = SimpleNamespace(recompute=lambda: None)

    stemfie._apply_properties(obj, {"Height": 1.25}, {"Angle", "Height"}, doc)
    assert obj.Height == 1.25
    stemfie._apply_properties(obj, {"Angle": "120 deg"}, {"Angle", "Height"}, doc)
    assert obj.Angle == "120 deg"
    obj.Angle = angle
    with pytest.raises(stemfie.StemfieProviderError, match="explicit unit string"):
        stemfie._apply_properties(obj, {"Angle": 120}, {"Angle", "Height"}, doc)
    with pytest.raises(stemfie.StemfieProviderError, match="Unsupported"):
        stemfie._apply_properties(obj, {"made_up": 3}, {"Angle", "Height"}, doc)
