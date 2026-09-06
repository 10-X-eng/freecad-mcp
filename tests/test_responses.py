import pytest

from freecad_mcp.responses import execution_feedback, runtime_feedback


BANNER = (
    "FreeCAD 1.1.3, Libs: 1.1.3R20260725 (Git shallow)\n"
    "(C) 2001-2026 FreeCAD contributors\n"
    "FreeCAD is free and open-source software licensed under the terms of LGPL2+ license.\n\n"
)


@pytest.mark.parametrize("value", [42, 0, False, None, "", [], {}, {"volume": 6000}])
def test_success_returns_only_the_requested_value(value):
    assert execution_feedback({
        "success": True, "has_result": True, "result": value,
        "session_id": "session", "cell_id": "cell", "test_id": "test",
        "result_type": "ignored", "duration_seconds": 0.02,
        "total_duration_seconds": 0.1, "workspace_removed": True,
        "exit_code": 0, "timed_out": False, "stdout": "", "stderr": "",
        "result_truncated": False, "stdout_truncated": False,
        "process_stdout": BANNER, "process_stderr": "",
    }) == {"result": value}


def test_no_result_and_no_output_has_a_small_acknowledgement():
    assert execution_feedback({"success": True, "has_result": False, "result": None}) == {"ok": True}


def test_python_output_is_not_repeated_in_process_logs():
    assert execution_feedback({
        "success": True, "stdout": "42\n", "process_stdout": BANNER + "42\n",
        "stderr": "warning\n", "process_stderr": "warning\n",
    }) == {"stdout": "42\n", "stderr": "warning\n"}


def test_native_diagnostics_are_not_silently_discarded():
    assert execution_feedback({
        "success": True, "result": 42,
        "process_stdout": BANNER + "Mesh warning\n", "process_stderr": "solver warning\n",
    }) == {"result": 42, "process_stdout": "Mesh warning\n", "process_stderr": "solver warning\n"}


def test_traceback_keeps_source_and_external_frames_without_runner_bookkeeping():
    feedback = execution_feedback({
        "success": False, "cell_id": "abc123", "stdout": "checking\n",
        "error": {"type": "AssertionError", "message": "wrong volume", "traceback": (
            'Traceback (most recent call last):\n'
            '  File "/repo/addon/FreeCADMCP/rpc_server/python_session.py", line 166, in run\n'
            '    exec(compile(tree, filename, "exec"), self.namespace)\n'
            '  File "<freecad-mcp-abc123>", line 2, in <module>\n'
            '    check_volume()\n'
            '  File "<freecad-mcp-def456>", line 4, in check_volume\n'
            '    assert volume == 24\n'
            'AssertionError: wrong volume\n'
        )},
    })
    assert set(feedback) == {"error", "stdout"}
    assert 'File "<cell>", line 2' in feedback["error"]
    assert 'File "<earlier cell>", line 4' in feedback["error"]
    assert "assert volume == 24" in feedback["error"]
    assert "AssertionError: wrong volume" in feedback["error"]
    assert "python_session.py" not in feedback["error"]
    assert "abc123" not in feedback["error"]


def test_timeout_keeps_partial_process_output_and_actionable_error():
    assert execution_feedback({
        "success": False, "code": "TEST_TIMEOUT", "error": "Worker killed after 1s",
        "exit_code": -9, "timed_out": True, "workspace_removed": True,
        "process_stdout": BANNER + "entered\n",
    }) == {"error": "Worker killed after 1s", "code": "TEST_TIMEOUT", "process_stdout": "entered\n"}


def test_abnormal_exit_keeps_the_exit_code():
    assert execution_feedback({
        "success": False, "code": "TEST_WORKER_EXITED", "error": "No result", "exit_code": 7,
    })["exit_code"] == 7


def test_stuck_error_drops_only_the_internal_operation_id():
    feedback = execution_feedback({
        "success": False, "code": "GUI_DISPATCH_STUCK",
        "error": "execute_python:" + "a" * 32 + " is still running; wait or restart FreeCAD",
    })
    assert feedback == {"code": "GUI_DISPATCH_STUCK", "error": "execute_python is still running; wait or restart FreeCAD"}


def test_version_mismatch_keeps_both_versions():
    feedback = execution_feedback({
        "success": False, "code": "FREECAD_VERSION_MISMATCH", "error": "Mismatched worker",
        "expected_version": ["1", "1", "3"], "freecad_version": ["1", "0", "0"],
    })
    assert feedback["expected_version"] != feedback["freecad_version"]


def test_truncation_is_never_hidden():
    assert execution_feedback({
        "success": True, "result": "short", "result_truncated": True,
        "stdout": "partial", "stdout_truncated": True, "process_stderr_truncated": True,
    }) == {"result": "short", "stdout": "partial", "truncated": ["result", "stdout", "process_stderr"]}


def test_idle_status_has_identity_and_availability_without_empty_fields_or_history():
    assert runtime_feedback({
        "success": True, "rpc_server": "running", "freecad_version": ["1", "1", "3", "build"],
        "session_id": "session", "current_cell": None, "recent_cells": [{"cell_id": "unused"}],
        "gui_dispatch": {"state": "healthy", "task_id": 0, "operation": "", "running_for_seconds": 0},
        "test_worker": {"available": True, "command": "/unused/path", "current_test": None},
    }) == {
        "freecad_version": "1.1.3", "session_id": "session",
        "gui": {"state": "idle"}, "test_worker": {"state": "ready"},
    }


def test_busy_status_retains_elapsed_time_without_unusable_ids():
    status = runtime_feedback({
        "gui_dispatch": {"state": "stuck", "operation": "execute_python:opaque-id",
                         "running_for_seconds": 12, "timeout_seconds": 10},
        "test_worker": {"available": True, "current_test": {"test_id": "opaque", "running_for_seconds": 4}},
    })
    assert status["gui"] == {"state": "stuck", "operation": "execute_python", "running_seconds": 12, "timeout_seconds": 10}
    assert status["test_worker"] == {"state": "running", "running_seconds": 4}


def test_unavailable_worker_and_connection_failures_are_actionable():
    assert "FREECAD_MCP_FREECADCMD" in runtime_feedback({"test_worker": {"available": False}})["test_worker"]["error"]
    assert runtime_feedback({"success": False, "error": {"type": "ConnectionRefusedError", "message": "Start FreeCAD"}}) == {"error": "ConnectionRefusedError: Start FreeCAD"}
