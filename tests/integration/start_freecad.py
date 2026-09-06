"""Pass this script to a separate FreeCAD GUI to start the checkout's addon.

Launch with isolated user/system config files and FREECAD_USER_HOME or XDG
profile directories. This script never installs anything into the user profile.
"""

import json
import os
from pathlib import Path
import sys

import FreeCAD as App

addon = Path(__file__).resolve().parents[2] / "addon" / "FreeCADMCP"
sys.path.insert(0, str(addon))
from rpc_server import rpc_server

message = rpc_server.start_rpc_server(port=int(os.environ.get("FREECAD_MCP_PORT", "9875")))
ready = {"freecad_version": App.Version(), "addon": str(addon), "message": message}
if os.environ.get("FREECAD_MCP_READY_PATH"):
    Path(os.environ["FREECAD_MCP_READY_PATH"]).write_text(json.dumps(ready))
print("FREECAD_MCP_READY", json.dumps(ready), flush=True)
