# Focused Python MCP validation

Validated on 2026-09-06 against the official Linux x86_64 FreeCAD 1.1.3
Python 3.11 AppImage, revision `20260725`, with MCP SDK 1.23.0 and an external
Python 3.12 MCP process. The GUI ran under Xvfb with a separate profile and
the addon loaded directly from this checkout.

AppImage SHA-256:
`3a853eb69ee595f779f2255dbf80a765926981d8ff68903cefee4dfb03a8f5ef`

## Branch sequence

1. `feat/python-session`: persistent execution, source tracebacks and status;
   tested before replacing the original interface (52 unit tests plus live
   create/edit/assert/correct and timeout/recovery checks).
2. `refactor/python-tool-surface`: replace the modeling tools and their backend
   wrappers with Python execution, image capture and runtime health (32 unit
   tests plus the real GUI/MCP integration suite including FEM).
3. `feat/isolated-python-tests`: add disposable FreeCADCmd workers and validate
   the complete four-tool interface.

These branches build on one another. The earlier five module-extraction
branches and standalone reload fix remain separate alternatives.

## Final checks

`uv run pytest -q`: 40 passed, 1 skipped. The skip is the deliberately opt-in
real GUI integration test, which was also run explicitly:

```bash
FREECAD_MCP_INTEGRATION=1 FREECAD_MCP_FEM=1 \
  uv run pytest -q -s tests/integration
```

Result: 1 passed; `REAL_FREECAD_ISOLATED_TESTS_PASS` and
`REAL_FREECAD_FOCUSED_MCP_PASS`.

The test uses a real MCP client over stdio, the actual Python MCP server,
XML-RPC, the real FreeCAD GUI thread, and separate native FreeCADCmd processes.
It checks:

- Exactly four registered tools and proper MCP error flags.
- Persistent Python variables, results, stdout/stderr, syntax errors,
  assertion tracebacks, correction and retry.
- Native document/object creation, editing, Sketcher geometry/constraints,
  solid booleans, volume/validity assertions, and document cleanup.
- PNG capture, FCStd reload retaining the internal name, STEP export/read,
  and merging a saved document using native Python.
- Responsive status during a busy/stuck live cell and recovery afterward.
- Headless assertions and correction, isolated namespace, copied-document
  edits preserving both the original file and unsaved live changes.
- Forced test timeout, partial output retention, abnormal worker exit,
  workspace removal, concurrent live execution, and successful worker retry.
- Real Gmsh meshing and CalculiX solving in both execution environments.

Final FEM run (coarse smoke-test mesh; not a converged engineering analysis):

| Execution | Nodes | Max von Mises (MPa) | Max displacement (mm) |
| --- | ---: | ---: | ---: |
| Disposable headless worker | 198 | 32.4228 | 0.115005 |
| Live GUI | 198 | 31.1856 | 0.113092 |

Meshing is not deterministic; values are checked against broad beam-theory
sanity bounds. The captured PNG was also visually inspected.

Compilation, `git diff --check`, and source/wheel builds passed. Windows and
macOS were not exercised. Headless tests do not cover GUI workbench behavior
or unsaved live state, and process isolation is not a security sandbox.
