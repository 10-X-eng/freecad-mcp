"""Linear elastic bracket verification using native Gmsh and CalculiX.

The four welded plates are fused into one continuum. Hardware/panel are excluded;
the rear mounting face is fixed and the outboard edge carries 500 N downward.
No bolt preload, contact, weld failure, plasticity or buckling is modeled.
"""

import contextlib
import math
import os
from pathlib import Path
import re
import tempfile

import FreeCAD as App
import ObjectsFem
from femmesh.gmshtools import GmshTools
from femtools import ccxtools

from gusseted_bracket_assembly import structural_shape


def deck_force(deck):
    """Check the generated nodal loads, rather than just the GUI property."""
    force = [0.0, 0.0, 0.0]
    reading = False
    for line in deck.splitlines():
        line = line.strip()
        if line.startswith("**") or not line:
            continue
        if line.startswith("*"):
            reading = line.upper().startswith("*CLOAD")
        elif reading:
            _, axis, value = line.split(",")[:3]
            force[int(axis) - 1] += float(value)
    return force


def total_reaction(dat):
    match = re.search(
        r"total force[^\n]*\n\s*([-+\d.EeDd]+)\s+([-+\d.EeDd]+)\s+([-+\d.EeDd]+)",
        dat, re.IGNORECASE,
    )
    assert match, "CalculiX reaction totals missing: " + dat[:1200]
    return [float(value.replace("D", "E").replace("d", "e")) for value in match.groups()]


@contextlib.contextmanager
def bundled_solvers():
    """Use this FreeCAD installation's solvers, restoring previous preferences."""
    previous = []
    try:
        for group, key, binary in (("Gmsh", "gmshBinaryPath", "gmsh"), ("Ccx", "ccxBinaryPath", "ccx")):
            params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/" + group)
            path = os.path.join(App.getHomePath(), "bin", binary)
            if os.path.isfile(path):
                previous.append((params, key, params.GetString(key)))
                params.SetString(key, path)
        yield
    finally:
        for params, key, value in previous:
            params.SetString(key, value)


def solve_bracket(mesh_size=6, force_n=500, output_directory=None, name="BracketFEM"):
    """Return a native analysis/result plus equilibrium and displacement checks."""
    doc = App.newDocument(name)
    doc.Label = f"Bracket FEM - {force_n:g} N, {mesh_size:g} mm quadratic mesh"
    body = doc.addObject("Part::Feature", "WeldedBracket")
    body.Shape = structural_shape()
    body.Label = "Welded continuum - idealized rigid mounting"
    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    steel = ObjectsFem.makeMaterialSolid(doc, "Steel")
    steel.Material = {
        "Name": "Linear elastic steel", "Density": "7850 kg/m^3",
        "YoungsModulus": "210 GPa", "PoissonRatio": "0.3",
    }
    analysis.addObject(steel)
    mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    mesh.Shape = body
    mesh.ElementOrder = "2nd"
    mesh.CharacteristicLengthMax = mesh_size
    mesh.CharacteristicLengthMin = mesh_size / 3
    analysis.addObject(mesh)

    def faces_at_x(x):
        return [f"Face{i}" for i, face in enumerate(body.Shape.Faces, 1)
                if face.BoundBox.XLength < 1e-7 and abs(face.CenterOfMass.x - x) < 1e-7]

    rear_faces, tip_faces = faces_at_x(0), faces_at_x(128)
    assert len(rear_faces) == len(tip_faces) == 1, (rear_faces, tip_faces)
    fixed = ObjectsFem.makeConstraintFixed(doc, "FixedMountingFace")
    fixed.References = [(body, rear_faces)]
    analysis.addObject(fixed)
    load = ObjectsFem.makeConstraintForce(doc, "DownwardLoad")
    load.References = [(body, tip_faces)]
    load.Force = f"{force_n:g} N"
    z_edge = next(f"Edge{i}" for i, edge in enumerate(body.Shape.Edges, 1)
                  if abs(edge.tangentAt(edge.FirstParameter).z) > 0.999 and edge.BoundBox.ZLength > 1)
    load.Direction = (body, [z_edge])
    doc.recompute()
    load.Reversed = load.DirectionVector.z > 0
    doc.recompute()
    assert (load.DirectionVector - App.Vector(0, 0, -1)).Length < 1e-8
    analysis.addObject(load)
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiX")
    solver.AnalysisType = "static"
    solver.GeometricalNonlinearity = "linear"
    solver.MaterialNonlinearity = "linear"
    analysis.addObject(solver)
    doc.recompute()

    with bundled_solvers(), contextlib.ExitStack() as stack:
        if output_directory is None:
            workdir = stack.enter_context(tempfile.TemporaryDirectory(prefix="bracket_fem_"))
        else:
            workdir = str(Path(output_directory).resolve())
            Path(workdir).mkdir(parents=True, exist_ok=True)
        mesh_error = GmshTools(mesh).create_mesh()
        assert not mesh_error, mesh_error
        assert mesh.FemMesh.NodeCount > 0 and mesh.FemMesh.VolumeCount > 0
        fea = ccxtools.FemToolsCcx(analysis=analysis, solver=solver)
        fea.update_objects()
        fea.setup_working_dir(workdir)
        fea.setup_ccx()
        prerequisites = fea.check_prerequisites()
        assert not prerequisites, prerequisites
        fea.write_inp_file()
        assert fea.inp_file_name
        inp = Path(fea.inp_file_name)
        applied = deck_force(inp.read_text())
        assert math.isclose(applied[2], -force_n, rel_tol=1e-6), applied
        assert abs(applied[0]) + abs(applied[1]) < 1e-7
        code = fea.ccx_run()
        assert code == 0, (code, fea.ccx_stderr, fea.ccx_stdout[-3000:])
        assert "*ERROR" not in fea.ccx_stdout.upper(), fea.ccx_stdout[-3000:]
        reaction = total_reaction(inp.with_suffix(".dat").read_text())
        assert abs(reaction[2] - force_n) / force_n < 1e-4, reaction
        assert abs(reaction[0]) + abs(reaction[1]) < force_n * 1e-4, reaction
        fea.load_results()
        result = next(obj for obj in analysis.Group if hasattr(obj, "vonMises"))
        assert len(result.vonMises) == len(result.DisplacementLengths) > 0
        stress, displacement = max(result.vonMises), max(result.DisplacementLengths)
        assert math.isfinite(stress) and stress > 0
        assert math.isfinite(displacement) and 0 < displacement < 1, displacement
        summary = {
            "mesh_size_mm": mesh_size, "element_order": 2,
            "nodes": mesh.FemMesh.NodeCount, "tetrahedra": mesh.FemMesh.VolumeCount,
            "load_n": force_n, "applied_force_n": applied, "reaction_force_n": reaction,
            "max_von_mises_mpa": stress, "max_displacement_mm": displacement,
            "solver_exit_code": code,
        }
        if output_directory is not None:
            (Path(workdir) / "calculix.stdout.log").write_text(fea.ccx_stdout)
            (Path(workdir) / "calculix.stderr.log").write_text(fea.ccx_stderr)
    if App.GuiUp:
        import FreeCADGui as Gui
        body.Visibility = False
        fixed.Visibility = False
        load.Visibility = False
        pipelines = analysis.getObjectsOfType("Fem::FemPostPipeline")
        if pipelines:
            pipeline = pipelines[-1]
            pipeline.ViewObject.Field = "von Mises Stress"
            pipeline.ViewObject.DisplayMode = "Surface"
            pipeline.ViewObject.Visibility = True
            result.Mesh.ViewObject.Visibility = False
            pipeline.ViewObject.updateColorBars()
        else:
            from femresult import resulttools
            resulttools.show_result(result, "Sabs")
        Gui.activeDocument().activeView().viewIsometric()
        Gui.activeDocument().activeView().fitAll()
    return {"document": doc, "analysis": analysis, "mesh": mesh, "result": result, "summary": summary}
