"""Thread-safe bridge client: every request owns its XML-RPC connection."""

import json
import xmlrpc.client


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class FreeCADConnection:
    def __init__(self, host: str = "localhost", port: int = 9875):
        # XML-RPC URLs need brackets around IPv6 literals.
        host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        self.uri = f"http://{host}:{port}"

    def _call(self, method: str, *args, timeout: float = 10):
        with xmlrpc.client.ServerProxy(
            self.uri, allow_none=True, transport=_TimeoutTransport(timeout),
        ) as proxy:
            return getattr(proxy, method)(*args)

    def ping(self) -> bool:
        return self._call("ping")

    def get_runtime_status(self) -> dict:
        return self._call("get_runtime_status")

    def execute_python(self, code: str, timeout_seconds: int = 90) -> dict:
        return json.loads(self._call(
            "execute_python", code, timeout_seconds, timeout=timeout_seconds + 30,
        ))

    def document_operations(
        self, action: str, document: str | None = None, path: str | None = None,
        discard_changes: bool = False, overwrite: bool = False,
    ) -> dict:
        return json.loads(self._call(
            "document_operations", action, document, path,
            discard_changes, overwrite, timeout=90,
        ))

    def inspect_document(
        self, document: str | None = None, object_name: str | None = None,
        properties: list[str] | None = None, max_depth: int = 6,
    ) -> dict:
        return json.loads(self._call(
            "inspect_document", document, object_name, properties, max_depth,
            timeout=90,
        ))

    def resource_operations(
        self, action: str, query: str | None = None, provider: str | None = None,
        resource_id: str | None = None, document: str | None = None,
        properties: dict | None = None, attach_to: str | None = None,
        limit: int = 10,
    ) -> dict:
        return json.loads(self._call(
            "resource_operations", action, query, provider, resource_id,
            document, properties, attach_to, limit, timeout=120,
        ))

    def get_view(self, width: int = 1024, height: int = 768) -> str:
        return self._call("get_view", width, height, timeout=90)

    def test_python(self, code: str, document_path: str | None = None, timeout_seconds: int = 60) -> dict:
        return json.loads(self._call(
            "test_python", code, document_path, timeout_seconds, timeout=timeout_seconds + 30,
        ))
