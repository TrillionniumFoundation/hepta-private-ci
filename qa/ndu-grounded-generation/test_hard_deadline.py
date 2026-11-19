"""Cross-platform, model-free deadline boundary tests; no network or model."""
import math
import os
import time
import unittest

from hard_deadline import (
    DeadlineSupervisor, MAX_MESSAGE_BYTES, MAX_PROGRESS, MAX_VALUE_DEPTH,
    MAX_VALUE_ITEMS,
)


def make_handler():
    return fixture_handler


def broken_factory():
    raise ValueError("model unavailable")


class SlowReconstruction:
    def __reduce__(self):
        return (time.sleep, (0.6,))


def make_echo_handler():
    return echo_handler


def echo_handler(payload, emit):
    return payload


def fixture_handler(payload, emit):
    op = payload["op"]
    if op == "custom":
        return SlowReconstruction()
    if op == "large_result":
        return b"x" * (MAX_MESSAGE_BYTES + 1)
    if op == "large_progress":
        emit({"stage": "oversized", "value": b"x" * (MAX_MESSAGE_BYTES + 1)})
    if op == "hang":
        emit({"stage": "encoder_entered"})
        time.sleep(2.0)
    if op == "crash":
        os._exit(7)
    if op == "bad":
        raise RuntimeError("bad model input")
    if op == "flood":
        for _ in range(MAX_PROGRESS + 10):
            emit({"stage": "loop"})
    emit({"stage": "decoded", "tokens": 5})
    return {"pid": os.getpid(), "boxes": [[1, 2, 3, 4]]}


class DeadlineBoundaryTests(unittest.TestCase):
    def test_finite_deadline_and_canonical_id(self):
        with DeadlineSupervisor(make_handler) as sup:
            for bad in (0, -1, math.inf, math.nan):
                with self.assertRaises(ValueError):
                    sup.run("valid:1", {"op": "ok"}, deadline_s=bad)
            for bad in ("", "../x", "white space", "a"*129):
                with self.assertRaises(ValueError):
                    sup.run(bad, {"op": "ok"})

    def test_success_reuses_warm_worker(self):
        with DeadlineSupervisor(make_handler, start_timeout_s=5) as sup:
            a = sup.run("a", {"op": "ok"}, deadline_s=2)
            b = sup.run("b", {"op": "ok"}, deadline_s=2)
            self.assertTrue(a.complete and b.complete)
            self.assertEqual(a.result["pid"], b.result["pid"])
            self.assertGreater(a.worker_startup_wall_s, 0)
            self.assertEqual(b.worker_startup_wall_s, 0)
            self.assertEqual(sup.startup_wall_total_s, a.worker_startup_wall_s)
            self.assertGreaterEqual(a.worker_cpu_s, 0)
            self.assertEqual(a.progress[0]["event"]["stage"], "decoded")

    def test_timeout_kills_worker_and_restarts(self):
        with DeadlineSupervisor(make_handler, start_timeout_s=5) as sup:
            first = sup.run("one", {"op": "ok"}, deadline_s=2)
            at = time.monotonic()
            bad = sup.run("two", {"op": "hang"}, deadline_s=.12)
            elapsed = time.monotonic() - at
            self.assertEqual(bad.status, "timeout")
            self.assertFalse(bad.complete)
            self.assertIsNone(bad.worker_cpu_s)
            self.assertIsNone(bad.result)
            self.assertGreaterEqual(bad.episode_wall_s, .11)
            self.assertLess(elapsed, 1.4)
            self.assertEqual(bad.progress[0]["event"]["stage"], "encoder_entered")
            again = sup.run("three", {"op": "ok"}, deadline_s=2)
            self.assertTrue(again.complete)
            self.assertNotEqual(first.result["pid"], again.result["pid"])
            self.assertGreater(sup.startup_wall_total_s, first.worker_startup_wall_s)

    def test_exception_is_charged_and_fails_closed(self):
        with DeadlineSupervisor(make_handler) as sup:
            bad = sup.run("err", {"op": "bad"}, deadline_s=2)
            self.assertEqual(bad.status, "task_error")
            self.assertEqual(bad.reason, "RuntimeError")
            self.assertIsNone(bad.result)
            good = sup.run("next", {"op": "ok"}, deadline_s=2)
            self.assertTrue(good.complete)

    def test_process_death_is_not_a_success(self):
        with DeadlineSupervisor(make_handler) as sup:
            result = sup.run("crash", {"op": "crash"}, deadline_s=2)
            self.assertEqual(result.status, "unavailable")
            self.assertIsNone(result.result)
            self.assertTrue(sup.run("recovered", {"op": "ok"}, deadline_s=2).complete)

    def test_startup_failure_is_fatal_for_episode(self):
        with DeadlineSupervisor(broken_factory) as sup:
            outcome = sup.run("a", {}, deadline_s=2)
            self.assertEqual(outcome.status, "unavailable")
            self.assertEqual(outcome.reason, "startup_error")
            self.assertEqual(outcome.episode_wall_s, 0)
            self.assertGreater(outcome.worker_startup_wall_s, 0)

    def test_progress_overflow_rejected(self):
        with DeadlineSupervisor(make_handler) as sup:
            bad = sup.run("flood", {"op": "flood"}, deadline_s=2)
            self.assertEqual(bad.status, "protocol_error")
            self.assertEqual(bad.reason, "progress_limit")
            self.assertEqual(len(bad.progress), MAX_PROGRESS)

    def test_unpickleable_factory_rejected(self):
        with self.assertRaises((AttributeError, TypeError)):
            DeadlineSupervisor(lambda: fixture_handler)

    def test_custom_result_never_reconstructs_in_supervisor(self):
        with DeadlineSupervisor(make_handler, start_timeout_s=5) as sup:
            self.assertTrue(sup.run("warm", {"op": "ok"}, deadline_s=2).complete)
            started = time.monotonic()
            outcome = sup.run("custom", {"op": "custom"}, deadline_s=.05)
            self.assertLess(time.monotonic() - started, .4)
            self.assertEqual(outcome.status, "task_error")
            self.assertEqual(outcome.reason, "ValueError")
            self.assertIsNone(outcome.result)

    def test_builtin_round_trip_preserves_types_and_null(self):
        values = [None, (b"binary", True, 12, .25, ["text"], {"null": None})]
        with DeadlineSupervisor(make_echo_handler, start_timeout_s=5) as sup:
            for value in values:
                outcome = sup.run("data", value, deadline_s=2)
                self.assertTrue(outcome.complete)
                self.assertEqual(type(outcome.result), type(value))
                self.assertEqual(outcome.result, value)

    def test_oversized_result_and_progress_are_rejected(self):
        with DeadlineSupervisor(make_handler, start_timeout_s=5) as sup:
            for op in ("large_result", "large_progress"):
                with self.subTest(op=op):
                    outcome = sup.run(op, {"op": op}, deadline_s=2)
                    self.assertEqual(outcome.status, "task_error")
                    self.assertIsNone(outcome.result)
                    self.assertEqual(outcome.progress, ())

    def test_invalid_payload_bounds_fail_without_handler_execution(self):
        cycle = []
        cycle.append(cycle)
        deep = None
        for _ in range(MAX_VALUE_DEPTH + 1):
            deep = [deep]
        invalid = [SlowReconstruction(), cycle, deep, [0] * (MAX_VALUE_ITEMS + 1),
                   b"x" * (MAX_MESSAGE_BYTES + 1), 1 << 257, float("nan"), {1: "key"}]
        with DeadlineSupervisor(make_echo_handler, start_timeout_s=5) as sup:
            for index, value in enumerate(invalid):
                with self.subTest(index=index):
                    outcome = sup.run("invalid", value, deadline_s=2)
                    self.assertEqual(outcome.status, "protocol_error")
                    self.assertEqual(outcome.reason, "invalid_payload")
                    self.assertIsNone(outcome.result)
            self.assertTrue(sup.run("recovered", "ok", deadline_s=2).complete)


if __name__ == "__main__":
    unittest.main()
