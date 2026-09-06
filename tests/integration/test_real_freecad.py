"""Opt-in MCP protocol tests against an isolated, real FreeCAD GUI.

FREECAD_MCP_INTEGRATION=1 uv run pytest -q -s tests/integration
Set FREECAD_MCP_FEM=1 to also require installed Gmsh and CalculiX.
"""

import asyncio
import base64
from datetime import timedelta
import json
import os
from pathlib import Path
import struct

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("FREECAD_MCP_INTEGRATION") != "1",
    reason="Requires an explicitly enabled, isolated real FreeCAD GUI",
)
REPO = Path(__file__).resolve().parents[2]


async def exercise():
    parameters = StdioServerParameters(
        command="uv",
        args=["--directory", str(REPO), "run", "freecad-mcp", "--host",
              os.environ.get("FREECAD_MCP_HOST", "127.0.0.1"), "--port",
              os.environ.get("FREECAD_MCP_PORT", "9875")],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert [tool.name for tool in tools.tools] == [
                "execute_python", "get_view", "get_runtime_status",
            ]

            async def call(name, args=None, success=True):
                result = await session.call_tool(
                    name, args or {}, read_timeout_seconds=timedelta(seconds=660),
                )
                text = "\n".join(block.text for block in result.content if block.type == "text")
                assert result.isError is not success, text
                return json.loads(text) if text else result

            async def run(code, success=True, timeout=90):
                result = await call("execute_python", {
                    "code": code, "timeout_seconds": timeout,
                }, success)
                assert result["success"] is success, result
                return result

            status = await call("get_runtime_status")
            assert status["freecad_version"][:3] == ["1", "1", "3"], status
            print("REAL FreeCAD version:", status["freecad_version"])
            await run(
                "import tempfile, os, math, sys, Part, Sketcher\n"
                "integration_temp = tempfile.TemporaryDirectory(prefix='freecad_mcp_integration_')\n"
                "doc = App.newDocument('MCPPythonIntegration')\n"
                "integration_docs = [doc.Name]\n"
                "box = doc.addObject('Part::Box', 'Box')\n"
                "box.Length, box.Width, box.Height = 20, 15, 10\n"
                "doc.recompute()"
            )
            try:
                failed = await run("print('before assertion')\nassert box.Shape.Volume == 1", False)
                assert failed["stdout"] == "before assertion\n"
                assert "assert box.Shape.Volume == 1" in failed["error"]["traceback"]
                assert failed["error"]["type"] == "AssertionError"
                fixed = await run(
                    "box.Length = 40\ndoc.recompute()\n"
                    "assert box.Shape.isValid()\n"
                    "{'volume': box.Shape.Volume, 'solids': len(box.Shape.Solids)}"
                )
                assert fixed["result"] == {"volume": 6000, "solids": 1}
                output = await run("print('stdout')\nprint('stderr', file=sys.stderr)\n2**80")
                assert output["stdout"] == "stdout\n" and output["stderr"] == "stderr\n"
                assert output["result"] == 2**80
                assert (await run("if", False))["error"]["type"] == "SyntaxError"
                assert (await run("40 + 2"))["result"] == 42

                # Workbench creation and shape booleans use the native API directly.
                await run(
                    "sketch = doc.addObject('Sketcher::SketchObject', 'Sketch')\n"
                    "sketch.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 3), False)\n"
                    "sketch.addConstraint(Sketcher.Constraint('Radius', 0, 3.0))\n"
                    "doc.recompute()\nassert sketch.GeometryCount == 1\n"
                    "bore = Part.makeCylinder(2, 10, App.Vector(5, 5, 0))\n"
                    "cut = box.Shape.cut(bore)\nassert cut.isValid()\n"
                    "assert math.isclose(cut.Volume, 6000 - math.pi * 4 * 10)\n"
                    "sketch.ViewObject.Visibility = False\n"
                    "Gui.activeDocument().activeView().viewIsometric()\n"
                    "Gui.activeDocument().activeView().fitAll()"
                )
                image_result = await call("get_view", {"width": 320, "height": 240})
                image = next(block for block in image_result.content if block.type == "image")
                data = base64.b64decode(image.data)
                assert data[:8] == b"\x89PNG\r\n\x1a\n"
                assert struct.unpack(">II", data[16:24]) == (320, 240)
                assert len(data) > 1000

                await run(
                    "model_path = os.path.join(integration_temp.name, 'different-name.FCStd')\n"
                    "doc.saveAs(model_path)\nbox.Length = 99\ndoc.recompute()\n"
                    "doc.load(model_path)\nbox = doc.getObject('Box')\n"
                    "assert doc.Name == integration_docs[0]\n"
                    "assert box.Length.Value == 40\n"
                    "step_path = os.path.join(integration_temp.name, 'box.step')\n"
                    "Part.export([box], step_path)\n"
                    "restored_shape = Part.Shape()\nrestored_shape.read(step_path)\n"
                    "assert math.isclose(restored_shape.Volume, 6000)\n"
                    "assert restored_shape.isValid()\n"
                    "copy_doc = App.newDocument('MCPImportedPart')\n"
                    "integration_docs.append(copy_doc.Name)\n"
                    "copy_doc.mergeProject(model_path)\n"
                    "assert copy_doc.getObject('Box').Shape.Volume == 6000\n"
                    "App.setActiveDocument(doc.Name)"
                )

                if os.environ.get("FREECAD_MCP_FEM") == "1":
                    # Use binaries bundled with the real installation when present.
                    await run(
                        "for group, key, binary in [('Gmsh', 'gmshBinaryPath', 'gmsh'), "
                        "('Ccx', 'ccxBinaryPath', 'ccx')]:\n"
                        "    path = os.path.join(App.getHomePath(), 'bin', binary)\n"
                        "    if os.path.isfile(path):\n"
                        "        App.ParamGet('User parameter:BaseApp/Preferences/Mod/Fem/' + group).SetString(key, path)"
                    )
                    solved = await run((REPO / "examples/cantilever_fem.py").read_text(), timeout=600)
                    print("REAL FEM:", solved["result"])
                    assert solved["result"]["node_count"] > 0

                # Both calls share one MCP session; status must bypass busy Python.
                long_call = asyncio.create_task(run("import time\ntime.sleep(3)\n42", False, 1))
                for _ in range(30):
                    status = await call("get_runtime_status")
                    if status["gui_dispatch"]["state"] == "busy":
                        break
                    await asyncio.sleep(0.03)
                else:
                    raise AssertionError("Status did not respond while Python was running")
                timed_out = await long_call
                assert timed_out["code"] == "GUI_DISPATCH_STUCK"
                stuck = await call("get_runtime_status")
                assert stuck["current_cell"]["cell_id"] == timed_out["cell_id"]
                rejected = await run("raise AssertionError('must never run')", False)
                assert rejected["code"] == "GUI_DISPATCH_STUCK"
                for _ in range(100):
                    if (await call("get_runtime_status"))["gui_dispatch"]["state"] == "healthy":
                        break
                    await asyncio.sleep(0.05)
                assert (await run("6 * 7"))["result"] == 42
            finally:
                await run(
                    "if 'fem_doc' in globals() and fem_doc.Name in App.listDocuments():\n"
                    "    App.closeDocument(fem_doc.Name)\n"
                    "for name in integration_docs:\n"
                    "    if name in App.listDocuments():\n"
                    "        App.closeDocument(name)\n"
                    "integration_temp.cleanup()"
                )
            no_view = await call("get_view", success=False)
            assert "active" in no_view["error"]["message"].lower()
            print("REAL_FREECAD_FOCUSED_MCP_PASS")


def test_real_freecad():
    asyncio.run(exercise())
