"""Native FreeCAD 1.1 assembly: welded bracket, mounting panel and M8 hardware.

Import in execute_python/test_python, then call build_assembly(). This is model
code, not an MCP tool. Dimensions are millimetres. Fastener threads and weld
beads are simplified; this example is not a manufacturing specification.
"""

import math
import os
import sys

import FreeCAD as App
import Part

sys.path.insert(0, os.path.join(App.getHomePath(), "Mod", "Assembly"))
import Assembly
import JointObject
import Preferences


HOLES = [(y, z) for y in (-28, 28) for z in (20, 90)]
STRUCTURAL_PARTS = ("Backplate", "Shelf", "LeftGusset", "RightGusset")


def prism(points, direction):
    vertices = [App.Vector(*point) for point in points]
    return Part.Face(Part.makePolygon(vertices + [vertices[0]])).extrude(App.Vector(*direction))


def hex_prism(across_flats, height, z=0):
    radius = across_flats / math.sqrt(3)
    return prism([
        (radius * math.cos(i * math.pi / 3), radius * math.sin(i * math.pi / 3), z)
        for i in range(6)
    ], (0, 0, height))


def templates():
    """Seven reusable, single-solid part definitions in their local frames."""
    back = prism([
        (0, -36, 0), (0, 36, 0), (0, 40, 4), (0, 40, 96),
        (0, 36, 100), (0, -36, 100), (0, -40, 96), (0, -40, 4),
    ], (8, 0, 0))
    panel = Part.makeBox(6, 92, 112, App.Vector(0, -46, -6))
    for y, z in HOLES:
        drill = Part.makeCylinder(4.5, 10, App.Vector(-1, y, z), App.Vector(1, 0, 0))
        back = back.cut(drill)
        panel = panel.cut(drill)
    shelf = prism([
        (0, -40, 0), (112, -40, 0), (120, -32, 0),
        (120, 32, 0), (112, 40, 0), (0, 40, 0),
    ], (0, 0, 8))
    for x in (88, 108):
        for y in (-25, 25):
            shelf = shelf.cut(Part.makeCylinder(3.3, 10, App.Vector(x, y, -1)))
    gusset = prism([(0, 0, 0), (100, 0, 56), (0, 0, 56)], (0, 6, 0))
    gusset = gusset.cut(Part.makeCylinder(10, 8, App.Vector(30, -1, 36), App.Vector(0, 1, 0)))
    bolt = Part.makeCylinder(4, 30).fuse(hex_prism(13, 5.3, 30))
    washer = Part.makeCylinder(8, 1.6).cut(Part.makeCylinder(4.2, 1.6))
    nut = hex_prism(13, 6.5).cut(Part.makeCylinder(4, 6.5))
    result = dict(Panel=panel, Backplate=back, Shelf=shelf, Gusset=gusset, Bolt=bolt, Washer=washer, Nut=nut)
    for name, shape in result.items():
        result[name] = shape.removeSplitter()
        assert result[name].isValid() and len(result[name].Solids) == 1, name
    return result


def layout():
    """(instance name, prototype name, assembly placement)."""
    def plc(x, y=0, z=0, rotation=None):
        return App.Placement(App.Vector(x, y, z), rotation or App.Rotation())

    specs = [
        ("MountingPanel", "Panel", plc(-6)),
        ("Backplate", "Backplate", plc(0)),
        ("Shelf", "Shelf", plc(8, 0, 70)),
        ("LeftGusset", "Gusset", plc(8, -18, 14)),
        ("RightGusset", "Gusset", plc(8, 12, 14)),
    ]
    along_x = App.Rotation(App.Vector(0, 0, 1), App.Vector(1, 0, 0))
    for index, (y, z) in enumerate(HOLES, 1):
        for role, prototype, x in (
            ("Bolt", "Bolt", -20.4), ("FrontWasher", "Washer", 8),
            ("RearWasher", "Washer", -7.6), ("Nut", "Nut", -14.1),
        ):
            specs.append((f"{role}{index}", prototype, plc(x, y, z, along_x)))
    return specs


def structural_shape():
    """Ideal welded continuum: only the backplate, shelf and two gussets."""
    definitions = templates()
    shapes = []
    for name, prototype, placement in layout():
        if name in STRUCTURAL_PARTS:
            shape = definitions[prototype].copy()
            shape.Placement = placement
            shapes.append(shape)
    welded = shapes[0].multiFuse(shapes[1:]).removeSplitter()
    assert welded.isValid() and len(welded.Solids) == 1
    return welded


def validate_parts(parts):
    """No solid interference; touching mating surfaces are allowed."""
    names = list(parts)
    for i, name in enumerate(names):
        shape = parts[name].Shape
        assert shape.isValid() and len(shape.Solids) == 1, name
        for other in names[i + 1:]:
            intersection = shape.common(parts[other].Shape)
            assert intersection.Volume < 1e-5, (name, other, intersection.Volume)


def build_assembly(name="GussetedBracket"):
    """Build, constrain, perturb and re-solve a 21-part native assembly."""
    definitions = templates()
    doc = App.newDocument(name)
    doc.Label = "Gusseted bracket - 21-part assembly"
    sources = doc.addObject("App::DocumentObjectGroup", "PartDefinitions")
    prototypes = {}
    colors = {
        "Panel": (0.45, 0.48, 0.52), "Backplate": (0.18, 0.48, 0.74),
        "Shelf": (0.22, 0.58, 0.83), "Gusset": (0.92, 0.56, 0.16),
        "Bolt": (0.73, 0.76, 0.80), "Washer": (0.78, 0.81, 0.84), "Nut": (0.65, 0.68, 0.73),
    }
    for prototype, shape in definitions.items():
        obj = doc.addObject("Part::Feature", "Definition" + prototype)
        obj.Label = prototype + " - reusable definition"
        obj.Shape = shape
        sources.addObject(obj)
        prototypes[prototype] = obj
        if App.GuiUp:
            obj.ViewObject.ShapeColor = colors[prototype]
            obj.ViewObject.Visibility = False

    assembly = doc.addObject("Assembly::AssemblyObject", "Assembly")
    assembly.Type = "Assembly"
    joints = assembly.newObject("Assembly::JointGroup", "Joints")
    parts, expected = {}, {}
    for instance, prototype, placement in layout():
        link = assembly.newObject("App::Link", instance)
        link.setLink(prototypes[prototype])
        link.LinkPlacement = placement
        parts[instance], expected[instance] = link, App.Placement(placement)
    doc.recompute()
    ground = joints.newObject("App::FeaturePython", "GroundPanel")
    JointObject.GroundedJoint(ground, parts["MountingPanel"])
    if App.GuiUp:
        JointObject.ViewProviderGroundedJoint(ground.ViewObject)

    prefs = Preferences.preferences()
    previous = prefs.GetBool("SolveInJointCreation", True)
    prefs.SetBool("SolveInJointCreation", False)
    try:
        for name, link in parts.items():
            if name == "MountingPanel":
                continue
            joint = joints.newObject("App::FeaturePython", "Fix" + name)
            JointObject.Joint(joint, 0)
            joint.Offset1 = expected["MountingPanel"].inverse() * expected[name]
            joint.Proxy.setJointConnectors(joint, [
                [parts["MountingPanel"], ["", ""]], [link, ["", ""]],
            ])
            if App.GuiUp:
                JointObject.ViewProviderJoint(joint.ViewObject)
                joint.ViewObject.Visibility = False
    finally:
        prefs.SetBool("SolveInJointCreation", previous)
    doc.recompute()
    assert assembly.solve() == 0, "Assembly solver failed"
    assert assembly.isPartGrounded(parts["MountingPanel"])
    assert all(assembly.isPartConnected(part) for part in parts.values())
    # Prove the joints enforce the geometry, rather than just preserving manual placement.
    for index, (name, part) in enumerate(parts.items()):
        if name != "MountingPanel":
            part.Placement = App.Placement(
                expected[name].Base + App.Vector(2, -3, 1),
                App.Rotation(App.Vector(1, 0, 0), 2) * expected[name].Rotation,
            )
    assert assembly.solve() == 0, "Perturbed assembly could not be solved"
    doc.recompute()
    assert all(part.Placement.isSame(expected[name], 1e-5) for name, part in parts.items())
    validate_parts(parts)
    assert len(parts) == 21 and len(joints.Group) == 21
    if App.GuiUp:
        import FreeCADGui as Gui
        sources.Visibility = False
        joints.Visibility = False
        for part in parts.values():
            part.Visibility = True
        Gui.activeDocument().activeView().viewIsometric()
        Gui.activeDocument().activeView().fitAll()
    return {
        "document": doc, "assembly": assembly, "parts": parts,
        "summary": {"parts": 21, "fixed_joints": 20, "grounded_parts": 1,
                    "solver_code": 0, "perturbation_recovered": True, "interference_free": True},
    }
