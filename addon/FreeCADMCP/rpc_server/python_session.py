"""Stateful Python cells, shared by the GUI bridge and disposable test worker.

Only the standard library is imported here. The caller supplies FreeCAD aliases
and, for the live session, serializes calls onto the GUI thread.
"""

import ast
import builtins
from collections import deque
import contextlib
import io
import json
import linecache
import math
import sys
import threading
import time
import traceback
import uuid


MAX_CODE_CHARS = 100_000
MAX_OUTPUT_CHARS = 64_000
MAX_RESULT_CHARS = 64_000
MAX_HISTORY = 20


class CapturedStream(io.StringIO):
    """Bound this cell's output and forward unrelated threads to the real stream."""

    def __init__(self, original, tee=False):
        super().__init__()
        self.original = original
        self.owner = threading.get_ident()
        self.truncated = False
        self.tee = tee

    def write(self, text):
        if threading.get_ident() != self.owner:
            return self.original.write(text)
        remaining = max(0, MAX_OUTPUT_CHARS - self.tell())
        super().write(text[:remaining])
        self.truncated |= len(text) > remaining
        if self.tee and remaining:
            self.original.write(text[:remaining])
            self.original.flush()
        return len(text)

    def flush(self):
        if threading.get_ident() != self.owner:
            self.original.flush()


def encode_result(value):
    """Return JSON data or an explicit representation; never expand CAD objects.

    Models can choose the exact properties they want in a final dictionary.
    Opaque objects (including shapes) remain useful through repr/dir/help.
    """
    budget = [MAX_RESULT_CHARS]
    seen = set()
    truncated = False

    def convert(item, depth=0):
        nonlocal truncated
        budget[0] -= 1
        if budget[0] <= 0 or depth >= 12:
            truncated = True
            return "<truncated>"
        if item is None or type(item) in (bool, int):
            return item
        if type(item) is float:
            return item if math.isfinite(item) else repr(item)
        if type(item) is str:
            length = max(0, budget[0])
            truncated |= len(item) > length
            budget[0] -= min(length, len(item))
            return item[:length]
        if id(item) in seen:
            return "<recursive reference>"
        if type(item) in (list, tuple, dict):
            seen.add(id(item))
            try:
                if type(item) is dict:
                    result = {}
                    for key, child in item.items():
                        if budget[0] <= 0 or len(result) >= 1000:
                            truncated = True
                            break
                        result[convert(str(key), depth + 1)] = convert(child, depth + 1)
                else:
                    result = []
                    for child in item:
                        if budget[0] <= 0 or len(result) >= 1000:
                            truncated = True
                            break
                        result.append(convert(child, depth + 1))
                return result
            finally:
                seen.remove(id(item))
        return {"type": type(item).__name__, "repr": convert(repr(item), depth + 1)}

    result = convert(value)
    # JSON escaping/key overhead can exceed the character budget above.
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(encoded) > MAX_RESULT_CHARS:
        return {"preview": encoded[:MAX_RESULT_CHARS]}, True
    return result, truncated


class PythonSession:
    def __init__(self, aliases, tee_output=False):
        self.session_id = uuid.uuid4().hex
        self.aliases = dict(aliases)
        self.namespace = {"__name__": "__main__", **aliases}
        self._lock = threading.Lock()
        self._current = None
        self._history = deque(maxlen=MAX_HISTORY)
        self.tee_output = tee_output

    def status(self):
        with self._lock:
            current = dict(self._current) if self._current else None
            if current:
                current["running_for_seconds"] = round(
                    time.monotonic() - current.pop("started_at"), 3
                )
            return {
                "session_id": self.session_id,
                "current_cell": current,
                "recent_cells": [
                    {key: value for key, value in cell.items() if key != "code"}
                    for cell in self._history
                ],
            }

    def run(self, code, cell_id=None):
        """Run one cell; the caller must serialize access to this session."""
        if not isinstance(code, str) or len(code) > MAX_CODE_CHARS:
            raise ValueError(f"code must be a string of at most {MAX_CODE_CHARS} characters")
        cell_id = cell_id or uuid.uuid4().hex
        filename = f"<freecad-mcp-{cell_id}>"
        started = time.monotonic()
        with self._lock:
            self._current = {"cell_id": cell_id, "started_at": started}
        # History is bounded so tracebacks retain source without leaking memory.
        linecache.cache[filename] = (len(code), None, code.splitlines(True), filename)
        self.namespace.update(self.aliases)
        self.namespace["__builtins__"] = dict(vars(builtins))
        self.namespace.pop("_result", None)
        stdout = CapturedStream(sys.stdout, self.tee_output)
        stderr = CapturedStream(sys.stderr, self.tee_output)
        response = {"session_id": self.session_id, "cell_id": cell_id}
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                tree = ast.parse(code, filename=filename)
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    expression = tree.body[-1]
                    tree.body[-1] = ast.copy_location(
                        ast.Assign(
                            targets=[ast.Name(id="_result", ctx=ast.Store())],
                            value=expression.value,
                        ), expression,
                    )
                    ast.fix_missing_locations(tree)
                exec(compile(tree, filename, "exec"), self.namespace)
                has_result = "_result" in self.namespace
                value = self.namespace.get("_result")
                result, truncated = encode_result(value)
                if has_result:
                    self.namespace["_"] = value
                response.update(
                    success=True, has_result=has_result, result=result,
                    result_type=type(value).__name__ if has_result else None,
                    result_truncated=truncated,
                )
        except BaseException as exc:
            # A submitted SystemExit/KeyboardInterrupt must not kill GUI dispatch.
            response.update(success=False, error={
                "type": type(exc).__name__,
                "message": str(exc)[:MAX_OUTPUT_CHARS],
                "traceback": traceback.format_exc()[-MAX_OUTPUT_CHARS:],
            })
        finally:
            response.update(
                stdout=stdout.getvalue(), stderr=stderr.getvalue(),
                stdout_truncated=stdout.truncated, stderr_truncated=stderr.truncated,
                duration_seconds=round(time.monotonic() - started, 3),
            )
            with self._lock:
                if len(self._history) == MAX_HISTORY:
                    oldest = self._history[0]["cell_id"]
                    linecache.cache.pop(f"<freecad-mcp-{oldest}>", None)
                self._history.append({
                    "cell_id": cell_id, "code": code,
                    "success": response.get("success", False),
                    "duration_seconds": response["duration_seconds"],
                })
                self._current = None
        return response
