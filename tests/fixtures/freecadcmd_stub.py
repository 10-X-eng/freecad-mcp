"""Stub the application module, but run the actual worker in a real process."""

import runpy
import sys
import types

app = types.ModuleType("FreeCAD")
app.Version = lambda: ["1", "1", "3", "test-build"]
app.openDocument = lambda path: types.SimpleNamespace(FileName=path)
sys.modules["FreeCAD"] = app
runpy.run_path(sys.argv[-1])
