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

## GUI interaction regression (2026-09-06)

Branch `fix/gui-interaction-dispatch` removes the blanket mouse/menu/modal
dispatch gate. A real desktop MCP call timed out before executing; a controlled
modal-dialog probe reproduced the same starvation while status reported healthy.
The fix lets Python inspect/close UI elements without removing the in-flight
task re-entrancy guard or stuck-task protection.

Three regression tests failed before the fix. Afterward, `uv run pytest -q`
reported 44 passed, 1 skipped. The full opt-in suite passed against a separate
real FreeCAD 1.1.3 GUI on port 9876, now including open-modal and open-popup
inspection/closure through MCP. FEM was not rerun for this dispatch-only change;
the earlier FEM results above remain the recorded baseline.

## Compact MCP feedback (2026-09-06)

Branch `refactor/concise-tool-feedback` keeps the same four tools and argument
schemas. It projects the bridge's detailed results into model-facing values,
nonempty output, source errors, and truncation notices. Backend diagnostic
records remain unchanged. Status retains session identity and busy/stuck state;
worker crashes/timeouts retain actionable errors and partial process output.

Tool descriptions shrink from 842 words (including server instructions repeated
per tool by the client) to 165. A simple success is exactly `{"result":42}`.
There is no repeated server-wide instruction paragraph. Explicit null/false/zero
results, native warnings, source lines from earlier cells, truncation and error
codes are covered by tests.

`uv run pytest -q`: 64 passed, 1 skipped. The full real FreeCAD 1.1.3 suite passed
with `FREECAD_MCP_FEM=1` on port 9876, including fresh MCP startup, GUI dialogs,
PNG capture, worker isolation, forced timeout/recovery, and Gmsh/CalculiX in both
GUI and headless execution. Coarse FEM results were 198 nodes, 31.1080 MPa and
0.114718 mm (headless), and 32.4225 MPa and 0.115814 mm (live). These are software
smoke tests, not engineering sign-off. Source/wheel builds and diff checks passed.

The desktop addon bridge was restarted without losing the live Python namespace
or mounting-plate document. A live modal was closed through Python and the plate
was edited from 8 to 10 mm afterward. Codex must restart to load the new MCP
response formatter and tool descriptions.

## Document operations (2026-09-06)

Branch `feat/document-operations` adds one lifecycle tool with `list`, `new`,
`open`, `activate`, `save`, `save_as`, `reload`, and `close` actions. Save-as
protects existing files by default; reload and close protect modified GUI
documents by default. Responses use FreeCAD's actual internal name and report
path, active/modified state, and object count without a screenshot.

The real FreeCAD 1.1.3 integration caught two assumptions that mocks did not:
dirty state is exposed by `Gui.Document.Modified`, and saving through
`App.Document` alone does not clear that GUI flag. The implementation now uses
the GUI save operation and was rerun through a clean MCP/FreeCAD instance. The
test created, saved, listed, protected/reloaded, saved, closed, reopened,
activated, and closed a disposable FCStd document successfully.

`uv run pytest -q`: 77 passed, 1 skipped. The full opt-in test passed against
the official FreeCAD 1.1.3 GUI on port 9876 and printed
`REAL_FREECAD_DOCUMENT_OPERATIONS_PASS`. Compilation, `git diff --check`, and
source/wheel builds also passed. FEM was not rerun for this document-only
change; the earlier real-solver results remain the baseline.
