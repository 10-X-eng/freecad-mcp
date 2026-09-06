"""Plain FreeCAD Python: a steel cantilever solved using Gmsh and CalculiX.

Submit this file's contents to execute_python with timeout_seconds=600, or
execute it as a FreeCAD macro. Configure the FEM solver paths in FreeCAD first.
This creates a new document and leaves it open for inspection.

The coarse linear tetrahedral mesh is a pipeline smoke test, not a converged
engineering analysis. Its stress/displacement checks allow mesh stiffness.
"""

import tempfile

import FreeCAD as App
import ObjectsFem
from femmesh.gmshtools import GmshTools
from femtools import ccxtools


fem_doc = App.newDocument("MCPCantilever")
fem_doc_name = fem_doc.Name
beam = fem_doc.addObject("Part::Box", "Beam")
beam.Length, beam.Width, beam.Height = 100, 10, 10
fem_doc.recompute()

analysis = ObjectsFem.makeAnalysis(fem_doc, "Analysis")
steel = ObjectsFem.makeMaterialSolid(fem_doc, "Steel")
steel.Material = {
    "Name": "Steel", "Density": "7900 kg/m^3",
    "YoungsModulus": "210 GPa", "PoissonRatio": "0.3",
}
analysis.addObject(steel)

mesh = ObjectsFem.makeMeshGmsh(fem_doc, "Mesh")
mesh.Shape = beam
mesh.CharacteristicLengthMax = 5
mesh.CharacteristicLengthMin = 1
analysis.addObject(mesh)
fem_doc.recompute()
GmshTools(mesh).create_mesh()
assert mesh.FemMesh.NodeCount > 0, "Gmsh produced no nodes"

fixed_face = next(
    f"Face{i}" for i, face in enumerate(beam.Shape.Faces, 1)
    if abs(face.CenterOfMass.x) < 1e-6
)
loaded_face = next(
    f"Face{i}" for i, face in enumerate(beam.Shape.Faces, 1)
    if abs(face.CenterOfMass.x - 100) < 1e-6
)
fixed = ObjectsFem.makeConstraintFixed(fem_doc, "Fixed")
fixed.References = [(beam, [fixed_face])]
analysis.addObject(fixed)
load = ObjectsFem.makeConstraintForce(fem_doc, "Load")
load.References = [(beam, [loaded_face])]
z_edge = next(
    f"Edge{i}" for i, edge in enumerate(beam.Shape.Edges, 1)
    if abs(edge.tangentAt(0).z) > 0.99
)
load.Direction = (beam, [z_edge])
load.Reversed = True
load.Force = "100 N"
analysis.addObject(load)
solver = ObjectsFem.makeSolverCalculiXCcxTools(fem_doc, "CalculiX")
analysis.addObject(solver)
fem_doc.recompute()

fea = ccxtools.FemToolsCcx(analysis=analysis, solver=solver)
fea.update_objects()
with tempfile.TemporaryDirectory(prefix="freecad_python_fem_") as solve_directory:
    fea.setup_working_dir(solve_directory)
    fea.setup_ccx()
    prerequisites = fea.check_prerequisites()
    assert not prerequisites, prerequisites
    fea.purge_results()
    # run() resets the working directory from GUI preferences. Use the lower
    # level sequence so all solver files stay in this temporary directory.
    fea.write_inp_file()
    assert fea.inp_file_name, "CalculiX input file was not written"
    assert fea.ccx_run() == 0, "CalculiX failed"
    fea.load_results()

results = next(obj for obj in analysis.Group if hasattr(obj, "vonMises"))
fem_summary = {
    "node_count": len(results.vonMises),
    "max_von_mises_MPa": max(results.vonMises),
    "max_displacement_mm": max(results.DisplacementLengths),
}
# Euler-Bernoulli predictions: 60 MPa and 0.190476 mm.
assert 0.4 < fem_summary["max_von_mises_MPa"] / 60 < 1.5, fem_summary
assert 0.4 < fem_summary["max_displacement_mm"] / (4 / 21) < 1.5, fem_summary
fem_summary
