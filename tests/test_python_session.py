import importlib.util
import json
from pathlib import Path
import threading

import pytest


SESSION_PATH = Path(__file__).resolve().parents[1] / "addon/FreeCADMCP/rpc_server/python_session.py"
spec = importlib.util.spec_from_file_location("_python_session_test", SESSION_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_iterate_after_assertion_with_source_traceback():
    session = module.PythonSession({"App": object()})
    assert session.run("x = 20\ndef area(w):\n    return x * w")["success"]
    failed = session.run("print('checking')\nassert area(3) == 80")
    assert not failed["success"]
    assert failed["stdout"] == "checking\n"
    assert failed["error"]["type"] == "AssertionError"
    assert "assert area(3) == 80" in failed["error"]["traceback"]
    assert session.run("x = 40\narea(3)")["result"] == 120
    assert session.run("_ + 1")["result"] == 121


def test_result_contract_handles_native_opaque_and_recursive_values():
    session = module.PythonSession({})
    result = session.run("_result = {'ok': True, 'large': 2**100, 'missing': None}")
    assert result["result"] == {"ok": True, "large": 2**100, "missing": None}
    assert not session.run("x = 3")["has_result"]
    assert session.run("x = []\nx.append(x)\nx")["result"] == ["<recursive reference>"]
    assert session.run("object()")["result"]["type"] == "object"
    json.dumps(session.run("float('nan')"), allow_nan=False)


@pytest.mark.parametrize("code, error", [
    ("if", "SyntaxError"), ("raise SystemExit(2)", "SystemExit"),
    ("raise KeyboardInterrupt()", "KeyboardInterrupt"),
])
def test_failures_return_diagnostics_without_killing_next_cell(code, error):
    session = module.PythonSession({})
    result = session.run(code)
    assert result["error"]["type"] == error
    assert session.run("1 + 1")["result"] == 2


def test_future_import_applies_to_entire_cell():
    session = module.PythonSession({})
    result = session.run("from __future__ import annotations\ndef f(x: Missing): pass\nf.__annotations__")
    assert result["result"] == {"x": "Missing"}


def test_restore_aliases_capture_stderr_and_bound_output():
    app = object()
    session = module.PythonSession({"App": app})
    session.run("App = None\n__builtins__ = None")
    result = session.run("import sys\nprint('oops', file=sys.stderr)\nprint('a' * 100000)\nApp")
    assert session.namespace["App"] is app
    assert result["stderr"] == "oops\n"
    assert result["stdout_truncated"]
    assert len(result["stdout"]) == module.MAX_OUTPUT_CHARS
    assert len(session.run("'a' * 100000")["result"]) <= module.MAX_RESULT_CHARS


def test_other_threads_output_is_not_captured():
    session = module.PythonSession({"threading": threading})
    result = session.run("worker = threading.Thread(target=lambda: print('elsewhere'))\nworker.start()\nworker.join()\nprint('cell')")
    assert result["stdout"] == "cell\n"


def test_history_is_bounded_and_oversized_code_rejected():
    session = module.PythonSession({})
    for _ in range(module.MAX_HISTORY + 2):
        session.run("1")
    assert len(session.status()["recent_cells"]) == module.MAX_HISTORY
    assert session.status()["current_cell"] is None
    with pytest.raises(ValueError):
        session.run("x" * (module.MAX_CODE_CHARS + 1))
