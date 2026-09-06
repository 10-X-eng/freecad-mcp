import pytest

from freecad_mcp import server_state


class FakeConnection:
    instances: list["FakeConnection"] = []
    ping_succeeds = True

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.disconnected = False
        self.instances.append(self)

    def ping(self) -> bool:
        return self.ping_succeeds

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture(autouse=True)
def reset_server_state(monkeypatch: pytest.MonkeyPatch):
    original_state = server_state.state
    test_state = server_state.ServerState(rpc_host="freecad.example")
    FakeConnection.instances = []
    FakeConnection.ping_succeeds = True
    monkeypatch.setattr(server_state, "state", test_state)
    monkeypatch.setattr(server_state, "FreeCADConnection", FakeConnection)
    yield test_state
    server_state.state = original_state


def test_connection_is_created_once_and_reused() -> None:
    first = server_state.get_freecad_connection()
    second = server_state.get_freecad_connection()

    assert first is second
    assert len(FakeConnection.instances) == 1
    assert first.host == "freecad.example"
    assert first.port == 9875


def test_failed_ping_discards_connection() -> None:
    FakeConnection.ping_succeeds = False

    with pytest.raises(Exception, match="Failed to connect to FreeCAD"):
        server_state.get_freecad_connection()

    assert server_state.state.freecad_connection is None


def test_disconnect_clears_cached_connection() -> None:
    connection = server_state.get_freecad_connection()

    server_state.disconnect_freecad()

    assert connection.disconnected is True
    assert server_state.state.freecad_connection is None
