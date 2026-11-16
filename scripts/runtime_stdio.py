"""Bounded MCP stdio transport for an explicitly pinned Unix runtime process.

The controller uses Unix file descriptors and is scoped to Linux/macOS. The
remote worker candidate declares its own separately frozen platform identity.
"""

import contextlib
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON member")
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )


def file_digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def unwrap(result):
    require(isinstance(result, dict), "MCP result is not an object")
    require(result.get("isError") is not True, "runtime tool returned an error")
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    values = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                parsed = strict_json(item["text"])
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                values.append(parsed)
    require(len(values) == 1, "runtime did not return exactly one JSON observation")
    return values[0]


class StdioRuntime:
    """Bounded JSON-RPC client launching one explicitly pinned runtime binary."""

    def __init__(self, runtime, *, timeout_seconds=45, environment=None):
        self.timeout_seconds = timeout_seconds
        self.pending = b""
        self.sequence = 0
        self.records = []
        self.identity = {
            "transport": "actual_mcp_stdio",
            "runtime_binary_sha256": file_digest(runtime["binary"]),
            "runtime_config_sha256": file_digest(runtime["config"]),
            "runtime_source_commit": runtime["source_commit"],
            "runtime_binary_build_provenance_verified": False,
        }
        require(
            self.identity["runtime_binary_sha256"] == runtime["binary_sha256"],
            "runtime binary does not match its frozen digest",
        )
        require(
            self.identity["runtime_config_sha256"] == runtime["config_sha256"],
            "runtime configuration does not match its frozen digest",
        )
        root = Path(runtime["source_root"]).resolve(strict=True)
        actual = (
            subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], timeout=10
            )
            .decode()
            .strip()
        )
        require(
            actual == runtime["source_commit"],
            "runtime checkout is not the frozen source",
        )
        changed = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            timeout=10,
        )
        require(not changed, "runtime checkout has tracked changes")
        self.identity["runtime_source_checkout_verified"] = True
        self.stderr_file = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [
                str(Path(runtime["binary"]).resolve(strict=True)),
                "mcp",
                "--runtime-config",
                str(Path(runtime["config"]).resolve(strict=True)),
                "--path",
                str(root),
            ],
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_file,
            bufsize=0,
            start_new_session=True,
        )
        try:
            self.initialized = self.rpc(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "hepta-cell-joint-runtime", "version": "1"},
                },
            )
            self._write(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                time.monotonic() + self.timeout_seconds,
            )
            catalog, cursor = [], None
            for _ in range(16):
                response = self.rpc(
                    "tools/list", {} if cursor is None else {"cursor": cursor}
                )
                catalog.extend(response.get("tools", []))
                cursor = response.get("nextCursor")
                if not cursor:
                    break
            require(not cursor, "runtime tool catalog exceeds the bounded page count")
            require(
                {"process_start", "process_status", "process_read", "process_cancel"}
                <= {tool.get("name") for tool in catalog},
                "runtime process owner is unavailable",
            )
            self.identity["runtime_tools_sha256"] = digest(canonical(catalog))
            if "tools_sha256" in runtime:
                require(
                    self.identity["runtime_tools_sha256"] == runtime["tools_sha256"],
                    "runtime catalog does not match its frozen digest",
                )
        except BaseException:
            self.close()
            raise

    def _write(self, message, deadline):
        raw = canonical(message) + b"\n"
        require(len(raw) <= 4 * 1024 * 1024, "MCP request exceeds transport bound")
        at = 0
        fd = self.process.stdin.fileno()
        os.set_blocking(fd, False)
        while at < len(raw):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MCP write deadline; submission may be unknown")
            _, ready, _ = select.select([], [fd], [], remaining)
            if ready:
                try:
                    at += os.write(fd, raw[at:])
                except BlockingIOError:
                    pass

    def rpc(self, method, params):
        self.sequence += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.sequence,
            "method": method,
            "params": params,
        }
        deadline = time.monotonic() + self.timeout_seconds
        self._write(request, deadline)
        while True:
            if b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                if not line.strip():
                    continue
                response = strict_json(line)
                self.records.append({"request": request, "response": response})
                if response.get("id") != self.sequence:
                    continue
                require("error" not in response, "MCP returned an RPC error")
                return response["result"]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "MCP response deadline; observe original operation only"
                )
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if ready:
                chunk = os.read(self.process.stdout.fileno(), 65536)
                require(bool(chunk), "runtime MCP stream closed")
                self.pending += chunk
                require(
                    len(self.pending) <= 4 * 1024 * 1024,
                    "MCP response exceeds transport bound",
                )

    def call(self, tool, arguments):
        return unwrap(self.rpc("tools/call", {"name": tool, "arguments": arguments}))

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            with contextlib.suppress(OSError):
                self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.stderr_file.close()
