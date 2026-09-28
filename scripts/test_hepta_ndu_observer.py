#!/usr/bin/env python3
"""Real UDS/peer-credential fixtures; not a live production monitoring claim."""
import copy
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import hepta_ndu_observer as observer


def payload(version):
    fields = observer.V1 if version == "metrics_v1" else observer.V2
    data = dict.fromkeys(fields, 0)
    data.update(type="ndu_control", result=version, journal_bytes=12, backup_age_seconds=None)
    if version == "metrics_v2":
        data.update(host_generation=7, storage_ready=True, filesystem_profile="linux-ext")
        data.update({key: list(range(size)) for key, size in observer.ARRAYS.items()})
    return data


def frame(version, request_id):
    return {"schema_version": 2, "request_id": request_id, "agent_id": "11111111-1111-4111-8111-111111111111",
            "spawn_generation": 7, "current_generation": 7, "payload": payload(version)}


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_rust_owned_wire_fixture_matches_the_observer(self):
        path = Path(__file__).resolve().parents[1] / "codex-rs/hepta-agent-protocol/tests/fixtures/ndu-observer-wire.json"
        fixture = json.loads(path.read_text())
        for request, response in zip(fixture["requests"], fixture["responses"]):
            version = request["method"]["request"]["operation"]
            decoded = observer.validate(json.dumps(response).encode() + b"\n", response["agent_id"], 7, request["request_id"], version)
            self.assertEqual(decoded, payload(version))

    def test_strict_typed_wire_identity_and_shapes(self):
        for version in ("metrics_v1", "metrics_v2"):
            good = frame(version, 1)
            self.assertEqual(observer.validate(json.dumps(good).encode() + b"\n", "11111111-1111-4111-8111-111111111111", 7, 1, version), good["payload"])
            distinct = copy.deepcopy(good); distinct["current_generation"] = 11
            self.assertEqual(observer.validate(json.dumps(distinct).encode() + b"\n", "11111111-1111-4111-8111-111111111111", 7, 1, version), good["payload"])
            for key, value in (("request_id", True), ("current_generation", 0), ("spawn_generation", 8), ("agent_id", "other"), ("schema_version", 1)):
                bad = copy.deepcopy(good); bad[key] = value
                with self.subTest(version=version, field=key), self.assertRaises(ValueError):
                    observer.validate(json.dumps(bad).encode() + b"\n", "11111111-1111-4111-8111-111111111111", 7, 1, version)
            for key in (observer.V1 if version == "metrics_v1" else observer.V2):
                bad = copy.deepcopy(good); del bad["payload"][key]
                with self.subTest(version=version, missing=key), self.assertRaises(ValueError):
                    observer.validate(json.dumps(bad).encode() + b"\n", "11111111-1111-4111-8111-111111111111", 7, 1, version)
            bad = copy.deepcopy(good); bad["payload"]["authorize"] = True
            with self.assertRaises(ValueError):
                observer.validate(json.dumps(bad).encode() + b"\n", "11111111-1111-4111-8111-111111111111", 7, 1, version)

    def test_boolean_unsigned_overflow_and_invalid_histograms_rejected(self):
        for key, value in (("evaluation_count", True), ("evaluation_count", -1), ("evaluation_count", 1 << 64), ("journal_bytes", False), ("storage_ready", 1), ("filesystem_profile", 'x"}\nbad 1'), ("host_generation", 8), ("evaluation_latency_buckets", [0] * 5), ("uncertainty_buckets", [False] * 6)):
            bad = frame("metrics_v2", 1); bad["payload"][key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                observer.validate(json.dumps(bad).encode() + b"\n", "11111111-1111-4111-8111-111111111111", 7, 1, "metrics_v2")
        text = json.dumps(frame("metrics_v2", 1))
        for bad in (text, text.replace('"request_id": 1', '"request_id": 1, "request_id": 1') + "\n", text + "\n{}\n", " " * observer.MAX_FRAME + text + "\n"):
            with self.assertRaises(ValueError):
                observer.validate(bad.encode(), "11111111-1111-4111-8111-111111111111", 7, 1, "metrics_v2")

    def test_renderer_converts_buckets_and_preserves_unknown(self):
        v1, v2 = payload("metrics_v1"), payload("metrics_v2")
        v2["storage_ready"] = None
        rendered = observer.render("11111111-1111-4111-8111-111111111111", 7, 123, (v1, v2, "instance"))
        self.assertIn('hepta_ndu_observer_up{agent="11111111-1111-4111-8111-111111111111",generation="7",owner_instance="instance"} 1', rendered)
        self.assertNotIn("hepta_ndu_storage_ready{", rendered)
        self.assertNotIn("hepta_ndu_backup_age_seconds{", rendered)
        self.assertIn('hepta_ndu_backup_age_seconds_known{agent="11111111-1111-4111-8111-111111111111",generation="7",owner_instance="instance"} 0', rendered)
        cumulative = 0
        for bound, count in zip(observer.LATENCY, range(6)):
            cumulative += count
            self.assertIn(f'le="{bound}",owner_instance="instance"}} {cumulative}\n', rendered)
        # A failed scrape contains no invented zero counters or stale readiness.
        failed = observer.render("11111111-1111-4111-8111-111111111111", 7, 124, None)
        self.assertEqual(len(failed.splitlines()), 2)
        self.assertIn("} 0\n", failed)
        self.assertNotIn("evaluation", failed)

    def serve(self, responses):
        endpoint = self.root / "control.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(endpoint)); os.chmod(endpoint, 0o600); listener.listen(2)
        listener.settimeout(2)
        observed, errors = [], []
        def run():
            try:
                for response in responses:
                    with listener.accept()[0] as stream:
                        stream.settimeout(2)
                        raw = bytearray()
                        while not raw.endswith(b"\n"):
                            raw.extend(stream.recv(4096))
                        observed.append(json.loads(raw))
                        stream.sendall(response)
            except Exception as error:
                errors.append(error)
            finally:
                listener.close()
        thread = threading.Thread(target=run, daemon=True); thread.start()
        self.addCleanup(thread.join, 3)
        return endpoint, thread, observed, errors

    def test_real_uds_uses_only_readonly_methods_and_peer_identity(self):
        responses = [json.dumps(frame(version, number)).encode() + b"\n" for version, number in (("metrics_v2", 1), ("metrics_v1", 2))]
        endpoint, thread, calls, errors = self.serve(responses)
        v1, v2, identity = observer.collect(endpoint, "11111111-1111-4111-8111-111111111111", 7, 2)
        thread.join(3)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
        self.assertEqual((v1, v2), (payload("metrics_v1"), payload("metrics_v2")))
        self.assertEqual(len(identity), 24)
        self.assertEqual([call["method"] for call in calls], [{"type": "ndu_control", "request": {"operation": v}} for v in ("metrics_v2", "metrics_v1")])

    def test_generation_switch_is_not_combined_into_one_sample(self):
        v1, v2 = payload("metrics_v1"), payload("metrics_v2")
        with patch.object(observer, "request", side_effect=[(v2, (1, 2, 3, 4, 11)), (v1, (5, 2, 3, 4, 11))]), self.assertRaises(ValueError):
            observer.collect(self.root / "control.sock", "11111111-1111-4111-8111-111111111111", 7, 1)
        with patch.object(observer, "request", side_effect=[(v2, (1, 2, 3, 4, 11)), (v1, (1, 2, 3, 4, 12))]), self.assertRaises(ValueError):
            observer.collect(self.root / "control.sock", "11111111-1111-4111-8111-111111111111", 7, 1)

    def test_deadline_and_unsafe_endpoint_fail_closed(self):
        path = self.root / "not-a-socket"; path.write_text("not a socket")
        with self.assertRaises(ValueError):
            observer.request(path, "11111111-1111-4111-8111-111111111111", 7, 1, "metrics_v2", time.monotonic() + 1)
        link = self.root / "alias"; link.symlink_to(path)
        with self.assertRaises(ValueError):
            observer.request(link, "11111111-1111-4111-8111-111111111111", 7, 1, "metrics_v2", time.monotonic() + 1)

    def test_atomic_publication_never_follows_links_or_retains_old_success(self):
        target = self.root / "ndu.prom"
        observer.publish(target, "healthy\n")
        observer.publish(target, observer.render("11111111-1111-4111-8111-111111111111", 7, 124, None))
        self.assertNotIn("healthy", target.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        self.assertEqual(list(self.root.glob("*.tmp")), [])
        other = self.root / "other"; other.write_text("not overwritten")
        target.unlink(); target.symlink_to(other)
        with self.assertRaises(ValueError): observer.publish(target, "unsafe\n")
        self.assertEqual(other.read_text(), "not overwritten")
        target.unlink(); os.link(other, target)
        with self.assertRaises(ValueError): observer.publish(target, "unsafe\n")
        self.assertEqual(other.read_text(), "not overwritten")

    def test_failed_cli_probe_publishes_failure_and_exits_nonzero(self):
        target = self.root / "ndu.prom"; target.write_text("old-success")
        with patch("sys.argv", ["observer", "--socket", str(self.root / "absent"), "--agent-id", "11111111-1111-4111-8111-111111111111", "--generation", "7", "--output", str(target)]):
            self.assertEqual(observer.main(), 1)
        self.assertNotIn("old-success", target.read_text())


if __name__ == "__main__":
    unittest.main()
