from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import time

import pytest

ADDON = Path(__file__).resolve().parents[1] / "addon/FreeCADMCP"
sys.path.insert(0, str(ADDON))
from rpc_server import python_testing


@pytest.fixture
def runner(monkeypatch):
    original_popen = subprocess.Popen
    fixture = Path(__file__).with_name("fixtures") / "freecadcmd_stub.py"

    def launch(command, **kwargs):
        return original_popen([sys.executable, str(fixture), *command[1:]], **kwargs)

    monkeypatch.setattr(python_testing.subprocess, "Popen", launch)
    return python_testing.PythonTestRunner("test-freecadcmd", ["1", "1", "3", "test-build"])


def test_worker_results_and_workspace_cleanup(runner):
    result = runner.run("import os\nprint('worker')\n{'cwd': os.getcwd(), 'value': 42}")
    assert result["success"] and result["exit_code"] == 0
    assert result["stdout"] == "worker\n"
    assert result["result"]["value"] == 42
    assert not Path(result["result"]["cwd"]).exists()
    assert result["workspace_removed"]


def test_document_changes_affect_only_the_copy(runner, tmp_path):
    source = tmp_path / "saved.FCStd"
    source.write_text("original")
    result = runner.run(
        "from pathlib import Path\nPath(doc.FileName).write_text('modified')",
        str(source),
    )
    assert result["success"]
    assert source.read_text() == "original"


def test_assertions_and_process_exit_are_reported(runner):
    failed = runner.run("assert 1 == 2, 'expected mismatch'")
    assert not failed["success"]
    assert failed["error"]["type"] == "AssertionError"
    assert "assert 1 == 2" in failed["error"]["traceback"]
    crashed = runner.run("import os\nos._exit(7)")
    assert not crashed["success"]
    assert crashed["code"] == "TEST_WORKER_EXITED"
    assert crashed["exit_code"] == 7


def test_timeout_kills_worker_and_next_test_succeeds(runner):
    timed_out = runner.run("print('entered')\nwhile True: pass", timeout_seconds=1)
    assert timed_out["code"] == "TEST_TIMEOUT" and timed_out["timed_out"]
    assert timed_out["workspace_removed"]
    assert "entered" in timed_out["process_stdout"]
    assert runner.status()["current_test"] is None
    assert runner.run("6 * 7")["result"] == 42


def test_concurrent_tests_are_rejected_and_status_is_readable(runner):
    with ThreadPoolExecutor() as workers:
        future = workers.submit(runner.run, "import time\ntime.sleep(0.3)\n42")
        for _ in range(100):
            if runner.status()["current_test"]:
                break
            time.sleep(0.01)
        assert runner.status()["current_test"]["test_id"]
        assert runner.run("1")["code"] == "TEST_WORKER_BUSY"
        assert future.result()["result"] == 42


def test_version_mismatch_rejected_before_running_code(runner):
    runner.expected_version = ["1", "0", "0", "different"]
    result = runner.run("raise AssertionError('should not execute')")
    assert result["code"] == "FREECAD_VERSION_MISMATCH"


def test_native_process_output_is_bounded(runner):
    result = runner.run("import os\nos.write(1, b'a' * 100000)\n42")
    assert result["success"]
    assert result["process_stdout_truncated"]
    assert len(result["process_stdout"]) == python_testing.MAX_OUTPUT_CHARS


def test_missing_command_has_actionable_diagnostic():
    result = python_testing.PythonTestRunner(None, []).run("42")
    assert result["code"] == "FREECADCMD_NOT_FOUND"
    assert "FREECAD_MCP_FREECADCMD" in result["error"]
