"""Cross-cutting unit reporting and input guards for FreeCAD quantities."""

from __future__ import annotations


_DIMENSIONAL_PROPERTY_MARKERS = (
    "Acceleration", "Angle", "Area", "Current", "Distance", "Energy",
    "Force", "Frequency", "Length", "Mass", "Potential", "Power",
    "Pressure", "Quantity", "Speed", "Temperature", "Time", "Volume",
)


def preferred_quantity(value):
    """Serialize a FreeCAD quantity in the user's active display units."""
    try:
        _display, conversion, unit = value.getUserPreferred()
        return {"value": value.Value / float(conversion), "unit": unit}
    except Exception:
        return {"value": value.Value, "unit": str(value.Unit)}


def preferred_internal(app, value: float, unit: str) -> dict:
    """Label an internal numeric result and convert it to preferred units."""
    return preferred_quantity(app.Units.Quantity(value, unit))


def preferred_vector(app, values, unit: str = "mm") -> dict:
    """Convert several internal values with one compact shared unit label."""
    reference = max((abs(value) for value in values), default=0) or 1
    _display, conversion, preferred_unit = app.Units.Quantity(
        reference, unit,
    ).getUserPreferred()
    return {
        "values": [value / float(conversion) for value in values],
        "unit": preferred_unit,
    }


def require_explicit_quantity(obj, name: str, value) -> None:
    """Reject unitless inputs for dimensional FreeCAD document properties."""
    property_type = obj.getTypeIdOfProperty(name)
    current = getattr(obj, name, None)
    is_quantity = hasattr(current, "Value") and hasattr(current, "Unit")
    if is_quantity or any(
        marker in property_type for marker in _DIMENSIONAL_PROPERTY_MARKERS
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{name} is dimensional; use an explicit unit string such as "
                "'2 mm' or '0.25 in'"
            )


def preferred_units(app) -> dict:
    """Report the configured schema and flag a transient active mismatch."""
    active_schema_id = int(app.Units.getSchema())
    schemas = list(app.Units.listSchemas())
    preferences = app.ParamGet("User parameter:BaseApp/Preferences/Units")
    schema_id = preferences.GetInt("UserSchema", active_schema_id)
    result = {
        "schema": schemas[schema_id] if 0 <= schema_id < len(schemas) else str(schema_id),
        "schema_id": schema_id,
        "decimals": preferences.GetInt("Decimals", 2),
    }
    if active_schema_id != schema_id:
        result["active_schema"] = (
            schemas[active_schema_id]
            if 0 <= active_schema_id < len(schemas)
            else str(active_schema_id)
        )
    return result
