"""Native FreeCAD CAM example: machine a pocketed four-hole fixture plate.

Import this module in ExecutePython/TestPython and call
``build_fixture_plate_cam()``.  The builder creates native CAM Job, stock,
tool-controller and operation objects, then posts GRBL G-code.  In a GUI,
``simulate_fixture_plate_cam()`` runs FreeCAD's native voxel-removal simulator.

This is a pipeline acceptance example, not production feeds-and-speeds advice.
All dimensions are millimetres.
"""

import json
import math
from pathlib import Path
import tempfile
import time

import FreeCAD as App
import Part
import Path.Main.Job as PathJob
import Path.Op.Drilling as PathDrilling
import Path.Op.MillFace as PathMillFace
import Path.Op.Pocket as PathPocket
import Path.Op.Profile as PathProfile
from Path.Post.Processor import PostProcessorFactory
from Path.Tool.Bit import ToolBit
import Path.Tool.Controller as ToolController
from Path.Tool.machine.models.machine import Machine


def _face_names(shape):
    """Return stable semantic selections for this exact fixture geometry."""
    indexed = list(enumerate(shape.Faces, 1))
    horizontal = [
        (index, face) for index, face in indexed
        if face.BoundBox.ZLength < 1e-7
    ]
    top_z = max(face.BoundBox.ZMax for _, face in horizontal)
    top = max(
        (item for item in horizontal if math.isclose(item[1].BoundBox.ZMax, top_z)),
        key=lambda item: item[1].Area,
    )
    pocket_floor = min(
        (item for item in horizontal if math.isclose(item[1].BoundBox.ZMin, 8.0)),
        key=lambda item: abs(item[1].Area - 1500.0),
    )
    holes = [
        index for index, face in indexed
        if hasattr(face.Surface, "Radius")
        and math.isclose(face.Surface.Radius, 2.5, abs_tol=1e-7)
    ]
    assert len(holes) == 4, holes
    return f"Face{top[0]}", f"Face{pocket_floor[0]}", [f"Face{i}" for i in holes]


def _set_custom_depths(obj, **depths):
    """Detach CAM defaults before assigning explicit machining depths."""
    for prop, value in depths.items():
        obj.setExpression(prop, None)
        setattr(obj, prop, f"{value} mm")


def build_fixture_plate_cam(output_directory=None, name="MCPFixturePlateCAM"):
    """Create and validate a complete 3-axis CAM setup and GRBL program."""
    doc = App.newDocument(name)
    doc.Label = "3-Axis Machining Acceptance - Fixture Plate"
    part = doc.addObject("PartDesign::Feature", "FixturePlate")
    part.Label = "6061-T6 fixture plate"
    shape = Part.makeBox(100, 70, 12)
    shape = shape.cut(Part.makeBox(50, 30, 4, App.Vector(25, 20, 8)))
    hole_centers = [(12, 12), (88, 12), (12, 58), (88, 58)]
    for x, y in hole_centers:
        shape = shape.cut(Part.makeCylinder(2.5, 12, App.Vector(x, y, 0)))
    part.Shape = shape.removeSplitter()
    assert part.Shape.isValid() and len(part.Shape.Solids) == 1

    job = PathJob.Create("CAMJob", [part], None)
    job.Label = "Setup 1 - Bench 3-Axis Mill"
    job.Stock.ExtXneg = job.Stock.ExtXpos = "2 mm"
    job.Stock.ExtYneg = job.Stock.ExtYpos = "2 mm"
    job.Stock.ExtZneg = "0 mm"
    job.Stock.ExtZpos = "2 mm"
    job.SetupSheet.ClearanceHeightOffset = "5 mm"
    job.SetupSheet.SafeHeightOffset = "3 mm"
    job.SetupSheet.HorizRapid = "1500 mm/min"
    job.SetupSheet.VertRapid = "800 mm/min"
    job.SetupSheet.CoolantMode = "Flood"

    endmill = job.Tools.Group[0]
    endmill.Label = "T1 - 6 mm carbide end mill"
    endmill.ToolNumber = 1
    endmill.Tool.Label = "6 mm 3-flute carbide end mill"
    endmill.Tool.Diameter = "6 mm"
    endmill.Tool.Flutes = 3
    endmill.Tool.Material = "Carbide"
    endmill.HorizFeed = "600 mm/min"
    endmill.VertFeed = "180 mm/min"
    endmill.HorizRapid = "1500 mm/min"
    endmill.VertRapid = "800 mm/min"
    endmill.SpindleSpeed = 10000

    top_face, pocket_floor, hole_faces = _face_names(part.Shape)
    # FreeCAD 1.1.3's controller lookup is ambiguous with multiple controllers,
    # so create each operation while exactly one controller is in the Job.
    job.Tools.Group = [endmill]
    facing = PathMillFace.Create("Facing", obj=None, parentJob=job)
    pocket = PathPocket.Create("Pocket", obj=None, parentJob=job)
    profile = PathProfile.Create("Profile", obj=None, parentJob=job)

    drill_bit = ToolBit.from_shape_id("drill")
    drill_tool = drill_bit.attach_to_doc(doc, "5 mm carbide drill")
    drill_tool.Diameter = "5 mm"
    drill_tool.Length = "50 mm"
    drill_tool.Flutes = 2
    drill_tool.Material = "Carbide"
    drill = ToolController.Create("TC_5mm_Drill", drill_tool, 2)
    drill.Label = "T2 - 5 mm carbide drill"
    drill.HorizFeed = "500 mm/min"
    drill.VertFeed = "120 mm/min"
    drill.HorizRapid = "1500 mm/min"
    drill.VertRapid = "800 mm/min"
    drill.SpindleSpeed = 6000
    job.Tools.Group = [drill]
    drilling = PathDrilling.Create("Drilling", obj=None, parentJob=job)
    job.Tools.Group = [endmill, drill]

    facing.ToolController = pocket.ToolController = profile.ToolController = endmill
    drilling.ToolController = drill
    facing.Base = (part, [top_face])
    pocket.Base = (part, [pocket_floor])
    drilling.Base = (part, hole_faces)
    profile.Base = (part, [top_face])
    doc.recompute()

    _set_custom_depths(facing, StartDepth=14, FinalDepth=12, StepDown=1)
    facing.StepOver = 70
    facing.ExtraOffset = "2 mm"
    facing.ClearingPattern = "ZigZag"
    facing.CutMode = "Climb"
    facing.CoolantMode = "Flood"
    _set_custom_depths(pocket, StartDepth=12, FinalDepth=8, StepDown=2)
    pocket.StepOver = 55
    pocket.ClearingPattern = "Offset"
    pocket.CutMode = "Climb"
    pocket.CoolantMode = "Flood"
    _set_custom_depths(drilling, StartDepth=12, FinalDepth=0)
    drilling.PeckEnabled = True
    drilling.setExpression("PeckDepth", None)
    drilling.PeckDepth = "3 mm"
    drilling.AddTipLength = True
    drilling.RetractMode = "G98"
    drilling.CoolantMode = "Flood"
    _set_custom_depths(profile, StartDepth=12, FinalDepth=0, StepDown=3)
    profile.Side = "Outside"
    profile.Direction = "CW"
    profile.UseComp = True
    profile.CoolantMode = "Flood"
    job.Operations.Group = [facing, pocket, drilling, profile]

    native_machine = Machine(
        label="Bench 3-Axis Mill", max_power=1.5, min_rpm=1000,
        max_rpm=12000, min_feed=20, max_feed=1500,
    )
    native_machine.validate()
    machine = doc.addObject("App::FeaturePython", "MachineSetup")
    machine.Label = "Bench 3-Axis Mill (GRBL)"
    for prop_type, prop_name, group in (
        ("App::PropertyString", "Controller", "Machine"),
        ("App::PropertyInteger", "AxisCount", "Machine"),
        ("App::PropertyInteger", "MinSpindleSpeed", "Machine"),
        ("App::PropertyInteger", "MaxSpindleSpeed", "Machine"),
        ("App::PropertySpeed", "MaxFeedRate", "Machine"),
        ("App::PropertyString", "WorkCoordinateSystem", "Setup"),
        ("App::PropertyString", "Workholding", "Setup"),
        ("App::PropertyString", "DefinitionJSON", "Machine"),
    ):
        machine.addProperty(prop_type, prop_name, group)
    machine.Controller = "GRBL"
    machine.AxisCount = 3
    machine.MinSpindleSpeed = 1000
    machine.MaxSpindleSpeed = 12000
    machine.MaxFeedRate = "1500 mm/min"
    machine.WorkCoordinateSystem = "G54: X0 Y0 stock lower-left, Z0 stock top"
    machine.Workholding = "Low-profile vise on parallels; contour clearance verified"
    machine.DefinitionJSON = json.dumps(native_machine.to_dict(), sort_keys=True)
    job.addProperty("App::PropertyLink", "MachineSetup", "Machine")
    job.MachineSetup = machine
    job.PostProcessor = "grbl"
    job.PostProcessorArgs = "--no-show-editor"
    doc.recompute()

    operations = list(job.Operations.Group)
    assert [obj.Name for obj in operations] == ["Facing", "Pocket", "Drilling", "Profile"]
    assert [obj.ToolController.ToolNumber for obj in operations] == [1, 1, 2, 1]
    assert all(obj.Path.Commands for obj in operations)
    assert all(
        math.isfinite(value)
        for obj in operations for command in obj.Path.Commands
        for value in command.Parameters.values() if isinstance(value, (int, float))
    )

    output = Path(output_directory or tempfile.mkdtemp(prefix="freecad_cam_"))
    output.mkdir(parents=True, exist_ok=True)
    gcode_path = output / "fixture_plate_grbl.nc"
    sections = PostProcessorFactory.get_post_processor(job, "grbl").export()
    gcode = "\n".join(section[1] for section in sections)
    gcode_path.write_text(gcode, encoding="utf-8")
    assert "G21" in gcode and "G54" in gcode
    assert "M3 S10000" in gcode and "M3 S6000" in gcode
    assert gcode.rstrip().endswith("M2")
    job.addProperty("App::PropertyString", "OutputFile", "Post Processing")
    job.OutputFile = str(gcode_path)
    job.addProperty("App::PropertyInteger", "GCodeLineCount", "Post Processing")
    job.GCodeLineCount = len(gcode.splitlines())
    doc.recompute()

    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewIsometric()
        Gui.activeDocument().activeView().fitAll()
    return {
        "document": doc, "part": part, "job": job, "machine": machine,
        "operations": operations, "gcode_path": str(gcode_path),
        "summary": {
            "operation_commands": {obj.Name: len(obj.Path.Commands) for obj in operations},
            "tool_numbers": [obj.ToolController.ToolNumber for obj in operations],
            "gcode_lines": len(gcode.splitlines()),
            "target_volume_mm3": part.Shape.Volume,
        },
    }


def simulate_fixture_plate_cam(built, timeout_seconds=120):
    """Run FreeCAD's GUI voxel-removal simulator to completion."""
    if not App.GuiUp:
        raise RuntimeError("The native material-removal simulator requires live FreeCAD GUI")
    import FreeCADGui as Gui
    from PySide import QtCore
    from Path.Main.Gui import Simulator

    doc, job = built["document"], built["job"]
    App.setActiveDocument(doc.Name)
    for name in ("CutTool", "CutMaterial", "CutMaterialIn"):
        old = doc.getObject(name)
        if old is not None:
            doc.removeObject(old.Name)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(job)
    simulation = Simulator.PathSimulation()
    simulation.Activate()
    simulation.SimFF()
    deadline = time.monotonic() + timeout_seconds
    while simulation.timer.isActive() and time.monotonic() < deadline:
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(25, loop.quit)
        loop.exec()
    assert not simulation.timer.isActive(), "CAM simulation timed out"
    assert simulation.iprogress == simulation.numCommands
    # The task panel normally performs these steps when the user accepts it.
    # Do them explicitly so scripted simulation retains one complete result.
    simulation.RemoveInnerMaterial()
    simulation.RemoveTool()
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    result = doc.getObject("CutMaterial")
    assert result is not None and result.Mesh.CountFacets > 1000
    expected = built["part"].Shape.Volume
    deviation = 100 * abs(result.Mesh.Volume - expected) / expected
    assert deviation < 1.0, deviation
    result.Label = "Native CAM Material Removal Result"
    for prop_type, prop_name in (
        ("App::PropertyString", "SimulationEngine"),
        ("App::PropertyString", "SimulationStatus"),
        ("App::PropertyInteger", "SimulatedCommands"),
        ("App::PropertyLength", "VoxelResolution"),
        ("App::PropertyFloat", "VolumeDeviationPercent"),
    ):
        if prop_name not in result.PropertiesList:
            result.addProperty(prop_type, prop_name, "Validation")
    result.SimulationEngine = "FreeCAD CAM native PathSimulator voxel engine"
    result.SimulationStatus = "Completed"
    result.SimulatedCommands = simulation.iprogress
    result.VoxelResolution = f"{simulation.resolution} mm"
    result.VolumeDeviationPercent = deviation
    result.ViewObject.ShapeColor = (0.82, 0.68, 0.24)
    doc.recompute()
    return {
        "simulation": simulation, "result": result,
        "summary": {
            "commands": simulation.iprogress,
            "facets": result.Mesh.CountFacets,
            "volume_mm3": result.Mesh.Volume,
            "volume_deviation_percent": deviation,
            "resolution_mm": simulation.resolution,
        },
    }
