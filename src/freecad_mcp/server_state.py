import logging
from dataclasses import dataclass

from .freecad_client import FreeCADConnection


logger = logging.getLogger("FreeCADMCPserver")


@dataclass
class ServerState:
    only_text_feedback: bool = False
    rpc_host: str = "localhost"
    freecad_connection: FreeCADConnection | None = None


state = ServerState()


def get_freecad_connection() -> FreeCADConnection:
    """Get or create the persistent connection to the FreeCAD RPC server."""
    if state.freecad_connection is None:
        state.freecad_connection = FreeCADConnection(host=state.rpc_host, port=9875)
        if not state.freecad_connection.ping():
            logger.error("Failed to ping FreeCAD")
            state.freecad_connection = None
            raise Exception(
                "Failed to connect to FreeCAD. Make sure the FreeCAD addon is running."
            )
    return state.freecad_connection


def disconnect_freecad() -> None:
    """Disconnect the persistent FreeCAD connection, if one exists."""
    if state.freecad_connection is not None:
        state.freecad_connection.disconnect()
        state.freecad_connection = None
