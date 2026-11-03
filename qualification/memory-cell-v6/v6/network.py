"""Bounded local HTTP nodes with pinned generations and final freshness checks.

Each node may own an independent disk copy. Final validation is fail-closed for
observed revocations/version changes; this is not multiwriter linearizability.
Counters charge attempted JSON request bodies and received response bodies,
including failures, rather than claiming packet-level network measurement.
"""

import argparse
from collections import OrderedDict
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .contracts import (
    MAX_WIRE_BYTES,
    MemoryReadout,
    MemoryRequest,
    bounded_text,
    canonical,
    digest,
    integer,
    valid_digest,
)
from .runtime import MemoryRuntime, execute_program
from .store import StaleSource


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class NodeClient:
    def __init__(self, url, snapshot_digest, *, timeout=3, generation=None):
        if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError("qualification client requires a canonical loopback URL")
        parsed = urllib.parse.urlsplit(url)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("invalid loopback port") from error
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not integer(port, 1, 65535)
            or url != f"http://127.0.0.1:{port}"
        ):
            raise ValueError("qualification client is loopback-only")
        if not valid_digest(snapshot_digest) or (
            generation is not None and not integer(generation, 1, 2**53 - 1)
        ):
            raise ValueError("invalid pinned generation")
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 60
        ):
            raise ValueError("invalid RPC deadline")
        self.url, self.snapshot_digest, self.timeout, self.generation = (
            url,
            snapshot_digest,
            timeout,
            generation,
        )
        self.sent_bytes = self.received_bytes = self.calls = 0
        self.read_attempts = self.validation_attempts = 0
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def counters(self):
        return {
            name: getattr(self, name)
            for name in (
                "sent_bytes",
                "received_bytes",
                "calls",
                "read_attempts",
                "validation_attempts",
            )
        }

    def _body(self, response):
        body = bytearray()
        reader = getattr(response, "read1", response.read)
        try:
            while len(body) <= MAX_WIRE_BYTES:
                block = reader(min(16384, MAX_WIRE_BYTES + 1 - len(body)))
                self.received_bytes += len(block)
                body.extend(block)
                if not block or len(body) > MAX_WIRE_BYTES:
                    break
        except http.client.IncompleteRead as error:
            self.received_bytes += len(error.partial)
            raise StaleSource("truncated node response") from error
        if (
            getattr(response, "length", 0) not in (0, None)
            and len(body) <= MAX_WIRE_BYTES
        ):
            raise StaleSource("truncated node response")
        return bytes(body)

    def _post(self, endpoint, payload):
        raw = canonical(payload)
        if len(raw) > MAX_WIRE_BYTES:
            raise ValueError("request exceeds transport limit")
        self.sent_bytes += len(raw)
        self.calls += 1
        started = time.perf_counter()
        wire = urllib.request.Request(
            self.url + endpoint, data=raw, headers={"Content-Type": "application/json"}
        )
        try:
            with self.opener.open(wire, timeout=self.timeout) as response:
                reply = self._body(response)
                if response.status != 200:
                    raise StaleSource("unexpected node HTTP disposition")
        except urllib.error.HTTPError as error:
            try:
                reply = self._body(error)
            finally:
                error.close()
            raise StaleSource("node rejected request: " + str(error.code)) from error
        except http.client.HTTPException as error:
            raise StaleSource("invalid node HTTP response") from error
        if len(reply) > MAX_WIRE_BYTES:
            raise StaleSource("oversized node response")
        try:
            result = json.loads(reply)
        except (ValueError, UnicodeError) as error:
            raise StaleSource("node response is not valid JSON") from error
        if not isinstance(result, dict):
            raise StaleSource("node response is not an object")
        return result, dict(
            sent_bytes=len(raw),
            received_bytes=len(reply),
            elapsed_seconds=time.perf_counter() - started,
        )

    def read(self, request, operation, *, disabled=(), permute=False):
        if not isinstance(request, MemoryRequest):
            request = MemoryRequest.from_dict(request)
        self.read_attempts += 1
        result, transport = self._post(
            "/read",
            dict(
                request=request.as_dict(),
                operation=operation,
                snapshot_digest=self.snapshot_digest,
                disabled=list(disabled),
                permute=permute,
            ),
        )
        try:
            readout = MemoryReadout.from_dict(result)
        except (TypeError, ValueError) as error:
            raise StaleSource("node readout violates its typed contract") from error
        if (
            readout.query_id != request.query_id
            or readout.operation != operation
            or readout.snapshot_digest != self.snapshot_digest
            or readout.hops > request.max_hops
            or (self.generation is not None and readout.generation != self.generation)
        ):
            raise StaleSource("node response is not bound to this request/generation")
        return {**readout.as_dict(), "transport": transport}

    def validate(self, *, query_id, scope, generation, source_ids):
        payload = dict(
            query_id=query_id,
            scope=scope,
            generation=generation,
            source_ids=list(source_ids),
            snapshot_digest=self.snapshot_digest,
        )
        self.validation_attempts += 1
        result, transport = self._post("/validate", payload)
        expected = {
            **payload,
            "schema": "hepta.memory.validation.v1",
            "status": "valid",
        }
        if (
            set(result) != set(expected) | {"source_cut"}
            or any(result.get(key) != value for key, value in expected.items())
            or not integer(result["source_cut"], 0, 2**53 - 1)
        ):
            raise StaleSource("node freshness response is not bound to this read")
        return {**result, "transport": transport}


class NodeProcess:
    def __init__(self, source, artifacts, reader_kind, *, log_path, startup_timeout=10):
        if (
            reader_kind not in ("parameter", "exact")
            or type(startup_timeout) not in (int, float)
            or not math.isfinite(startup_timeout)
            or not 0 < startup_timeout <= 60
        ):
            raise ValueError("invalid node startup configuration")
        self.process = None
        self.log = open(log_path, "w")
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "v6.network",
                    "--source",
                    str(Path(source).resolve()),
                    "--artifacts",
                    str(Path(artifacts).resolve()),
                    "--reader-kind",
                    reader_kind,
                ],
                stdout=subprocess.PIPE,
                stderr=self.log,
                cwd=Path(__file__).resolve().parent.parent,
            )
            deadline, line = time.monotonic() + startup_timeout, bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                while b"\n" not in line:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("node readiness deadline exceeded")
                    block = os.read(self.process.stdout.fileno(), 4097 - len(line))
                    if not block:
                        raise RuntimeError("node exited before readiness")
                    line.extend(block)
                    if len(line) > 4096:
                        raise ValueError("node readiness exceeds bound")
            self.ready = json.loads(line)
            fields = {"url", "snapshot_digest", "generation", "reader_kind", "pid"}
            if (
                not isinstance(self.ready, dict)
                or set(self.ready) != fields
                or self.ready["reader_kind"] != reader_kind
                or self.ready["pid"] != self.process.pid
            ):
                raise ValueError("invalid node readiness contract")
            self.client = NodeClient(
                self.ready["url"],
                self.ready["snapshot_digest"],
                generation=self.ready["generation"],
            )
        except BaseException:
            self.stop(crash=True)
            raise

    def stop(self, *, crash=False):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill() if crash else self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            if self.process.stdout:
                self.process.stdout.close()
        self.log.close()


class MetaNetwork:
    """Typed composition with pre-dispatch read budgets and final node checks."""

    def __init__(self, event_client, semantic_client, procedure_client):
        self.clients = {
            "event": event_client,
            "semantic": semantic_client,
            "procedure": procedure_client,
        }
        if len({client.snapshot_digest for client in self.clients.values()}) != 1:
            raise StaleSource("nodes disagree on the admitted bundle")
        generations = {
            client.generation
            for client in self.clients.values()
            if client.generation is not None
        }
        if len(generations) > 1:
            raise StaleSource("nodes disagree on the admitted generation")
        self.generation = next(iter(generations), 1)

    def read(self, request, operation, *, disabled=(), permute=False):
        if not isinstance(request, MemoryRequest):
            request = MemoryRequest.from_dict(request)
        started, results, attempted_kinds = time.perf_counter(), [], []
        clients = {id(client): client for client in self.clients.values()}
        before = {key: client.counters() for key, client in clients.items()}
        snapshot = next(iter(self.clients.values())).snapshot_digest
        generation = self.generation

        def hop(kind, op, *, at=None):
            nonlocal generation
            if kind in disabled:
                raise StaleSource("required cross-node edge removed")
            if (
                len(attempted_kinds) >= request.max_hops
                or len(set(attempted_kinds) | {kind}) > request.max_cells
            ):
                raise OverflowError("network read budget exceeded")
            fields = request.as_dict()
            fields["query_id"] = digest(
                dict(
                    parent=request.query_id,
                    snapshot=snapshot,
                    index=len(attempted_kinds),
                    kind=kind,
                    operation=op,
                )
            )
            if at is not None:
                fields["at"], fields["since"] = at, min(fields["since"], at)
            attempted_kinds.append(kind)
            value = self.clients[kind].read(
                MemoryRequest.from_dict(fields), op, permute=permute
            )
            if value["snapshot_digest"] != snapshot or value["status"] != "ok":
                raise StaleSource("node did not produce the pinned typed value")
            if results and value["generation"] != generation:
                raise StaleSource("mixed generations across nodes")
            generation = value["generation"]
            results.append((kind, value))
            return value["value"]

        status, reason, value = "ok", None, None
        try:
            match operation:
                case "current" | "history":
                    value = hop("event", operation)
                case "semantic" | "procedure":
                    value = hop(operation, operation)
                case "change":
                    value = hop("event", "current") - hop(
                        "event", "history", at=request.since
                    )
                case "apply":
                    event = hop("event", "current")
                    semantic = hop("semantic", "semantic")
                    procedure = hop("procedure", "procedure")
                    value = execute_program(procedure, event, semantic)
                case None:
                    status, reason = "abstain", "semantic router rejected"
                case _:
                    raise ValueError("unsupported network operation")
            # Validation is never served from the read cache. At most one extra
            # RPC per participating node, separately charged from read hops.
            supports = {}
            for kind, result in results:
                key = id(self.clients[kind])
                supports.setdefault(key, []).extend(result["source_ids"])
            for index, (key, sources) in enumerate(supports.items()):
                clients[key].validate(
                    query_id=digest(
                        dict(
                            parent=request.query_id, snapshot=snapshot, validation=index
                        )
                    ),
                    scope=request.scope,
                    generation=generation,
                    source_ids=list(dict.fromkeys(sources)),
                )
        except StaleSource as error:
            status, reason, value = "stale", str(error), None
        except OverflowError as error:
            status, reason, value = "budget_exceeded", str(error), None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            status, reason, value = "unavailable", type(error).__name__, None
        except (ValueError, TypeError, KeyError):
            status, reason, value = (
                "unavailable",
                "invalid node contract or stored program",
                None,
            )
        source_ids, models = [], []
        if status == "ok":
            for _, part in results:
                source_ids.extend(part["source_ids"])
                models.extend(part["cell_digests"])
        kinds = {part["prediction_kind"] for _, part in results}
        prediction_kind = (
            "none"
            if status != "ok"
            else "mixed"
            if len(kinds) > 1
            else next(iter(kinds))
        )
        result = MemoryReadout(
            request.query_id,
            operation,
            status,
            value,
            tuple(dict.fromkeys(source_ids)),
            generation,
            snapshot,
            prediction_kind,
            tuple(dict.fromkeys(models)),
            len(attempted_kinds),
            time.perf_counter() - started,
            reason,
        ).as_dict()
        measured = {
            name: sum(
                client.counters()[name] - before[key][name]
                for key, client in clients.items()
            )
            for name in next(iter(before.values()))
        }
        result["transport"] = {
            "rpc_bytes": measured["sent_bytes"] + measured["received_bytes"],
            "rpc_attempts": measured["calls"],
            "read_attempts": measured["read_attempts"],
            "validation_attempts": measured["validation_attempts"],
            "attempted_request_bytes": measured["sent_bytes"],
            "received_response_bytes": measured["received_bytes"],
            "node_count": len({self.clients[k].url for k in attempted_kinds}),
            "byte_accounting": "attempted JSON request bodies plus received response bodies; excludes HTTP/TCP overhead",
        }
        return result


def serve(source, artifacts, reader_kind):
    runtime = MemoryRuntime(source, artifacts, reader_kind=reader_kind)
    manifest, identity = runtime.load()
    cache = OrderedDict()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            try:
                self.connection.settimeout(5)
                lengths = self.headers.get_all("Content-Length", [])
                if (
                    len(lengths) != 1
                    or not lengths[0].isdigit()
                    or self.headers.get("Transfer-Encoding") is not None
                ):
                    raise ValueError("invalid request framing")
                length = int(lengths[0])
                if (
                    self.path not in ("/read", "/validate")
                    or not 0 < length <= MAX_WIRE_BYTES
                ):
                    raise ValueError("invalid endpoint or request size")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("truncated request")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("request body must be an object")
                if self.path == "/read":
                    if set(payload) != {
                        "request",
                        "operation",
                        "snapshot_digest",
                        "disabled",
                        "permute",
                    }:
                        raise ValueError("unexpected transport fields")
                    if (
                        payload["disabled"] not in ([], ["semantic"], ["procedure"])
                        or type(payload["permute"]) is not bool
                        or not valid_digest(payload["snapshot_digest"])
                    ):
                        raise ValueError("unknown diagnostic intervention")
                    request = MemoryRequest.from_dict(payload["request"])
                    runtime.load(payload["snapshot_digest"])
                    key, request_digest = request.query_id, digest(payload)
                    if key in cache:
                        prior_digest, result = cache[key]
                        if prior_digest != request_digest:
                            raise ValueError(
                                "query identity reused with different request"
                            )
                    else:
                        result = runtime.read(
                            request,
                            payload["operation"],
                            expected_digest=payload["snapshot_digest"],
                            disabled=payload["disabled"],
                            permute=payload["permute"],
                        )
                        MemoryReadout.from_dict(result)
                        cache[key] = request_digest, result
                        if len(cache) > 256:
                            cache.popitem(last=False)
                else:
                    expected = {
                        "query_id",
                        "scope",
                        "generation",
                        "source_ids",
                        "snapshot_digest",
                    }
                    if (
                        set(payload) != expected
                        or not bounded_text(payload["query_id"])
                        or not bounded_text(payload["scope"])
                        or not valid_digest(payload["snapshot_digest"])
                        or not integer(payload["generation"], 1, 2**53 - 1)
                        or not isinstance(payload["source_ids"], list)
                        or not 1 <= len(payload["source_ids"]) <= 64
                        or any(not valid_digest(item) for item in payload["source_ids"])
                        or len(set(payload["source_ids"])) != len(payload["source_ids"])
                    ):
                        raise ValueError("invalid freshness request")
                    current, pinned = runtime.load(payload["snapshot_digest"])
                    if (
                        payload["scope"] != current["scope"]
                        or payload["generation"] != current["generation"]
                    ):
                        raise StaleSource(
                            "freshness request differs from admitted generation"
                        )
                    runtime.source.validate_support(
                        payload["source_ids"],
                        scope=payload["scope"],
                        cut=current["source_cut"],
                    )
                    if (
                        runtime.artifacts.active() != (current["generation"], pinned)
                        or runtime.source.cut != current["source_cut"]
                    ):
                        raise StaleSource(
                            "source or generation changed during freshness check"
                        )
                    result = {
                        **payload,
                        "schema": "hepta.memory.validation.v1",
                        "status": "valid",
                        "source_cut": current["source_cut"],
                    }
                raw = canonical(result)
                self.send_response(200)
            except (ValueError, TypeError, KeyError, TimeoutError) as error:
                raw = canonical({"error": str(error)[:512]})
                self.send_response(409 if isinstance(error, StaleSource) else 400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    print(
        json.dumps(
            dict(
                url=f"http://127.0.0.1:{server.server_port}",
                snapshot_digest=identity,
                generation=manifest["generation"],
                reader_kind=reader_kind,
                pid=os.getpid(),
            )
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--reader-kind", choices=("parameter", "exact"), required=True)
    arguments = parser.parse_args()
    serve(arguments.source, arguments.artifacts, arguments.reader_kind)
