"""Adversarial read-only qualification of the synthetic execution transport probe."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_probe as probe  # noqa: E402


class IntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = probe.make_intents(64, 2, 32)[0]
        self.intent = json.loads(self.raw)

    def broken(self, **delta: object) -> bytes:
        data = dict(self.intent)
        data.update(delta)
        return probe.canonical_json(data)

    def test_valid_pure_result_is_canonical_and_deny_all(self) -> None:
        result = probe.evaluate(self.raw)
        probe.validate_receipt(result, self.raw)
        record = json.loads(result)
        self.assertEqual(record["disposition"], "SYNTHETIC_ONLY")
        self.assertEqual(record["authority"], "DENY_ALL")
        self.assertIs(record["external_effect_observed"], False)
        self.assertEqual(record["payload_sha256"], hashlib.sha256(b"x" * 32).hexdigest())

    def test_reject_unsigned_authorization_field(self) -> None:
        with self.assertRaises(probe.ProtocolRejected):
            probe.evaluate(self.broken(authorized=True))

    def test_reject_missing_field(self) -> None:
        data = dict(self.intent)
        del data["scope"]
        with self.assertRaises(probe.ProtocolRejected):
            probe.evaluate(probe.canonical_json(data))

    def test_reject_duplicate_json_key(self) -> None:
        raw = self.raw.replace(b'"version":1', b'"version":1,"version":1')
        with self.assertRaises(probe.ProtocolRejected):
            probe.evaluate(raw)

    def test_reject_wrong_payload_digest(self) -> None:
        with self.assertRaises(probe.ProtocolRejected):
            probe.evaluate(self.broken(payload="y" * 32))

    def test_reject_forged_or_stale_boundaries(self) -> None:
        for delta in [dict(scope="research/other"), dict(generation=0),
                      dict(fence=-1), dict(fence=True), dict(version=2),
                      dict(operation_id="../escape"), dict(payload_sha256="A" * 64)]:
            with self.subTest(delta=delta), self.assertRaises(probe.ProtocolRejected):
                probe.evaluate(self.broken(**delta))

    def test_reject_nonfinite_extra_and_nonobject(self) -> None:
        for raw in [b'[]', b'{"oops":1}', b'not json', b'\xff',
                    b'{"version":NaN}', b'null']:
            with self.subTest(raw=raw), self.assertRaises(probe.ProtocolRejected):
                probe.evaluate(raw)

    def test_reject_unbounded_payload_or_frame(self) -> None:
        with self.assertRaises(probe.ProtocolRejected):
            probe.evaluate(self.broken(payload="a" * (probe.MAX_PAYLOAD_BYTES + 1)))
        with self.assertRaises(probe.ProtocolRejected):
            probe.evaluate(b"x" * (probe.MAX_FRAME_BYTES + 1))

    def test_receipt_cannot_claim_external_effect_or_authority(self) -> None:
        result = json.loads(probe.evaluate(self.raw))
        for delta in [dict(authority="ALLOW"), dict(external_effect_observed=True),
                      dict(operation_id="cell-88888"), dict(disposition="COMPLETED"),
                      dict(scope="other"), dict(generation=2), dict(fence=2)]:
            with self.subTest(delta=delta), self.assertRaises(probe.ProtocolRejected):
                probe.validate_receipt(probe.canonical_json({**result, **delta}), self.raw)

    def test_receipt_cannot_add_fields_or_reorder_noncanonical_bytes(self) -> None:
        result = json.loads(probe.evaluate(self.raw))
        with self.assertRaises(probe.ProtocolRejected):
            probe.validate_receipt(probe.canonical_json({**result, "signed": True}), self.raw)
        reversed_record = {k: result[k] for k in reversed(result)}
        with self.assertRaises(probe.ProtocolRejected):
            probe.validate_receipt(json.dumps(reversed_record).encode("ascii"), self.raw)

    def test_make_intents_bounds_and_unique_operations(self) -> None:
        for args in [(0, 1, 0), (4_097, 1, 0), (64, 65, 1),
                     (64, 0, 0), (64, 1, -1), (64, 1, 8_193)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                probe.make_intents(*args)
        result = probe.make_intents(1_024, 256, 0)
        self.assertEqual(len(result), len(set(result)))
        self.assertEqual(len({json.loads(x)["payload_sha256"] for x in result}), 1)


class WireTests(unittest.TestCase):
    def test_framing_roundtrip_and_clean_eof(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            probe.send_frame(left, b"hello")
            self.assertEqual(probe.recv_frame(right), b"hello")
            left.shutdown(socket.SHUT_WR)
            self.assertIsNone(probe.recv_frame(right))

    def test_truncated_header_or_body_is_unknown_not_a_retry(self) -> None:
        for data in [b"\x00\x00", struct.pack(">I", 8) + b"oops"]:
            left, right = socket.socketpair()
            with left, right:
                left.sendall(data)
                left.shutdown(socket.SHUT_WR)
                with self.assertRaises(probe.TransportIndeterminate):
                    probe.recv_frame(right)

    def test_zero_or_overbudget_frames_reject_without_reading_body(self) -> None:
        for size in [0, probe.MAX_FRAME_BYTES + 1]:
            left, right = socket.socketpair()
            with left, right:
                left.sendall(struct.pack(">I", size))
                with self.assertRaises(probe.ProtocolRejected):
                    probe.recv_frame(right)

    def test_invalid_outgoing_frames_rejected(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            for raw in [b"", b"y" * (probe.MAX_FRAME_BYTES + 1)]:
                with self.assertRaises(probe.ProtocolRejected):
                    probe.send_frame(left, raw)

    @unittest.skipUnless(os.name == "posix", "POSIX socketpair needed")
    def test_persistent_process_bounded_and_same_identity(self) -> None:
        intents = probe.make_intents(256, 8, 64)
        with probe.ProcessClient() as client:
            self.assertIsNone(client.process.poll())
            pid = client.process.pid
            self.assertEqual(client.processes_spawned, 1)
            for intent in intents:
                probe.validate_receipt(client.request(intent), intent)
            self.assertEqual(client.process.pid, pid)

    @unittest.skipUnless(os.name == "posix", "POSIX socketpair needed")
    def test_invalid_worker_intent_is_explicit_denial_not_success(self) -> None:
        with probe.ProcessClient() as client:
            result = json.loads(client.request(b'{"malicious":"shell"}'))
            self.assertEqual(result, {"authority": "DENY_ALL", "rejected": "INVALID_RESEARCH_INTENT"})
            original = probe.make_intents(64, 1, 2)[0]
            probe.validate_receipt(client.request(original), original)

    def test_no_forged_transport_replay_on_unknown_result(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            left.shutdown(socket.SHUT_WR)
            with self.assertRaises(probe.TransportIndeterminate):
                probe.recv_exact(right, 4)


class BenchmarkTests(unittest.TestCase):
    def test_invalid_matrix_or_modes_fail_before_runs(self) -> None:
        for args in [dict(logical_cells=64, active_cells=64, payload_bytes=0, rounds=0,
                          modes=["direct"]),
                     dict(logical_cells=64, active_cells=1, payload_bytes=0, rounds=1,
                          modes=["direct", "direct"]),
                     dict(logical_cells=64, active_cells=1, payload_bytes=0, rounds=1,
                          modes=["fake"]),
                     dict(logical_cells=4_096, active_cells=4_096, payload_bytes=0,
                          rounds=4, modes=["direct"])]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                probe.benchmark(**args)

    def test_cold_cannot_compare_partial_sample_silently(self) -> None:
        intents = probe.make_intents(64, 8, 0)
        with self.assertRaises(ValueError):
            probe.run_mode("cold", intents, 5)

    def test_p95_and_p99_require_enough_observations(self) -> None:
        self.assertIsNone(probe.summarize_ms([1.0] * 19)["p95_ms"])
        self.assertEqual(probe.summarize_ms([1.0] * 20)["p95_ms"], 1.0)
        self.assertIsNone(probe.summarize_ms([1.0] * 99)["p99_ms"])
        self.assertEqual(probe.summarize_ms([float(i) for i in range(100)])["p99_ms"], 98.0)

    def test_research_flags_are_never_runtime_evidence(self) -> None:
        result = probe.benchmark(64, 8, 16, 2, ["direct", "queue"])
        self.assertFalse(result["real_codex_exec_server"])
        self.assertFalse(result["real_hepta_runtime"])
        self.assertFalse(result["real_model_or_tool_effects"])
        self.assertFalse(result["production_qualification"])
        self.assertEqual(result["status"], "RESEARCH_DENY_ALL")
        self.assertEqual(len({x["observed_receipts_sha256"] for x in result["runs"]}), 1)

    @unittest.skipUnless(os.name == "posix", "POSIX process tests")
    def test_all_modes_same_bytes_and_correct_process_counts(self) -> None:
        result = probe.benchmark(64, 2, 64, 2,
                                 ["direct", "queue", "persistent", "cold"])
        self.assertEqual({x["operations"] for x in result["runs"]}, {4})
        self.assertEqual([x["processes_spawned"] for x in result["runs"]],
                         [0, 0, 1, 4])
        self.assertEqual({x["observed_receipts_sha256"] for x in result["runs"]},
                         {result["expected_receipts_sha256"]})
        self.assertTrue(all(x["dispatch_latency"]["p95_ms"] is None
                            for x in result["runs"]))

    def test_incorrect_result_never_counted_as_success(self) -> None:
        original = probe.evaluate
        with mock.patch.object(probe, "evaluate", wraps=original) as pure:
            result = probe.run_mode("direct", probe.make_intents(64, 1, 0), 1)
            self.assertEqual(result["operations"], 1)
            self.assertGreaterEqual(pure.call_count, 2)
        with mock.patch.object(probe.DirectClient, "request", return_value=b'{}'):
            with self.assertRaises(probe.ProtocolRejected):
                probe.run_mode("direct", probe.make_intents(64, 1, 0), 1)


if __name__ == "__main__":
    unittest.main()
