[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/neka-nat-freecad-mcp-badge.png)](https://mseep.ai/app/neka-nat-freecad-mcp)

# FreeCAD MCP

This fork of [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp)
lets an AI model control FreeCAD by writing Python.
Install both the MCP server and addon from this checkout; the published package
and older addons expose a different interface.

## Demo

### Design a flange

![Flange demo](./assets/freecad_mcp4.gif)

### Design a toy car

![Toy car demo](./assets/make_toycar4.gif)

### Design a part from a 2D drawing

![Input 2D drawing](./assets/b9-1.png)

![2D drawing demo](./assets/from_2ddrawing.gif)

The original conversation is available in the
[upstream shared transcript](https://claude.ai/share/7b48fd60-68ba-46fb-bb21-2fbb17399b48).

## Python-first tool surface

| Tool | Purpose |
| --- | --- |
| `GetHelp(topic="start")` | Learn the Python-first workflow and focused guidance for documents, workbenches, FEM, CAM, validation, or blockers. |
| `DocumentOperations(action, document=None, path=None, ...)` | List, create, open, activate, save, reload, or safely close live FreeCAD documents. |
| `ExecutePython(code, timeout_seconds=90)` | Run Python in the live FreeCAD GUI, retaining variables between calls. |
| `InspectDocument(document=None, object_name=None, properties=None, max_depth=6)` | Read the native GUI tree or focused object dependencies and property values. |
| `GetView(width=1024, height=768)` | Return the current 3D view as an MCP PNG image. |
| `GetRuntimeStatus()` | Read FreeCAD version and execution health, even while the GUI is busy. |
| `TestPython(code, document_path=None, timeout_seconds=60)` | Run assertions/scripts in a fresh FreeCADCmd process, optionally opening a saved document copy. |

Document lifecycle has one focused tool. Objects, sketches, libraries,
imports/exports, assemblies, and FEM are handled by the native Python API.
There are no separate modeling tools.

## Install the FreeCAD addon

FreeCAD 1.1.3 is the tested configuration. FreeCAD addon directories include:

- Windows: `%APPDATA%\FreeCAD\Mod\`
- macOS:
  - FreeCAD 1.1: `~/Library/Application Support/FreeCAD/v1-1/Mod/`
  - FreeCAD 1.0: `~/Library/Application Support/FreeCAD/v1-0/Mod/`
- Linux:
  - Ubuntu: `~/.FreeCAD/Mod/`
  - Ubuntu Snap: `~/snap/freecad/common/Mod/`
  - Debian: `~/.local/share/FreeCAD/Mod/`
  - Arch/CachyOS FreeCAD 1.1: `~/.local/share/FreeCAD/v1-1/Mod/`
  - Flatpak: `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/`

`App.getUserAppDataDir()` in FreeCAD's Python console reports the active profile
directory. Place this checkout's `addon/FreeCADMCP` directory in that profile's
`Mod` directory. For example:

```bash
git clone https://github.com/10-X-eng/freecad-mcp.git
cd freecad-mcp

# Ubuntu
mkdir -p ~/.FreeCAD/Mod/
cp -r addon/FreeCADMCP ~/.FreeCAD/Mod/

# Debian
mkdir -p ~/.local/share/FreeCAD/Mod/
cp -r addon/FreeCADMCP ~/.local/share/FreeCAD/Mod/

# Arch/CachyOS FreeCAD 1.1
mkdir -p ~/.local/share/FreeCAD/v1-1/Mod/
cp -r addon/FreeCADMCP ~/.local/share/FreeCAD/v1-1/Mod/

# Flatpak
mkdir -p ~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/
cp -r addon/FreeCADMCP ~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/

# macOS FreeCAD 1.1
mkdir -p ~/Library/Application\ Support/FreeCAD/v1-1/Mod/
cp -r addon/FreeCADMCP ~/Library/Application\ Support/FreeCAD/v1-1/Mod/
```

Restart FreeCAD after installing or updating the addon. Select **MCP Addon**
from the workbench list:

![MCP Addon in the workbench list](./assets/workbench_list.png)

Start the bridge with **Start RPC Server** in the **FreeCAD MCP** toolbar:

![Start RPC Server](./assets/start_rpc_server.png)

### Auto-start the RPC server

By default, start the RPC server manually whenever FreeCAD opens. To start it
automatically, switch to the MCP Addon workbench and enable **FreeCAD MCP →
Auto-Start Server**. The setting persists across sessions and can be disabled
from the same menu.

## Configure an MCP client

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then point
the client at this checkout. For Claude Desktop, edit
`claude_desktop_config.json`; other stdio MCP clients use the same command:

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
This fork removes the old tool names and `--only-text-feedback` flag.
Execution returns text; request images explicitly with `GetView`.

## Remote connections

The FreeCAD bridge listens on localhost by default. To control it from another
trusted machine:

1. Enable **Remote Connections** in the **FreeCAD MCP** toolbar. The bridge will
   bind to `0.0.0.0` after it is restarted.
2. Select **Configure Allowed IPs** and enter comma-separated IP addresses or
   CIDR ranges, for example `192.168.1.100, 10.0.0.0/24`.
3. Restart the RPC server.
4. Add `--host` with the FreeCAD machine's address to the MCP client command:

```json
{
  "mcpServers": {
    "freecad": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/freecad-mcp", "run", "freecad-mcp",
        "--host", "192.168.1.100"
      ]
    }
  }
}
```

Remote access is disabled by default. Allow only trusted clients; Python cells
run with the FreeCAD host user's filesystem and network privileges. The `--host`
value must be a valid IPv4 address, IPv6 address, or hostname.

## Write, inspect, correct

Use `DocumentOperations` for file lifecycle instead of repeating boilerplate
Python. Its actions are `list`, `new`, `open`, `activate`, `save`, `save_as`,
`reload`, and `close`. It reports FreeCAD's actual internal document name,
label, path, active/modified state, and object count. `open` and `save_as` use
`.FCStd` paths on the FreeCAD host. `save_as` refuses to replace another file
unless `overwrite=true`; `reload` and `close` refuse to discard modified state
unless `discard_changes=true`.

Call `InspectDocument` without `object_name` for a compact hierarchy built from
FreeCAD's native GUI providers. Hidden objects and actionable state are marked;
routine `Up-to-date` state is omitted. Set `object_name` to an internal name for
its parents, children, dependencies, dependents, and visible property names.
Pass only the property names whose values are needed. Quantities use the user's
preferred unit, placements become vectors/quaternions, links become object
names, and shapes become bounded volume/size summaries rather than serialized
geometry.

Submit a cell to `ExecutePython`:

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

Results contain only the returned value and non-empty stdout/stderr. A cell
with neither returns `{"ok":true}`. Exceptions return a source traceback in
`error` and set MCP `isError`; transport failures include an error message.
Python exceptions do not undo changes already made; inspect the document
before retrying. Restarting FreeCAD clears the namespace.

Lists, dictionaries and scalars return as JSON. Other values return type/repr;
select the properties you need explicitly. Output/result sizes and source
history are bounded; a `truncated` list identifies shortened output fields.
Python stdout/stderr are captured;
native FreeCAD console diagnostics may still appear only in Report View.

Runtime status returns the FreeCAD version, session identity, and GUI/test-worker
states. A changed session ID means live variables were reset. Busy/stuck status
adds elapsed time. Routine results omit opaque IDs, timings, empty fields and
default flags; internal source history is retained for cross-cell tracebacks.

For visual verification, set the camera in Python and then call `GetView`:

```python
Gui.activeDocument().activeView().viewIsometric()
Gui.activeDocument().activeView().fitAll()
```

Use `dir(App)`, `help(App.openDocument)`, `doc.supportedTypes()`,
`obj.PropertiesList`, and `obj.getTypeIdOfProperty("Length")` to explore the
installed API. The [official scripting basics](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/FreeCAD_Scripting_Basics.md)
explain the App/Gui distinction. A complete Python FEM example is in
[examples/cantilever_fem.py](examples/cantilever_fem.py). A complete native
CAM Job with two tools, GRBL postprocessing and voxel material-removal
simulation is in [examples/fixture_plate_cam.py](examples/fixture_plate_cam.py).

## Execution and testing

Live cells run on FreeCAD's GUI thread. `timeout_seconds` accepts 1–3600 seconds;
it limits the wait and cannot terminate an operation that has already started.
A timed-out running cell marks dispatch as stuck and later GUI calls fail
immediately until it finishes. Check `GetRuntimeStatus` before retrying.
If execution never finishes, restart FreeCAD manually. Python has the same
filesystem and process privileges as FreeCAD; it is not a security sandbox.
Python remains available while menus or non-blocking modal dialogs are open,
so it can inspect and close them through Qt. Prefer `dialog.open()`/`show()`;
calling a blocking `dialog.exec()` inside a cell keeps that cell running and
prevents another live cell from entering until it returns. Avoid editing the
same document manually while a model is modifying it.

Use `TestPython` to check a complete script before applying it to the live
document. Every test starts a new FreeCADCmd on the FreeCAD host with its own
profile and temporary workspace. The worker must match the live FreeCAD
version and build. `App`/`FreeCAD` are preloaded; live variables and `Gui` are
unavailable. When `document_path` is supplied, it must be an absolute `.FCStd`
path on that host; the temporary copy is opened as `doc`. It includes saved
state only. Linked external files are not copied.

The worker uses the same compact result format. Native diagnostics are retained,
but the startup banner and exact duplicate Python output are removed. Failures
include error codes; abnormal exits include the exit code. Output printed before
a timeout remains in the process logs. The worker is terminated on timeout and its
temporary workspace is removed. One test runs at a time; live execution and
runtime status remain available. Return values instead of temporary artifact
paths. As with live execution, Python retains the host user's filesystem and
network access; this isolates FreeCAD state, not untrusted code.

FreeCADCmd is located beside the running FreeCAD installation. For layouts
where it is elsewhere, set `FREECAD_MCP_FREECADCMD` to its executable path
**before launching FreeCAD**. This setting belongs to the addon host, including
when the MCP client connects remotely. `GetRuntimeStatus` reports availability
and whether a test is running. GUI workbenches and views still need live testing.

Run unit tests with `uv run pytest -q`. The integration test is opt-in and must
target a separate FreeCAD GUI/profile with this addon installed:

The bootstrap script [tests/integration/start_freecad.py](tests/integration/start_freecad.py)
can also be passed to that GUI's executable to load the addon directly from
this checkout. Use a separate user config and profile when launching it.

```bash
FREECAD_MCP_INTEGRATION=1 uv run pytest -q -s tests/integration
FREECAD_MCP_INTEGRATION=1 FREECAD_MCP_FEM=1 uv run pytest -q -s tests/integration
FREECAD_MCP_INTEGRATION=1 FREECAD_MCP_CAM=1 uv run pytest -q -s tests/integration
```

It checks the actual MCP protocol, document lifecycle and dirty-state guards,
native tree/property inspection, geometry, failed assertions and corrected
code, sketches/booleans, PNG capture, FCStd/STEP round trips, busy/stuck status
and recovery. It also verifies disposable process assertions, source-document
preservation, forced timeout, abnormal exit and successful retry. The second
command also executes real Gmsh/CalculiX. The third builds native facing,
pocketing, drilling and profiling paths, posts GRBL G-code, completes the
native voxel-removal simulation, saves the FCStd and reopens it in a fresh
FreeCADCmd process.
Set `FREECAD_MCP_HOST`/`FREECAD_MCP_PORT` to target a different test bridge.
The FEM test may configure bundled solver paths in that isolated profile.
Set `FREECAD_MCP_IMAGE_PATH` to save its captured PNG for inspection. Live
integration has been verified on Linux with the official FreeCAD 1.1.3 build;
Windows and macOS have not been exercised here.

## Contributors

<a href="https://github.com/neka-nat/freecad-mcp/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=neka-nat/freecad-mcp" alt="Upstream contributors" />
</a>

Made with [contrib.rocks](https://contrib.rocks). Original authorship and license
are retained.
