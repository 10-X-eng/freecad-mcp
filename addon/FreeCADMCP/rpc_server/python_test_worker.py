"""Entry point loaded by FreeCADCmd (which imports scripts, not __main__)."""

import json
import os
from pathlib import Path
import sys
import traceback

import FreeCAD as App

sys.path.insert(0, str(Path(__file__).resolve().parent))
from python_session import PythonSession


def main():
    result_path = Path(os.environ["FREECAD_MCP_TEST_RESULT"])
    version = list(App.Version())
    try:
        request = json.loads(Path(os.environ["FREECAD_MCP_TEST_REQUEST"]).read_text(encoding="utf-8"))
        if version[:4] != request["expected_version"][:4]:
            result = {
                "success": False, "code": "FREECAD_VERSION_MISMATCH",
                "error": "Test worker version/build differs from the live FreeCAD process",
                "expected_version": request["expected_version"],
            }
        else:
            unit_settings = request.get("unit_settings")
            if unit_settings and hasattr(App, "Units"):
                preferences = App.ParamGet(
                    "User parameter:BaseApp/Preferences/Units"
                )
                preferences.SetInt("UserSchema", unit_settings["schema_id"])
                preferences.SetInt("Decimals", unit_settings["decimals"])
                App.Units.setSchema(unit_settings["schema_id"])
            aliases = {"FreeCAD": App, "App": App}
            if request["document_path"]:
                aliases["doc"] = App.openDocument(request["document_path"])
            # Tee bounded Python output to the process pipes so timeout/crash
            # results retain anything printed before the process was killed.
            result = PythonSession(aliases, tee_output=True).run(request["code"])
        result["freecad_version"] = version
    except BaseException as exc:
        result = {"success": False, "freecad_version": version, "error": {
            "type": type(exc).__name__, "message": str(exc),
            "traceback": traceback.format_exc(),
        }}
    result_path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")


# FreeCADCmd executes/imports this file under its filename-derived module name.
main()
