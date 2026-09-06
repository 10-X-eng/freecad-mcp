"""Disposable FreeCADCmd processes, launched on the FreeCAD host.

Separate documents/profile/process state protect the interactive session.
This is not a filesystem/network security sandbox.
"""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from rpc_server.python_session import MAX_CODE_CHARS, MAX_OUTPUT_CHARS


def find_freecadcmd(freecad_home: str) -> str | None:
    override = os.environ.get("FREECAD_MCP_FREECADCMD")
    candidates = [Path(override)] if override else [
        Path(freecad_home) / "bin" / name
        for name in ("FreeCADCmd.exe", "FreeCADCmd", "freecadcmd")
    ]
    return next((str(path.resolve()) for path in candidates if path.is_file()), None)


class ProcessOutput:
    """Drain a child's pipe without accumulating unlimited output in memory."""

    def __init__(self, pipe):
        self.pipe = pipe
        self.data = bytearray()
        self.truncated = False
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        with self.pipe:
            for chunk in iter(lambda: self.pipe.read(4096), b""):
                remaining = max(0, MAX_OUTPUT_CHARS - len(self.data))
                self.data.extend(chunk[:remaining])
                self.truncated |= len(chunk) > remaining

    def finish(self):
        self.thread.join(timeout=5)
        return bytes(self.data).decode("utf-8", errors="replace")


def stop_process_tree(process):
    """Terminate only the worker's owned process group (including solvers)."""
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                check=False,
            )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


class PythonTestRunner:
    def __init__(self, command: str | None, expected_version):
        self.command = command
        self.expected_version = list(expected_version)
        self._gate = threading.Lock()
        self._state_lock = threading.Lock()
        self._current = None

    def status(self):
        with self._state_lock:
            current = dict(self._current) if self._current else None
        if current:
            current["running_for_seconds"] = round(
                time.monotonic() - current.pop("started_at"), 3,
            )
        return {"available": self.command is not None, "command": self.command, "current_test": current}

    def run(self, code: str, document_path: str | None = None, timeout_seconds: int = 60):
        if not isinstance(code, str) or len(code) > MAX_CODE_CHARS:
            raise ValueError(f"code must be a string of at most {MAX_CODE_CHARS} characters")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be an integer between 1 and 3600")
        if self.command is None:
            return {"success": False, "code": "FREECADCMD_NOT_FOUND", "error": (
                "FreeCADCmd was not found beside this FreeCAD installation. Set "
                "FREECAD_MCP_FREECADCMD to its executable path before starting FreeCAD."
            )}
        if not self._gate.acquire(blocking=False):
            return {"success": False, "code": "TEST_WORKER_BUSY", "error": "Another test is still running"}
        test_id = uuid.uuid4().hex
        started = time.monotonic()
        with self._state_lock:
            self._current = {"test_id": test_id, "started_at": started}
        try:
            with tempfile.TemporaryDirectory(prefix="freecad_mcp_test_") as directory:
                response = self._run(Path(directory), code, document_path, timeout_seconds)
            # Return only after the temporary workspace has actually been removed.
            response.update(
                test_id=test_id, workspace_removed=True,
                total_duration_seconds=round(time.monotonic() - started, 3),
            )
            return response
        except Exception as exc:
            return {"success": False, "test_id": test_id, "error": {
                "type": type(exc).__name__, "message": str(exc),
            }}
        finally:
            with self._state_lock:
                self._current = None
            self._gate.release()

    def _run(self, directory, code, document_path, timeout):
        input_path = None
        if document_path is not None:
            source = Path(document_path)
            if not source.is_absolute() or not source.is_file() or source.suffix.lower() != ".fcstd":
                raise ValueError("document_path must be an absolute path to a saved .FCStd on the FreeCAD host")
            input_path = directory / "input.FCStd"
            shutil.copy2(source, input_path)
        request_path = directory / "request.json"
        result_path = directory / "result.json"
        request_path.write_text(json.dumps({
            "code": code, "document_path": str(input_path) if input_path else None,
            "expected_version": self.expected_version,
        }), encoding="utf-8")
        env = dict(os.environ)
        for name, subdirectory in {
            "FREECAD_USER_HOME": "profile", "FREECAD_USER_DATA": "data",
            "XDG_DATA_HOME": "data", "XDG_CONFIG_HOME": "config",
            "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp", "TEMP": "tmp", "TMP": "tmp",
        }.items():
            path = directory / subdirectory
            path.mkdir(exist_ok=True)
            env[name] = str(path)
        env["FREECAD_MCP_TEST_REQUEST"] = str(request_path)
        env["FREECAD_MCP_TEST_RESULT"] = str(result_path)
        worker = Path(__file__).with_name("python_test_worker.py")
        command = [
            self.command, "--user-cfg", str(directory / "user.cfg"),
            "--system-cfg", str(directory / "system.cfg"), str(worker),
        ]
        process = subprocess.Popen(
            command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
        )
        stdout, stderr = ProcessOutput(process.stdout), ProcessOutput(process.stderr)
        timed_out = False
        try:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            # Also remove descendants left behind after normal worker exit.
            stop_process_tree(process)
        logs = {
            "process_stdout": stdout.finish(), "process_stderr": stderr.finish(),
            "process_stdout_truncated": stdout.truncated,
            "process_stderr_truncated": stderr.truncated,
            "exit_code": process.returncode, "timed_out": timed_out,
        }
        if timed_out:
            return {**logs, "success": False, "code": "TEST_TIMEOUT", "error": (
                f"Disposable FreeCAD exceeded {timeout}s and was terminated. The live session was not used."
            )}
        if not result_path.is_file() or result_path.stat().st_size > 1_000_000:
            return {**logs, "success": False, "code": "TEST_WORKER_EXITED", "error": (
                "FreeCADCmd exited without a valid result; inspect process_stdout/process_stderr."
            )}
        response = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(response, dict):
            raise ValueError("Worker returned a non-object result")
        if process.returncode != 0:
            response.update(success=False, code="TEST_WORKER_EXITED", error="FreeCADCmd exited abnormally")
        return {**response, **logs}
