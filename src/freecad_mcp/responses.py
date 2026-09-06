"""Model-facing feedback; keep transport/debug bookkeeping inside the bridge."""

import re


_BANNER = re.compile(
    r"\AFreeCAD [^\r\n]+\r?\n"
    r"\(C\) [^\r\n]*FreeCAD[^\r\n]*\r?\n"
    r"FreeCAD is free and open-source software licensed[^\r\n]*\r?\n(?:\r?\n)?"
)
_RUNNER_FRAME = re.compile(
    r'(?m)^  File "[^"\n]*[/\\]rpc_server[/\\](?:python_session|python_test_worker)\.py",'
    r" line \d+, in (?:run|main)\n(?:    [^\n]*\n)*"
)
_CELL_FRAME = re.compile(r'File "<freecad-mcp-([0-9a-f]+)>"')


def _error_text(error, cell_id=None):
    if not isinstance(error, dict):
        return str(error)
    if error.get("traceback"):
        trace = _RUNNER_FRAME.sub("", error["traceback"])
        return _CELL_FRAME.sub(
            lambda match: 'File "<cell>"' if match[1] == cell_id else 'File "<earlier cell>"',
            trace,
        ).rstrip()
    return ": ".join(str(error[key]) for key in ("type", "message") if error.get(key))


def execution_feedback(data):
    """Only return values, nonempty output, and actionable failure information."""
    out = {}
    if not data.get("success", True):
        out["error"] = _error_text(data.get("error", "Execution failed"), data.get("cell_id"))
        if data.get("code") == "GUI_DISPATCH_STUCK":
            out["error"] = re.sub(r"execute_python:[0-9a-f]{32}\b", "execute_python", out["error"])
        if data.get("code"):
            out["code"] = data["code"]
        if data.get("code") == "TEST_WORKER_EXITED" and "exit_code" in data:
            out["exit_code"] = data["exit_code"]
        if data.get("code") == "FREECAD_VERSION_MISMATCH":
            for key in ("expected_version", "freecad_version"):
                if key in data:
                    out[key] = data[key]
    elif data.get("has_result", "result" in data):
        # False, zero, empty collections/strings, and explicit None are results.
        out["result"] = data.get("result")

    for channel in ("stdout", "stderr"):
        captured = data.get(channel, "")
        if captured:
            out[channel] = captured
        native = data.get("process_" + channel, "")
        if channel == "stdout":
            native = _BANNER.sub("", native, count=1)
        # The worker tees Python streams to its process pipes for crash recovery.
        # Suppress only an exact duplicate. Mixed/native diagnostics are retained.
        if native and native != captured:
            out["process_" + channel] = native

    truncated = [
        key for key in ("result", "stdout", "stderr", "process_stdout", "process_stderr")
        if data.get(key + "_truncated")
    ]
    if truncated:
        out["truncated"] = truncated
    return out or {"ok": True}


def runtime_feedback(data):
    """Status is the place for version/session identity, not every Python result."""
    if not data.get("success", True):
        return execution_feedback(data)
    dispatch = data.get("gui_dispatch", {})
    state = dispatch.get("state", "unknown")
    gui = {"state": "idle" if state == "healthy" else state}
    if state in ("busy", "stuck"):
        # The opaque cell ID suffix has no model-facing lookup/cancellation API.
        gui["operation"] = dispatch.get("operation", "").partition(":")[0]
        gui["running_seconds"] = dispatch.get("running_for_seconds", 0)
        if state == "stuck":
            gui["timeout_seconds"] = dispatch.get("timeout_seconds", 0)
    worker = data.get("test_worker", {})
    current = worker.get("current_test")
    test = {"state": "running" if current else "ready" if worker.get("available") else "unavailable"}
    if current:
        test["running_seconds"] = current.get("running_for_seconds", 0)
    elif not worker.get("available"):
        test["error"] = "Set FREECAD_MCP_FREECADCMD on the FreeCAD host, then restart FreeCAD."
    out = {"gui": gui, "test_worker": test}
    if data.get("freecad_version"):
        out["freecad_version"] = ".".join(data["freecad_version"][:3])
    if data.get("session_id"):
        out["session_id"] = data["session_id"]
    if data.get("units"):
        out["units"] = data["units"]
    return out
