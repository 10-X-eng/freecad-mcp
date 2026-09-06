"""Opt-in MCP protocol tests against an isolated, real FreeCAD GUI.

FREECAD_MCP_INTEGRATION=1 uv run pytest -q -s tests/integration
Set FREECAD_MCP_FEM=1 to also require installed Gmsh and CalculiX.
Set FREECAD_MCP_CAM=1 to also build, post, simulate and reopen a CAM Job.
Set FREECAD_MCP_RESOURCES=1 to require Fasteners and FreeCAD Parts Library.
Set FREECAD_MCP_FCGEAR=1 with RESOURCES to require the external FCGear provider.
"""

import asyncio
import base64
from datetime import timedelta
import json
import os
from pathlib import Path
import struct
import tempfile

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
                "GetHelp", "DocumentOperations", "ExecutePython", "InspectDocument",
                "ResourceOperations", "GetView", "GetRuntimeStatus", "TestPython",
            ]

            async def call(name, args=None, success=True):
                result = await session.call_tool(
                    name, args or {}, read_timeout_seconds=timedelta(seconds=660),
                )
                text = "\n".join(block.text for block in result.content if block.type == "text")
                assert result.isError is not success, text
                return json.loads(text) if text else result

            async def run(code, success=True, timeout=90):
                result = await call("ExecutePython", {
                    "code": code, "timeout_seconds": timeout,
                }, success)
                return result

            status = await call("GetRuntimeStatus")
            assert status["freecad_version"] == "1.1.3", status
            assert status["test_worker"]["state"] == "ready", status
            print("REAL FreeCAD version:", status["freecad_version"])

            # The production document tool owns lifecycle and protects live edits.
            with tempfile.TemporaryDirectory(prefix="freecad_mcp_documents_") as directory:
                document_path = str(Path(directory) / "lifecycle.FCStd")
                created = await call("DocumentOperations", {
                    "action": "new", "document": "MCP Document Lifecycle",
                })
                lifecycle_name = created["result"]["name"]
                await run(
                    f"lifecycle_doc = App.getDocument({lifecycle_name!r})\n"
                    "lifecycle_box = lifecycle_doc.addObject('Part::Box', 'Box')\n"
                    "lifecycle_box.Length = 10\nlifecycle_doc.recompute()"
                )
                inspected = await call("InspectDocument", {"document": lifecycle_name})
                assert inspected["result"]["document"]["modified"] is True
                assert inspected["result"]["document"]["object_count"] == 1
                assert inspected["result"]["tree"] == [{
                    "name": "Box", "type": "Part::Box",
                }]
                box_detail = await call("InspectDocument", {
                    "document": lifecycle_name, "object_name": "Box",
                    "properties": ["Length", "Shape"],
                })
                assert box_detail["result"]["object"]["properties"]["Length"]["value"] == {
                    "value": 10.0, "unit": "mm",
                }
                shape = box_detail["result"]["object"]["properties"]["Shape"]["value"]
                assert shape["solids"] == 1
                assert shape["volume"] == pytest.approx(1000.0)
                print("REAL_FREECAD_DOCUMENT_INSPECTION_PASS")
                saved = await call("DocumentOperations", {
                    "action": "save_as", "document": lifecycle_name,
                    "path": document_path,
                })
                assert saved["result"]["path"] == document_path
                listed = await call("DocumentOperations", {"action": "list"})
                assert any(
                    item["name"] == lifecycle_name and item["path"] == document_path
                    for item in listed["result"]["documents"]
                )
                await run("lifecycle_box.Length = 99\nlifecycle_doc.recompute()")
                protected = await call("DocumentOperations", {
                    "action": "reload", "document": lifecycle_name,
                }, False)
                assert "unsaved changes" in protected["error"]
                reloaded = await call("DocumentOperations", {
                    "action": "reload", "document": lifecycle_name,
                    "discard_changes": True,
                })
                assert reloaded["result"]["name"] == lifecycle_name
                await run(
                    "lifecycle_box = lifecycle_doc.getObject('Box')\n"
                    "assert lifecycle_box.Length.Value == 10\n"
                    "lifecycle_box.Width = 12\nlifecycle_doc.recompute()"
                )
                await call("DocumentOperations", {
                    "action": "save", "document": lifecycle_name,
                })
                await call("DocumentOperations", {
                    "action": "close", "document": lifecycle_name,
                })
                opened = await call("DocumentOperations", {
                    "action": "open", "path": document_path,
                })
                reopened_name = opened["result"]["name"]
                await run(
                    f"reopened = App.getDocument({reopened_name!r})\n"
                    "assert reopened.getObject('Box').Width.Value == 12"
                )
                await call("DocumentOperations", {
                    "action": "activate", "document": reopened_name,
                })
                await call("DocumentOperations", {
                    "action": "close", "document": reopened_name,
                })
                print("REAL_FREECAD_DOCUMENT_OPERATIONS_PASS")

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
                assert "assert box.Shape.Volume == 1" in failed["error"]
                assert "AssertionError" in failed["error"]
                assert "python_session.py" not in failed["error"]
                fixed = await run(
                    "box.Length = 40\ndoc.recompute()\n"
                    "assert box.Shape.isValid()\n"
                    "{'volume': box.Shape.Volume, 'solids': len(box.Shape.Solids)}"
                )
                assert fixed["result"] == {"volume": 6000, "solids": 1}
                output = await run("print('stdout')\nprint('stderr', file=sys.stderr)\n2**80")
                assert output["stdout"] == "stdout\n" and output["stderr"] == "stderr\n"
                assert output["result"] == 2**80
                assert "SyntaxError" in (await run("if", False))["error"]
                assert await run("40 + 2") == {"result": 42}

                # A menu/dialog must not block the Python needed to inspect or
                # close it. Fallback timers prevent a regression stranding the UI.
                await run(
                    "from PySide import QtCore, QtWidgets\n"
                    "dispatch_dialog = QtWidgets.QDialog(Gui.getMainWindow())\n"
                    "dispatch_dialog.setModal(True)\n"
                    "QtCore.QTimer.singleShot(10000, dispatch_dialog.reject)\n"
                    "dispatch_dialog.show()"
                )
                await run(
                    "assert QtWidgets.QApplication.activeModalWidget() is dispatch_dialog\n"
                    "dispatch_dialog.reject()", timeout=3,
                )
                await run(
                    "dispatch_menu = QtWidgets.QMenu(Gui.getMainWindow())\n"
                    "dispatch_menu.addAction('MCP dispatch test')\n"
                    "QtCore.QTimer.singleShot(10000, dispatch_menu.close)\n"
                    "dispatch_menu.popup(Gui.getMainWindow().mapToGlobal(QtCore.QPoint(100, 100)))"
                )
                await run(
                    "assert QtWidgets.QApplication.activePopupWidget() is dispatch_menu\n"
                    "dispatch_menu.close()", timeout=3,
                )

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
                image_result = await call("GetView", {"width": 320, "height": 240})
                image = next(block for block in image_result.content if block.type == "image")
                data = base64.b64decode(image.data)
                assert data[:8] == b"\x89PNG\r\n\x1a\n"
                assert struct.unpack(">II", data[16:24]) == (320, 240)
                assert len(data) > 1000
                if os.environ.get("FREECAD_MCP_IMAGE_PATH"):
                    Path(os.environ["FREECAD_MCP_IMAGE_PATH"]).write_bytes(data)

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

                if os.environ.get("FREECAD_MCP_RESOURCES") == "1":
                    providers = await call("ResourceOperations", {"action": "providers"})
                    provider_ids = {
                        item["id"] for item in providers["result"]["providers"]
                    }
                    assert {"fasteners", "parts_library"} <= provider_ids, providers

                    created_resources = await call("DocumentOperations", {
                        "action": "new", "document": "MCP Resource Integration",
                    })
                    resource_doc = created_resources["result"]["name"]
                    await run(f"integration_docs.append({resource_doc!r})")

                    screws = await call("ResourceOperations", {
                        "action": "search", "provider": "fasteners",
                        "query": "ISO 4762 socket head cap screw", "limit": 5,
                    })
                    screw_ids = {item["id"] for item in screws["result"]["matches"]}
                    assert "fasteners:ISO4762" in screw_ids, screws
                    screw_info = await call("ResourceOperations", {
                        "action": "inspect", "resource_id": "fasteners:ISO4762",
                        "properties": {"Diameter": "M8"},
                    })
                    assert "M8" in screw_info["result"]["diameters"]
                    assert "25" in screw_info["result"]["lengths"]
                    inserted_screw = await call("ResourceOperations", {
                        "action": "insert", "resource_id": "fasteners:ISO4762",
                        "document": resource_doc,
                        "properties": {"Diameter": "M8", "Length": "25", "Thread": False},
                    })
                    screw = inserted_screw["result"]
                    assert screw["shape"]["solids"] == 1
                    assert screw["shape"]["volume"] > 0

                    bearings = await call("ResourceOperations", {
                        "action": "search", "provider": "parts_library",
                        "query": "608ZZ Ball Bearing", "limit": 5,
                    })
                    bearing = next(
                        item for item in bearings["result"]["matches"]
                        if item["path"].endswith("608ZZ_Ball_Bearing.fcstd")
                    )
                    bearing_info = await call("ResourceOperations", {
                        "action": "inspect", "resource_id": bearing["id"],
                    })
                    assert bearing_info["result"]["format"].casefold() == "fcstd"
                    inserted_bearing = await call("ResourceOperations", {
                        "action": "insert", "resource_id": bearing["id"],
                        "document": resource_doc,
                    })
                    assert inserted_bearing["result"]["objects"]

                    if os.environ.get("FREECAD_MCP_FCGEAR") == "1":
                        assert "fcgear" in provider_ids, providers
                        gears = await call("ResourceOperations", {
                            "action": "search", "provider": "fcgear",
                            "query": "external involute gear", "limit": 5,
                        })
                        assert gears["result"]["matches"][0]["id"] == (
                            "fcgear:InvoluteGear"
                        )
                        gear_properties = {
                            "module": 2, "num_teeth": 24, "height": 8,
                            "helix_angle": "15 deg", "axle_hole": True,
                            "axle_holesize": 8,
                        }
                        gear_info = await call("ResourceOperations", {
                            "action": "inspect",
                            "resource_id": "fcgear:InvoluteGear",
                            "properties": gear_properties,
                        })
                        assert {"module", "num_teeth", "height"} <= set(
                            gear_info["result"]["parameters"]
                        )
                        assert gear_info["result"]["shape"]["solids"] == 1
                        inserted_gear = await call("ResourceOperations", {
                            "action": "insert",
                            "resource_id": "fcgear:InvoluteGear",
                            "document": resource_doc, "properties": gear_properties,
                        })
                        gear = inserted_gear["result"]
                        assert gear["properties"]["num_teeth"] == 24
                        assert gear["computed"]["pitch_diameter"] == {
                            "value": pytest.approx(48.0), "unit": "mm",
                        }
                        assert gear["shape"]["solids"] == 1
                        print("REAL_FREECAD_FCGEAR_RESOURCE_PASS")

                    inspected_resources = await call("InspectDocument", {
                        "document": resource_doc,
                    })
                    expected_objects = 5 if os.environ.get("FREECAD_MCP_FCGEAR") == "1" else 4
                    assert inspected_resources["result"]["document"]["object_count"] >= expected_objects
                    print("REAL_FREECAD_RESOURCE_OPERATIONS_PASS")

                # Assertions fail and are corrected in fresh native FreeCADCmds.
                failed_test = await call("TestPython", {"code": (
                    "import Part\nshape = Part.makeBox(2, 3, 4)\n"
                    "assert shape.Volume == 25, 'wrong volume'"
                )}, False)
                assert "AssertionError" in failed_test["error"]
                tested = await call("TestPython", {"code": (
                    "import Part, math\nshape = Part.makeBox(2, 3, 4)\n"
                    "assert math.isclose(shape.Volume, 24)\n"
                    "assert App.GuiUp == 0\nassert 'Gui' not in globals()\n"
                    "assert 'integration_docs' not in globals()\n"
                    "{'volume': shape.Volume, 'valid': shape.isValid(), 'version': '.'.join(App.Version()[:3])}"
                )})
                assert tested["result"]["valid"]
                assert tested["result"]["version"] == status["freecad_version"]
                assert set(tested) == {"result"}, tested

                # A saved copy excludes unsaved live edits and cannot replace the source.
                source = await run(
                    "import hashlib\nfrom pathlib import Path\n"
                    "original_hash = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()\n"
                    "box.Width = 16\ndoc.recompute()\nmodel_path"
                )
                copied = await call("TestPython", {
                    "document_path": source["result"],
                    "code": (
                        "assert doc.getObject('Box').Width.Value == 15\n"
                        "doc.getObject('Box').Length = 7\ndoc.recompute()\ndoc.save()\n"
                        "{'path': doc.FileName, 'width': doc.getObject('Box').Width.Value}"
                    ),
                })
                assert copied["result"]["path"] != source["result"]
                await run(
                    "assert hashlib.sha256(Path(model_path).read_bytes()).hexdigest() == original_hash\n"
                    "assert box.Length.Value == 40 and box.Width.Value == 16\n"
                    f"assert not os.path.exists({copied['result']['path']!r})\n"
                    "box.Width = 15\ndoc.recompute()"
                )

                # An infinite loop is killed in the disposable process. Live calls
                # and status still complete through the very same MCP connection.
                hanging_test = asyncio.create_task(call("TestPython", {
                    "code": "print('worker entered', flush=True)\nwhile True: pass",
                    "timeout_seconds": 2,
                }, False))
                for _ in range(40):
                    test_status = await call("GetRuntimeStatus")
                    if test_status["test_worker"]["state"] == "running":
                        break
                    await asyncio.sleep(0.03)
                assert test_status["test_worker"]["state"] == "running"
                assert (await run("box.Length.Value"))["result"] == 40
                busy = await call("TestPython", {"code": "42"}, False)
                assert busy["code"] == "TEST_WORKER_BUSY"
                killed = await hanging_test
                assert killed["code"] == "TEST_TIMEOUT"
                assert "worker entered" in killed["process_stdout"]
                crashed = await call("TestPython", {"code": "import os\nos._exit(7)"}, False)
                assert crashed["code"] == "TEST_WORKER_EXITED" and crashed["exit_code"] == 7
                assert (await call("TestPython", {"code": "6 * 7"}))["result"] == 42
                print("REAL_FREECAD_ISOLATED_TESTS_PASS")

                if os.environ.get("FREECAD_MCP_FEM") == "1":
                    # Use binaries bundled with the real installation when present.
                    fem_setup = (
                        "import os\n"
                        "for group, key, binary in [('Gmsh', 'gmshBinaryPath', 'gmsh'), "
                        "('Ccx', 'ccxBinaryPath', 'ccx')]:\n"
                        "    path = os.path.join(App.getHomePath(), 'bin', binary)\n"
                        "    if os.path.isfile(path):\n"
                        "        App.ParamGet('User parameter:BaseApp/Preferences/Mod/Fem/' + group).SetString(key, path)"
                    )
                    fem_code = (REPO / "examples/cantilever_fem.py").read_text()
                    tested_fem = await call("TestPython", {
                        "code": fem_setup + "\n" + fem_code, "timeout_seconds": 600,
                    })
                    print("REAL headless FEM:", tested_fem["result"])
                    await run(fem_setup)
                    solved = await run(fem_code, timeout=600)
                    print("REAL FEM:", solved["result"])
                    assert solved["result"]["node_count"] > 0

                if os.environ.get("FREECAD_MCP_CAM") == "1":
                    cam_code = (REPO / "examples/fixture_plate_cam.py").read_text()
                    tested_cam = await call("TestPython", {
                        "code": (
                            cam_code + "\ncam_built = build_fixture_plate_cam("
                            "tempfile.mkdtemp(prefix='headless_cam_'), 'HeadlessCAM')\n"
                            "cam_built['summary']"
                        ),
                        "timeout_seconds": 120,
                    })
                    assert tested_cam["result"]["tool_numbers"] == [1, 1, 2, 1]
                    assert tested_cam["result"]["gcode_lines"] > 300
                    print("REAL headless CAM:", tested_cam["result"])

                    built_cam = await run(
                        cam_code + "\ncam_built = build_fixture_plate_cam("
                        "integration_temp.name, 'MCPFixturePlateCAM')\n"
                        "integration_docs.append(cam_built['document'].Name)\n"
                        "{'document': cam_built['document'].Name, "
                        "'directory': integration_temp.name, **cam_built['summary']}",
                        timeout=120,
                    )
                    assert built_cam["result"]["tool_numbers"] == [1, 1, 2, 1]
                    simulated_cam = await run(
                        "cam_simulated = simulate_fixture_plate_cam(cam_built)\n"
                        "cam_simulated['summary']",
                        timeout=180,
                    )
                    assert simulated_cam["result"]["commands"] > 200
                    assert simulated_cam["result"]["volume_deviation_percent"] < 1
                    cam_path = str(
                        Path(built_cam["result"]["directory"]) / "fixture-plate-cam.FCStd"
                    )
                    await call("DocumentOperations", {
                        "action": "save_as", "document": built_cam["result"]["document"],
                        "path": cam_path,
                    })
                    persisted_cam = await call("TestPython", {
                        "document_path": cam_path,
                        "code": (
                            "job = doc.getObject('CAMJob')\n"
                            "ops = list(job.Operations.Group)\n"
                            "assert [o.Name for o in ops] == ['Facing', 'Pocket', 'Drilling', 'Profile']\n"
                            "assert [o.ToolController.ToolNumber for o in ops] == [1, 1, 2, 1]\n"
                            "result = doc.getObject('CutMaterial')\n"
                            "assert result.SimulationStatus == 'Completed'\n"
                            "assert result.Mesh.CountFacets > 1000\n"
                            "{'operations': {o.Name: len(o.Path.Commands) for o in ops}, "
                            "'simulation_commands': result.SimulatedCommands}"
                        ),
                        "timeout_seconds": 120,
                    })
                    assert persisted_cam["result"]["simulation_commands"] > 200
                    print("REAL CAM:", persisted_cam["result"])

                # Both calls share one MCP session; status must bypass busy Python.
                long_call = asyncio.create_task(run("import time\ntime.sleep(3)\n42", False, 1))
                for _ in range(30):
                    status = await call("GetRuntimeStatus")
                    if status["gui"]["state"] == "busy":
                        break
                    await asyncio.sleep(0.03)
                else:
                    raise AssertionError("Status did not respond while Python was running")
                timed_out = await long_call
                assert timed_out["code"] == "GUI_DISPATCH_STUCK"
                stuck = await call("GetRuntimeStatus")
                assert stuck["gui"]["state"] == "stuck"
                assert stuck["gui"]["operation"] == "execute_python"
                rejected = await run("raise AssertionError('must never run')", False)
                assert rejected["code"] == "GUI_DISPATCH_STUCK"
                for _ in range(100):
                    if (await call("GetRuntimeStatus"))["gui"]["state"] == "idle":
                        break
                    await asyncio.sleep(0.05)
                assert (await run("6 * 7"))["result"] == 42
            finally:
                await run(
                    "if 'fem_doc_name' in globals() and fem_doc_name in App.listDocuments():\n"
                    "    App.closeDocument(fem_doc_name)\n"
                    "for name in integration_docs:\n"
                    "    if name in App.listDocuments():\n"
                    "        App.closeDocument(name)\n"
                    "integration_temp.cleanup()"
                )
            no_view = await call("GetView", success=False)
            assert "active" in no_view["error"].lower()
            print("REAL_FREECAD_FOCUSED_MCP_PASS")


def test_real_freecad():
    asyncio.run(exercise())
