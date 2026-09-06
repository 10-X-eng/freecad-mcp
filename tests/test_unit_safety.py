import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "addon" / "FreeCADMCP" / "rpc_server" / "unit_safety.py"
)
_spec = importlib.util.spec_from_file_location("_unit_safety_test", MODULE_PATH)
units = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(units)


def test_dimensional_properties_require_explicit_units():
    obj = SimpleNamespace(Length=SimpleNamespace(Value=1, Unit="mm"), Count=4)
    obj.getTypeIdOfProperty = lambda name: {
        "Length": "App::PropertyLength",
        "Count": "App::PropertyInteger",
    }[name]
    units.require_explicit_quantity(obj, "Length", "0.25 in")
    units.require_explicit_quantity(obj, "Count", 4)
    with pytest.raises(ValueError, match="explicit unit string"):
        units.require_explicit_quantity(obj, "Length", 0.25)


def test_all_quantity_types_require_units():
    obj = SimpleNamespace(
        Current=SimpleNamespace(Value=2, Unit="A"),
    )
    obj.getTypeIdOfProperty = lambda name: {
        "Current": "App::PropertyElectricCurrent",
    }[name]
    with pytest.raises(ValueError, match="explicit unit string"):
        units.require_explicit_quantity(obj, "Current", 2)


def test_preferred_units_follow_running_freecad_schema():
    app = SimpleNamespace(
        Units=SimpleNamespace(
            getSchema=lambda: 2,
            listSchemas=lambda: ["Internal", "MKS", "Imperial"],
        ),
        ParamGet=lambda _path: SimpleNamespace(
            GetInt=lambda key, default: {"UserSchema": 2, "Decimals": 3}.get(
                key, default,
            ),
        ),
    )
    assert units.preferred_units(app) == {
        "schema": "Imperial", "schema_id": 2, "decimals": 3,
    }


def test_preferred_units_reports_transient_schema_mismatch():
    app = SimpleNamespace(
        Units=SimpleNamespace(
            getSchema=lambda: 0,
            listSchemas=lambda: ["Internal", "MKS", "Imperial"],
        ),
        ParamGet=lambda _path: SimpleNamespace(
            GetInt=lambda key, default: {"UserSchema": 2, "Decimals": 2}.get(
                key, default,
            ),
        ),
    )
    assert units.preferred_units(app) == {
        "schema": "Imperial", "schema_id": 2, "decimals": 2,
        "active_schema": "Internal",
    }
