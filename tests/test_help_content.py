import pytest

from freecad_mcp.help_content import HELP_TOPICS, get_help_content


def test_every_help_topic_is_concise_and_connected():
    assert HELP_TOPICS == (
        "start", "python", "documents", "workbenches", "resources",
        "inspection", "validation", "bim", "fem", "cam", "blocked",
    )
    for topic in HELP_TOPICS:
        content = get_help_content(topic)
        assert content["topic"] == topic
        assert content["guidance"]
        assert all(item and "\n" not in item for item in content["guidance"])
        assert set(content["related"]).issubset(HELP_TOPICS)
        assert len(" ".join(content["guidance"]).split()) <= 170


def test_unknown_help_topic_is_rejected():
    with pytest.raises(KeyError):
        get_help_content("unknown")


def test_bim_help_steers_semantic_and_export_validation():
    guidance = " ".join(get_help_content("bim")["guidance"])
    assert "IfcBuildingStorey" in guidance
    assert "getEnumerationsOfProperty" in guidance
    assert "ifcopenshell" in guidance
    assert "Cables" in guidance
    assert "professional review" in guidance
