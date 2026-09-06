"""Concise operating guidance for Python-first FreeCAD MCP clients."""

from typing import Literal, get_args


HelpTopic = Literal[
    "start",
    "python",
    "documents",
    "workbenches",
    "resources",
    "inspection",
    "validation",
    "fem",
    "cam",
    "blocked",
]


_HELP: dict[str, dict] = {
    "start": {
        "guidance": [
            "This MCP is Python-first. Use ExecutePython for modeling and every workbench API; do not wait for dedicated CAD-operation tools.",
            "Use DocumentOperations for .FCStd lifecycle, ResourceOperations for installed components, InspectDocument for the native tree, GetView for visual evidence, and TestPython for isolated assertions.",
            "Call GetHelp again for the task topic before guessing API names.",
        ],
        "related": ["python", "documents", "workbenches", "resources", "validation", "blocked"],
    },
    "python": {
        "guidance": [
            "ExecutePython runs in live FreeCAD with App and Gui preloaded. Imports and variables persist across calls.",
            "Return the last expression or assign _result. Call doc.recompute() after edits.",
            "Never pass a bare number as a dimension. Assign explicit strings such as '2 mm' or '0.25 in'; for APIs requiring numeric internal units, use App.Units.Quantity('0.25 in').Value. Raw geometry numbers are internal units, not the UI schema.",
            "Discover the installed API through ExecutePython: use dir(), help(), inspect.signature(), module.__file__, and App.getHomePath(). This stays version-correct without copied documentation.",
            "An exception does not roll back earlier statements. Inspect live state before retrying; use document transactions when atomicity matters.",
            "A timeout stops waiting, not execution. Check GetRuntimeStatus before retrying.",
        ],
        "related": ["inspection", "validation", "blocked"],
    },
    "documents": {
        "guidance": [
            "Use DocumentOperations—not ExecutePython—for list, new, open, activate, save, save_as, reload, and close.",
            "Saving does not close a document. reload and close require discard_changes=true when modified; save_as requires overwrite=true before replacing a file.",
            "Use internal document names returned by DocumentOperations. Preserve unrelated open documents.",
        ],
        "related": ["inspection", "validation"],
    },
    "workbenches": {
        "guidance": [
            "A missing dedicated MCP tool does not mean a workbench is unavailable: import its Python modules with ExecutePython.",
            "Never infer activation identifiers from UI labels. Read Gui.listWorkbenches(); common identifiers include CAMWorkbench and FemWorkbench.",
            "Use module.__file__, dir(), help(), and inspect.signature() against the running installation because workbench APIs vary by FreeCAD version.",
            "GUI-only dialogs, hardware, and external solvers still require explicit acceptance tests.",
        ],
        "related": ["python", "resources", "validation", "fem", "cam", "blocked"],
    },
    "resources": {
        "guidance": [
            "ResourceOperations provides one interface for installed component providers such as Fasteners, FCGear, STEMFIE, and Parts Library.",
            "Call action=providers, then search with a short query. Use the returned stable resource_id with inspect before insert when sizes or parameters matter.",
            "insert requires the internal document name. Fasteners accept properties such as Diameter, Length, and Thread; attach_to uses ObjectName.Edge1 or ObjectName.Face1.",
            "FCGear inspect returns its installed parameter schema; use exact lowercase names such as module, num_teeth, height, helix_angle, and axle_hole.",
            "STEMFIE inspect returns the installed part parameters and descriptions. Some numeric parameters are STEMFIE Block Units (BU), not FreeCAD lengths; follow the returned description.",
            "Dimensional properties require explicit unit strings. freecad_units reports the configured profile schema; each inspected quantity includes the actual preferred unit FreeCAD selected for its magnitude.",
            "File-backed FCStd and STEP resources are discovered dynamically. Search results are references; nothing is inserted until action=insert.",
        ],
        "related": ["documents", "workbenches", "inspection", "validation"],
    },
    "inspection": {
        "guidance": [
            "InspectDocument without object_name returns the compact native GUI tree; with object_name it returns links and property names.",
            "Object names are internal Names, not Labels. Request only needed property values.",
            "InspectDocument covers document-object properties. Inspect ViewObject properties through ExecutePython.",
            "Use GetView only after activating the intended document and orienting/framing its activeView.",
        ],
        "related": ["python", "documents", "validation"],
    },
    "validation": {
        "guidance": [
            "Validate in layers: Python assertions, InspectDocument tree/properties, GetView, save, then TestPython against the saved .FCStd when headless verification applies.",
            "TestPython is a fresh FreeCADCmd process: it has App and the live profile's unit settings but no Gui or live variables; document_path contains only saved state.",
            "Do not claim a workbench works from imports alone. Exercise a real operation and verify its native outputs.",
        ],
        "related": ["inspection", "fem", "cam", "blocked"],
    },
    "fem": {
        "guidance": [
            "Use ExecutePython with ObjectsFem and the installed solver modules; activate FemWorkbench only for presentation.",
            "A valid study needs native analysis, material, mesh, constraints, solver, results, and numerical checks such as load/reaction balance.",
            "After loading results, a FemPostPipeline may still have ViewObject.Field='None'. Select the intended field, update color bars, frame the view, and verify with GetView.",
            "Solver availability is external state; discover bundled/configured binaries and run a real solve before claiming support.",
        ],
        "related": ["workbenches", "inspection", "validation"],
    },
    "cam": {
        "guidance": [
            "Use ExecutePython and installed Path modules. Activate CAMWorkbench; PathWorkbench is not its UI identifier.",
            "Build a valid solid, create a Path.Main.Job, then configure its native Stock, SetupSheet, tool controllers, operations, and PostProcessor.",
            "A new Job may create default Stock, SetupSheet, and a default tool controller. Inspect them before creating duplicates.",
            "Select geometry by verified internal subelement names. Recompute each operation and assert its Path contains finite, safe commands before posting.",
            "The Machine asset model is distinct from a Job's executable setup. Machine limits, postprocessor, work coordinate system, stock, workholding, feeds, speeds, and tools must agree.",
            "ToolBit shape defaults may be copied when attached; verify the attached document object's dimensions.",
            "A rendered path is not a material-removal simulation. Run the installed simulator when its Python surface is callable; otherwise report that exact gap.",
            "Post to a named output file without opening an editor, inspect the G-code, save the .FCStd, and validate the saved job separately.",
        ],
        "related": ["python", "workbenches", "inspection", "validation", "blocked"],
    },
    "blocked": {
        "guidance": [
            "During an MCP acceptance test, use only MCP tools. Do not inspect the host repository or change the MCP to conceal a product gap.",
            "First use ExecutePython API discovery and TestPython isolation. If still blocked, report the exact missing callable, documentation, transport, or observation capability.",
            "MCP development is a separate, explicit phase. After changes, restart the MCP and client, then repeat the acceptance test using only the production tools.",
        ],
        "related": ["start", "python", "validation"],
    },
}


def get_help_content(topic: HelpTopic = "start") -> dict:
    """Return one focused help topic with discoverable related topics."""
    return {"topic": topic, **_HELP[topic]}


HELP_TOPICS = get_args(HelpTopic)
