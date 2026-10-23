#!/usr/bin/env python3
"""Synthetic receipt and loopback tests. No real host claim."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bakeoff import EvidenceError
from lifecycle import STAGES, canonical, verify_lifecycle
from scale import percentile, probe


class LifecycleTests(unittest.TestCase):
    def signed_events(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private = {role: Ed25519PrivateKey.generate() for _, role in STAGES}
        keys = {
            role: key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ).hex()
            for role, key in private.items()
        }
        baseline, candidate, gen = "1" * 64, "2" * 64, 6
        previous = "0" * 64
        events = []
        for i, (name, role) in enumerate(STAGES):
            generation = gen - 1 if name == "old_generation_rejected" else gen + 1 if i >= 6 else gen
            model = baseline if i >= 6 or name == "old_generation_rejected" else candidate
            if name == "stale_candidate_rejected":
                generation, model = gen, candidate
            payload = {
                "stage": name, "issuer_role": role, "sequence": i + 1,
                "previous_receipt_sha256": previous, "observed": True,
                "operation_id": f"op-{i}", "evidence_digest": "3" * 64,
                "source_commit": "a" * 40, "generation": generation,
                "model_digest": model,
            }
            if i == 0:
                payload["baseline_digest"] = baseline
            entry = {
                "payload": payload,
                "signature": private[role].sign(canonical(payload)).hex(),
            }
            previous = hashlib.sha256(canonical(entry)).hexdigest()
            events.append(entry)
        return events, keys

    def test_valid_chain_is_still_not_authority(self):
        events, keys = self.signed_events()
        result = verify_lifecycle(events, keys)
        self.assertTrue(result["signed_sequence_valid"])
        self.assertFalse(result["promotion_authorized"])
        self.assertFalse(result["all_blockers_closed"])

    def test_tampered_receipt_fails(self):
        events, keys = self.signed_events()
        events[3]["payload"]["observed"] = False
        with self.assertRaises(EvidenceError):
            verify_lifecycle(events, keys)

    def test_missing_crash_recovery_fails(self):
        events, keys = self.signed_events()
        events.pop(4)
        with self.assertRaisesRegex(EvidenceError, "stages"):
            verify_lifecycle(events, keys)

    def test_duplicate_role_keys_fail(self):
        events, keys = self.signed_events()
        keys["observer"] = keys["supervisor"]
        with self.assertRaisesRegex(EvidenceError, "public key"):
            verify_lifecycle(events, keys)


class ScaleTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(percentile([2, 1, 3], 0.95), 3)

    def test_remote_endpoint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            probe("http://example.com:8000/api", 1, 64, 4, 3, "a" * 64, 2)

    def test_loopback_fixture_is_not_host_qualification(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                data = json.loads(self.rfile.read(length))
                receipt = {
                    **{k: data[k] for k in (
                        "request_id", "cell_id", "generation", "model_digest",
                    )},
                    "output_digest": "b" * 64,
                    "queue_age_us": 0, "success": True,
                    "terminal_observed": True,
                }
                raw = json.dumps(receipt).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            record = probe(
                f"http://127.0.0.1:{server.server_port}/infer",
                os.getpid(), 64, 4, 3, "a" * 64, 2,
            )
            self.assertEqual(record["successes"], 64)
            self.assertEqual(record["failures"], 0)
            self.assertEqual(record["configured_active_workers"], 4)
            self.assertGreaterEqual(record["client_http_inflight_peak"], 1)
            self.assertLessEqual(record["client_http_inflight_peak"], 4)
            self.assertIsNone(record["server_active_inference_peak"])
            self.assertIsNone(record["concurrently_active"])
            self.assertFalse(record["p99_at_least_100_samples"])
            self.assertEqual(
                record["measurement_scope"],
                "client_http_timing_not_attested_server_execution",
            )
            self.assertFalse(record["qualification"])
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
