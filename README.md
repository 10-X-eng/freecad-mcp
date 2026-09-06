# FreeCAD MCP — Python interface

This development branch lets an AI model control FreeCAD by writing Python.
Install both the MCP server and addon from this checkout; the published package
and older addons expose a different interface.

| Tool | Purpose |
| --- | --- |
| `execute_python(code, timeout_seconds=90)` | Run Python in the live FreeCAD GUI, retaining variables between calls. |
| `get_view(width=1024, height=768)` | Return the current 3D view as an MCP PNG image. |
| `get_runtime_status()` | Read FreeCAD version and execution health, even while the GUI is busy. |

Documents, objects, sketches, libraries, imports/exports, and FEM are all handled
by the native Python API. There are no separate modeling tools.

## Install

Use FreeCAD 1.1.3 for the tested configuration. In FreeCAD's Python console,
`App.getUserAppDataDir()` gives the correct profile directory for your platform.
Put this checkout's `addon/FreeCADMCP` directory inside its `Mod` directory,
restart FreeCAD, select the **MCP Addon** workbench, and click **Start RPC Server**.

The addon retains its toolbar controls for auto-start, remote connections and
allowed IPs. Remote connections are disabled by default. Enable them only for
trusted clients, configure allowed IPs, and restart the RPC server.

Configure your MCP client to run this checkout with [uv](https://docs.astral.sh/uv/):

```json
{
  "mcpServers": {
    "freecad": {
      "command": "uv",
      "args": ["--directory", "/path/to/freecad-mcp", "run", "freecad-mcp"]
    }
  }
}
```

Use `--host HOST` and optionally `--port PORT` for a different bridge address.
This branch removes the old tool names and `--only-text-feedback` flag.
Execution returns text; request images explicitly with `get_view`.

## Write, inspect, correct

Submit a cell to `execute_python`:

```python
doc = App.newDocument("Demo")
box = doc.addObject("Part::Box", "Box")
box.Length, box.Width, box.Height = 20, 15, 10
doc.recompute()
{"volume": box.Shape.Volume, "valid": box.Shape.isValid()}
```

The final expression becomes the returned `result`. Imports, functions and
variables persist in the live FreeCAD process, including across MCP reconnects.
Connected clients share that namespace. A later cell can inspect or modify it:

```python
box.Length = 40
doc.recompute()
assert box.Shape.isValid()
assert abs(box.Shape.Volume - 6000) < 1e-6
box.Shape.Volume
```

You can also assign `_result` explicitly in a cell that ends in a statement.
`_` holds the last successful expression result. `App`/`FreeCAD` and
`Gui`/`FreeCADGui` are restored before every cell. Use `import Part`,
`import Sketcher`, `import Draft`, or other workbench modules as needed.

Results include cell/session IDs, stdout/stderr, duration, and exception
tracebacks with submitted source lines. Failed executions set MCP `isError`.
Python exceptions do not undo changes already made; inspect the document
before retrying. Restarting FreeCAD clears the namespace.

Lists, dictionaries and scalars return as JSON. Other values return type/repr;
select the properties you need explicitly. Output/result sizes and source
history are bounded; truncation is reported. Python stdout/stderr are captured;
native FreeCAD console diagnostics may still appear only in Report View.

For visual verification, set the camera in Python and then call `get_view`:

```python
Gui.activeDocument().activeView().viewIsometric()
Gui.activeDocument().activeView().fitAll()
```

Use `dir(App)`, `help(App.openDocument)`, `doc.supportedTypes()`,
`obj.PropertiesList`, and `obj.getTypeIdOfProperty("Length")` to explore the
installed API. The [official scripting basics](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/FreeCAD_Scripting_Basics.md)
explain the App/Gui distinction. A complete Python FEM example is in
[examples/cantilever_fem.py](examples/cantilever_fem.py).

## Execution and testing

Live cells run on FreeCAD's GUI thread. `timeout_seconds` accepts 1–3600 seconds;
it limits the wait and cannot terminate an operation that has already started.
A timed-out running cell marks dispatch as stuck and later GUI calls fail
immediately until it finishes. Check `get_runtime_status` before retrying.
If execution never finishes, restart FreeCAD manually. Python has the same
filesystem and process privileges as FreeCAD; it is not a security sandbox.

Run unit tests with `uv run pytest -q`. The integration test is opt-in and must
target a separate FreeCAD GUI/profile with this addon installed:

The bootstrap script [tests/integration/start_freecad.py](tests/integration/start_freecad.py)
can also be passed to that GUI's executable to load the addon directly from
this checkout. Use a separate user config and profile when launching it.

```bash
FREECAD_MCP_INTEGRATION=1 uv run pytest -q -s tests/integration
FREECAD_MCP_INTEGRATION=1 FREECAD_MCP_FEM=1 uv run pytest -q -s tests/integration
```

It checks the actual MCP protocol, geometry, failed assertions and corrected
code, sketches/booleans, PNG capture, FCStd/STEP round trips, busy/stuck status
and recovery. The second command also executes real Gmsh/CalculiX.
Set `FREECAD_MCP_HOST`/`FREECAD_MCP_PORT` to target a different test bridge.
The FEM test may configure bundled solver paths in that isolated profile.

Derived from [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp).
Original authorship and license are retained.
