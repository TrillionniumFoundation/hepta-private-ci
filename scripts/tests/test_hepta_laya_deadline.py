"""Real clock-budget/protocol tests. Scorer outputs are explicit test doubles."""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import hepta_retrieval_wire as wire
from scripts.hepta_laya_worker import DeadlineGuard, score_frame


def request():
    return {
        "operation_id": "op.1", "workspace_id": "ws.1", "generation": 3,
        "objective_digest": "1" * 64, "observation_digest": "2" * 64,
        "bundle_digest": "3" * 64, "deadline_ms": 9000, "query": "q",
        "sources": [{"source_id": "src.1", "revision": 7,
                     "content_sha256": hashlib.sha256(b"alpha").hexdigest(), "text": "alpha"}],
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def scorer(value):
    result = {
        "schema": "hepta.laya.retrieval.v1", "operation_id": value["operation_id"],
        "workspace_id": value["workspace_id"], "generation": value["generation"],
        "bundle_digest": value["bundle_digest"], "observation_digest": value["observation_digest"],
        "request_digest": digest(value), "production_authority": False,
        "labels": (None, "src.1"), "prediction_ppm": [100000, 900000],
        "input_tokens": 12, "output_tokens": 0, "latency_us": 7,
    }
    result["result_digest"] = digest(result)
    return result


class Clock:
    def __init__(self):
        self.wall = 100
        self.monotonic = 1000

    def guard(self, deadline=9000):
        return DeadlineGuard(deadline, now_ms=lambda: self.wall,
                             monotonic_ns=lambda: self.monotonic)


class DeadlineTests(unittest.TestCase):
    def run_score(self, clock, func=scorer, guard=None):
        return score_frame(wire.encode_request(request()), func,
                           now_ms=lambda: clock.wall,
                           monotonic_ns=lambda: clock.monotonic, deadline=guard)

    def test_valid_result_retains_v1_bytes(self):
        raw = wire.encode_request(request())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "268a20079cee413b0d086ada8cb77a6e677a4759f66f40e6b6424fa4a915a2ef")
        self.assertEqual(wire.decode_reply(self.run_score(Clock()), raw)["prediction_ppm"],
                         [100000, 900000])

    def test_wall_rollback_during_scoring_is_unknown_not_success(self):
        clock = Clock()
        calls = []
        def rollback(value):
            calls.append(1)
            clock.wall -= 1
            return scorer(value)
        with self.assertRaisesRegex(wire.WireError, "regressed"):
            self.run_score(clock, rollback)
        self.assertEqual(len(calls), 1)

    def test_frozen_wall_cannot_extend_monotonic_budget(self):
        clock = Clock()
        def slow(value):
            clock.monotonic += 8_900_000_000
            return scorer(value)
        with self.assertRaisesRegex(wire.WireError, "expired"):
            self.run_score(clock, slow)

    def test_monotonic_rollback_rejected(self):
        clock = Clock()
        def rollback(value):
            clock.monotonic -= 1
            return scorer(value)
        with self.assertRaisesRegex(wire.WireError, "regressed"):
            self.run_score(clock, rollback)

    def test_exact_absolute_deadline_rejected(self):
        clock = Clock()
        def slow(value):
            clock.wall = 9000
            return scorer(value)
        with self.assertRaisesRegex(wire.WireError, "expired"):
            self.run_score(clock, slow)

    def test_model_load_time_is_not_reset_by_score_frame(self):
        clock = Clock()
        guard = clock.guard()
        clock.monotonic += 8_900_000_000
        calls = []
        with self.assertRaisesRegex(wire.WireError, "expired"):
            self.run_score(clock, lambda value: calls.append(value), guard)
        self.assertEqual(calls, [])

    def test_clock_rollback_during_load_stays_fenced(self):
        clock = Clock()
        guard = clock.guard()
        clock.wall = 99
        with self.assertRaises(wire.WireError):
            guard.check()
        clock.wall = 101
        with self.assertRaisesRegex(wire.WireError, "unavailable"):
            guard.check()

    def test_different_deadline_guard_rejected(self):
        clock = Clock()
        with self.assertRaisesRegex(wire.WireError, "another request"):
            self.run_score(clock, guard=clock.guard(10000))

    def test_invalid_initial_clocks_and_deadlines_reject(self):
        for value in (True, -1, 1.5, 2**63, None):
            with self.subTest(value=value):
                with self.assertRaises(wire.WireError):
                    DeadlineGuard(9000, now_ms=lambda: value)
                with self.assertRaises(wire.WireError):
                    DeadlineGuard(9000, now_ms=lambda: 100, monotonic_ns=lambda: value)
                with self.assertRaises(wire.WireError):
                    DeadlineGuard(value, now_ms=lambda: 100)

    def test_later_invalid_clock_poison_guard(self):
        for field in ("wall", "monotonic"):
            clock = Clock()
            guard = clock.guard()
            setattr(clock, field, True)
            with self.assertRaises(wire.WireError):
                guard.check()
            setattr(clock, field, 10000)
            with self.assertRaisesRegex(wire.WireError, "unavailable"):
                guard.check()

    def test_scorer_error_is_not_retried(self):
        calls = []
        def broken(value):
            calls.append(1)
            raise OSError("lost reply")
        with self.assertRaises(OSError):
            self.run_score(Clock(), broken)
        self.assertEqual(calls, [1])

    def test_all_request_and_reply_truncations_reject(self):
        raw = wire.encode_request(request())
        reply = self.run_score(Clock())
        for length in range(len(raw)):
            with self.subTest(request_length=length), self.assertRaises(wire.WireError):
                wire.decode_request(raw[:length])
        for length in range(len(reply)):
            with self.subTest(reply_length=length), self.assertRaises(wire.WireError):
                wire.decode_reply(reply[:length], raw)

    def test_source_mutation_and_scope_misbinding_rejected(self):
        def mutate(value):
            value["query"] = "changed"
            return scorer(value)
        with self.assertRaises(wire.WireError):
            self.run_score(Clock(), mutate)
        def misbind(value):
            result = scorer(value)
            result["workspace_id"] = "ws.2"
            result.pop("result_digest")
            result["result_digest"] = digest(result)
            return result
        with self.assertRaises(wire.WireError):
            self.run_score(Clock(), misbind)

    def test_actual_process_rejects_before_model_loading(self):
        root = Path(__file__).resolve().parents[2]
        expired = request()
        expired["deadline_ms"] = 1
        for raw in (b"malformed", wire.encode_request(expired)):
            result = subprocess.run([
                sys.executable, str(root / "scripts/hepta_laya_worker.py"),
                "--model-root", "/nonexistent/model", "--bundle", "/nonexistent/bundle",
                "--bundle-digest", "3" * 64,
            ], input=raw, capture_output=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"WireError", result.stderr)
            self.assertNotIn(b"FileNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
