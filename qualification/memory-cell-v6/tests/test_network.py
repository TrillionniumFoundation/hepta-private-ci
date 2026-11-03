"""Actual independent disk/process reads, bounded transport and failure checks."""

from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from v6.artifacts import ArtifactOwner
from v6.contracts import MAX_WIRE_BYTES, MemoryReadout, MemoryRequest, canonical
from v6.network import MetaNetwork, NodeClient, NodeProcess
from v6.runtime import train_snapshot
from v6.store import EventStore, StaleSource


@contextmanager
def response_server(callback):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            status, headers, body = callback(payload)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class NetworkTests(unittest.TestCase):
    def test_noncanonical_hosts_redirects_and_response_substitution_are_rejected(self):
        snapshot = "b" * 64
        urls = (
            "http://127.0.0.1:80@example.invalid",
            "http://localhost:80",
            "https://127.0.0.1:80",
            "http://127.0.0.1:80/",
            "http://127.0.0.1:80?",
            "http://127.0.0.1:80#",
            "http://127.0.0.1:0",
            "http://127.0.0.1:65536",
            "http://127.0.0.1:080",
            "http://127.0.0.1:80\n",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                NodeClient(url, snapshot)
        request = MemoryRequest("q", "scope", "entity", "text", 20, 10)
        target_calls = []
        with response_server(
            lambda payload: (target_calls.append(payload) or 200, {}, b"{}")
        ) as target:
            with response_server(
                lambda _payload: (302, {"Location": target + "/read"}, b"redirect")
            ) as url:
                client = NodeClient(url, snapshot)
                with self.assertRaises(StaleSource):
                    client.read(request, "current")
                self.assertEqual(
                    (client.calls, client.received_bytes, len(target_calls)), (1, 8, 0)
                )
        base = MemoryReadout(
            "q",
            "current",
            "ok",
            7,
            ("a" * 64,),
            1,
            snapshot,
            "source_evidence",
            (),
            1,
            0.01,
        ).as_dict()
        reply = {}
        with response_server(lambda _payload: (200, {}, canonical(reply))) as url:
            client = NodeClient(url, snapshot)
            for change in (
                {"query_id": "other"},
                {"operation": "history"},
                {"snapshot_digest": "c" * 64},
                {"source_ids": ["wrong"]},
                {"unexpected": True},
                {"value": None},
            ):
                reply.clear()
                reply.update({**base, **change})
                with self.subTest(change=change), self.assertRaises(StaleSource):
                    client.read(request, "current")
            self.assertEqual(client.calls, 6)
            self.assertGreater(client.received_bytes, 0)
        with response_server(
            lambda _payload: (200, {}, b" " * (MAX_WIRE_BYTES + 100))
        ) as url:
            client = NodeClient(url, snapshot)
            with self.assertRaises(StaleSource):
                client.read(request, "current")
            self.assertEqual(client.received_bytes, MAX_WIRE_BYTES + 1)

    def test_readiness_timeout_and_malformed_contract_cleanup_children(self):
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as directory:
            for code, expected in (
                ("import time; time.sleep(30)", TimeoutError),
                ("import time; print('{}', flush=True); time.sleep(30)", ValueError),
            ):
                children = []

                def launch(_command, **kwargs):
                    child = real_popen([sys.executable, "-c", code], **kwargs)
                    children.append(child)
                    return child

                started = time.perf_counter()
                with (
                    patch("v6.network.subprocess.Popen", side_effect=launch),
                    self.assertRaises(expected),
                ):
                    NodeProcess(
                        "unused",
                        "unused",
                        "exact",
                        log_path=Path(directory) / "startup.log",
                        startup_timeout=0.3,
                    )
                self.assertLess(time.perf_counter() - started, 3)
                self.assertIsNotNone(children[0].poll())
                self.assertTrue(children[0].stdout.closed)

    def test_independent_replicas_restart_versions_and_final_revocation_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base"
            base.mkdir()
            source = EventStore(base / "source.sqlite")
            latest = {}
            for entity in ("a", "b"):
                for at, value in ((10, 4), (20, 7)):
                    latest[entity] = source.append(
                        scope="scope",
                        entity=entity,
                        kind="event",
                        effective_at=at,
                        value=value,
                        origin_id=f"event-{entity}-{at}",
                    )
                source.append(
                    scope="scope",
                    entity=entity,
                    kind="semantic",
                    effective_at=1,
                    value={"factor": 3, "label": "group"},
                    origin_id="semantic-" + entity,
                )
                source.append(
                    scope="scope",
                    entity=entity,
                    kind="procedure",
                    effective_at=1,
                    value={"opcode": "affine", "bias": 2, "limit": 50},
                    origin_id="procedure-" + entity,
                )
            source.close()
            train_snapshot(
                base / "source.sqlite",
                base / "artifacts",
                scope="scope",
                seed=929,
                steps=20,
                hidden=8,
            )
            paths, nodes = [], []
            try:
                for index in range(3):
                    path = root / f"replica-{index}"
                    shutil.copytree(base, path)
                    paths.append(path)
                    nodes.append(
                        NodeProcess(
                            path / "source.sqlite",
                            path / "artifacts",
                            "parameter",
                            log_path=root / f"node-{index}.log",
                        )
                    )
                self.assertEqual(
                    len({(path / "source.sqlite").stat().st_ino for path in paths}), 3
                )
                self.assertEqual(len({node.process.pid for node in nodes}), 3)
                network = MetaNetwork(*(node.client for node in nodes))
                request = MemoryRequest("first", "scope", "a", "apply", 15, 10)
                result = network.read(request, "apply")
                self.assertEqual(
                    (
                        result["status"],
                        result["value"],
                        result["prediction_kind"],
                        result["hops"],
                    ),
                    ("ok", 23, "mixed", 3),
                )
                self.assertEqual(
                    (
                        result["transport"]["rpc_attempts"],
                        result["transport"]["validation_attempts"],
                        result["transport"]["node_count"],
                    ),
                    (6, 3, 3),
                )
                self.assertGreater(result["transport"]["rpc_bytes"], 0)
                boundary = network.read(replace(request, query_id="q" * 256), "apply")
                self.assertEqual((boundary["status"], boundary["value"]), ("ok", 23))
                limited = network.read(
                    replace(request, query_id="limited", max_cells=1), "apply"
                )
                self.assertEqual(
                    (
                        limited["status"],
                        limited["hops"],
                        limited["transport"]["rpc_attempts"],
                    ),
                    ("budget_exceeded", 1, 1),
                )
                self.assertEqual(
                    (limited["value"], limited["source_ids"], limited["cell_digests"]),
                    (None, (), ()),
                )
                nodes[1].stop(crash=True)
                failed = network.read(
                    replace(request, query_id="during-crash"), "apply"
                )
                self.assertEqual(
                    (
                        failed["status"],
                        failed["hops"],
                        failed["transport"]["rpc_attempts"],
                    ),
                    ("unavailable", 2, 2),
                )
                self.assertGreater(failed["transport"]["attempted_request_bytes"], 0)
                self.assertEqual(
                    (failed["value"], failed["source_ids"], failed["cell_digests"]),
                    (None, (), ()),
                )
                nodes[1] = NodeProcess(
                    paths[1] / "source.sqlite",
                    paths[1] / "artifacts",
                    "parameter",
                    log_path=root / "node-restart.log",
                )
                network = MetaNetwork(*(node.client for node in nodes))
                restarted = network.read(replace(request, query_id="restart"), "apply")
                self.assertEqual(
                    (
                        restarted["status"],
                        restarted["value"],
                        restarted["snapshot_digest"],
                    ),
                    ("ok", 23, result["snapshot_digest"]),
                )
                owner = ArtifactOwner(paths[1] / "artifacts")
                manifest, _ = owner.manifest()
                next_digest = owner.publish(manifest, expected_generation=1)
                owner.close()
                stale = network.read(
                    replace(request, query_id="mixed-version"), "apply"
                )
                self.assertEqual(
                    (stale["status"], stale["value"], stale["source_ids"]),
                    ("stale", None, ()),
                )
                with self.assertRaises(StaleSource):
                    MetaNetwork(
                        nodes[0].client,
                        NodeClient(nodes[1].client.url, next_digest, generation=2),
                        nodes[2].client,
                    )
                for node in nodes:
                    node.stop()
                nodes = []
                migrated = []
                for index in range(3):
                    path = root / f"migrated-{index}"
                    shutil.copytree(paths[1], path)
                    migrated.append(path)
                    nodes.append(
                        NodeProcess(
                            path / "source.sqlite",
                            path / "artifacts",
                            "parameter",
                            log_path=root / f"migrated-{index}.log",
                        )
                    )
                network = MetaNetwork(*(node.client for node in nodes))
                coherent = network.read(
                    replace(request, query_id="coherent-release"), "apply"
                )
                self.assertEqual(
                    (
                        coherent["status"],
                        coherent["generation"],
                        coherent["snapshot_digest"],
                        coherent["value"],
                    ),
                    ("ok", 2, next_digest, 23),
                )
                rejected = network.read(
                    replace(request, query_id="rejected-after-release"), None
                )
                self.assertEqual(
                    (
                        rejected["status"],
                        rejected["generation"],
                        rejected["transport"]["rpc_attempts"],
                    ),
                    ("abstain", 2, 0),
                )
                original_read = nodes[2].client.read

                def read_then_revoke(*args, **kwargs):
                    value = original_read(*args, **kwargs)
                    changed = EventStore(migrated[0] / "source.sqlite")
                    changed.revoke(latest["a"], "revoked between read and validation")
                    changed.close()
                    return value

                with patch.object(
                    nodes[2].client, "read", side_effect=read_then_revoke
                ):
                    revoked = network.read(
                        replace(request, query_id="late-revocation"), "apply"
                    )
                self.assertEqual(
                    (
                        revoked["status"],
                        revoked["value"],
                        revoked["source_ids"],
                        revoked["cell_digests"],
                    ),
                    ("stale", None, (), ()),
                )
                self.assertEqual(
                    (
                        revoked["hops"],
                        revoked["transport"]["rpc_attempts"],
                        revoked["transport"]["validation_attempts"],
                    ),
                    (3, 4, 1),
                )
            finally:
                for node in nodes:
                    node.stop(crash=True)


if __name__ == "__main__":
    unittest.main()
