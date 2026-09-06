from dataclasses import dataclass

from .freecad_client import FreeCADConnection


@dataclass
class ServerState:
    rpc_host: str = "localhost"
    rpc_port: int = 9875
    freecad_connection: FreeCADConnection | None = None
