"""Lifecycle, adversarial replay and real subprocess checks for the v2 meter."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from .span_meter import (
    MeterError,
    SpanMeter,
    record_from_jsonl,
    record_sha256,
    run_subprocess_probe,
    verify_record,
)


def burn_cpu():
    value = b"bounded-meter-check"
    for _ in range(1000):
        value = hashlib.sha256(value).digest()
    return value


def example_record():
    meter = SpanMeter("owner-operation")
    with meter.attempt("original"):
        with meter.span("planning", "planning"):
            burn_cpu()
            with meter.span("critic", "critic"):
                burn_cpu()
    return meter.finish()


def rechain(record):
    previous = record_sha256(record["header"])
    for index, event in enumerate(record["events"]):
        event.update(seq=index, previous_sha256=previous)
        event.pop("sha256", None)
        event["sha256"] = record_sha256(event)
        previous = event["sha256"]
    return record


class SpanMeterTests(unittest.TestCase):
    def test_nested_raw_clock_partition_and_cpu_scope(self):
        record = example_record()
        replay = verify_record(record, expected_sha256=record_sha256(record))
        self.assertTrue(replay["valid"], replay)
        self.assertTrue(replay["complete_record"])
        for dimension in ("wall", "process_cpu"):
            categorized = sum(
                row["exclusive_" + dimension + "_ns"]
                for row in replay["categories"].values()
            )
            self.assertEqual(
                categorized + replay["uninstrumented"][dimension + "_ns"],
                replay["envelope"]["inclusive_" + dimension + "_ns"],
            )
        nodes = {row["span_id"]: row for row in replay["spans"]}
        self.assertEqual(
            nodes["planning"]["inclusive_wall_ns"],
            nodes["planning"]["exclusive_wall_ns"]
            + nodes["critic"]["inclusive_wall_ns"],
        )
        self.assertEqual(
            nodes["critic"]["start_monotonic_ns"], record["events"][3]["monotonic_ns"]
        )
        self.assertGreater(nodes["critic"]["exclusive_process_cpu_ns"], 0)
        self.assertEqual(
            (
                replay["child_process_cpu_ns"],
                replay["energy_joules"],
                replay["provider_charges"],
            ),
            (None, None, None),
        )

    def test_uninstrumented_is_unknown_not_synchronization(self):
        meter = SpanMeter("uncovered-setup")
        burn_cpu()
        replay = verify_record(meter.finish())
        self.assertTrue(replay["valid"])
        self.assertEqual(
            replay["uninstrumented"]["wall_ns"], replay["envelope"]["inclusive_wall_ns"]
        )
        self.assertEqual(replay["categories"]["sync"]["exclusive_wall_ns"], 0)
        self.assertEqual(replay["uninstrumented"]["status"], "UNKNOWN")
        self.assertFalse(replay["full_physical_cost_complete"])

    def test_failed_retry_budgetstop_cancel_and_unknown_are_retained(self):
        meter = SpanMeter("all-attempts")
        with self.assertRaisesRegex(RuntimeError, "observed failure"):
            with meter.attempt("failed"):
                with meter.span("failed-work", "encoder"):
                    raise RuntimeError("observed failure")
        with meter.attempt("retry", retry_of="failed") as attempt:
            attempt.set_status("BUDGET_STOP")
        with self.assertRaises(KeyboardInterrupt):
            with meter.attempt("canceled"):
                raise KeyboardInterrupt()
        with meter.attempt("unresolved") as attempt:
            attempt.set_status("UNKNOWN")
        with self.assertRaisesRegex(MeterError, "UNBOUND_OR_UNRESOLVED_RETRY"):
            with meter.attempt("unsafe-retry", retry_of="unresolved"):
                self.fail("An unresolved prior attempt must not admit a retry")
        replay = verify_record(meter.finish("UNKNOWN"))
        self.assertTrue(replay["valid"], replay)
        self.assertEqual(
            [
                (a["attempt_id"], a["retry_of"], a["status"], a["error_type"])
                for a in replay["attempts"]
            ],
            [
                ("failed", None, "FAILED", "RuntimeError"),
                ("retry", "failed", "BUDGET_STOP", None),
                ("canceled", None, "CANCELED", "KeyboardInterrupt"),
                ("unresolved", None, "UNKNOWN", None),
            ],
        )

    def test_durable_sink_prefix_replays_open_spans_as_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            with path.open("xb") as output:

                def persist(raw):
                    self.assertIsInstance(raw, bytes)
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())

                meter = SpanMeter("native-prefix", event_sink=persist)
                with meter.attempt("a"):
                    with meter.span("work", "shared"):
                        burn_cpu()
                        snapshot = meter.snapshot()
                        prefix = path.read_bytes()
                        with self.assertRaisesRegex(MeterError, "UNCLOSED_CHILD_SPANS"):
                            meter.finish()
                complete = meter.finish()
            self.assertEqual(record_from_jsonl(prefix), snapshot)
            self.assertEqual(record_from_jsonl(path.read_bytes()), complete)
        replay = verify_record(snapshot)
        self.assertTrue(replay["valid"], replay)
        self.assertFalse(replay["complete_record"])
        self.assertTrue(replay["unobserved_tail"])
        self.assertEqual(
            [(s["status"], s["end_monotonic_ns"]) for s in replay["spans"]],
            [("UNKNOWN", None), ("UNKNOWN", None), ("UNKNOWN", None)],
        )

    def test_external_pin_and_hash_chain_do_not_replace_structural_replay(self):
        original = example_record()
        edited = copy.deepcopy(original)
        edited["events"][4]["status"] = "FAILED"
        self.assertEqual(
            verify_record(edited)["diagnostics"][0]["code"], "BROKEN_EVENT_CHAIN"
        )
        rechain(edited)
        self.assertEqual(
            verify_record(edited, expected_sha256=record_sha256(original))[
                "diagnostics"
            ][0]["code"],
            "EXTERNAL_DIGEST_MISMATCH",
        )
        cases = [
            ("PARENT_OR_OVERLAP_MISMATCH", 3, "parent_id", "envelope"),
            ("NON_LIFO_CLOSE", 4, "span_id", "planning"),
            (
                "FOREIGN_PROCESS_OR_THREAD",
                2,
                "process_id",
                original["header"]["process_id"] + 1,
            ),
            ("INVALID_CLOCK_SAMPLE", 2, "process_time_ns", True),
            ("DUPLICATE_OR_INVALID_SPAN", 3, "span_id", "planning"),
            (
                "CLOCK_REGRESSION",
                3,
                "monotonic_ns",
                original["events"][2]["monotonic_ns"] - 1,
            ),
            (
                "CLOCK_REGRESSION",
                3,
                "process_time_ns",
                original["events"][2]["process_time_ns"] - 1,
            ),
        ]
        for code, index, field, value in cases:
            with self.subTest(code=code, field=field):
                malformed = copy.deepcopy(original)
                malformed["events"][index][field] = value
                replay = verify_record(rechain(malformed))
                self.assertFalse(replay["valid"])
                self.assertEqual(replay["diagnostics"][0]["code"], code)
                self.assertNotIn("categories", replay)

    def test_closed_envelope_cannot_acquire_events_or_be_resurrected(self):
        meter = SpanMeter("closed")
        completed = meter.finish()
        with self.assertRaisesRegex(MeterError, "CLOSED_OR_POISONED_METER"):
            with meter.span("late", "retry"):
                self.fail("No work after the envelope closes")
        completed["events"].append({**completed["events"][-1], "kind": "checkpoint"})
        self.assertEqual(
            verify_record(rechain(completed))["diagnostics"][0]["code"],
            "EVENT_AFTER_ENVELOPE_CLOSE",
        )

    def test_live_clock_regression_poison_preserves_bad_raw_sample(self):
        meter = SpanMeter("clock-anomaly")
        earlier = meter.snapshot()["events"][-1]["monotonic_ns"] - 1
        with patch(
            "ndu_real_runtime.span_meter.time.monotonic_ns", return_value=earlier
        ):
            with self.assertRaisesRegex(MeterError, "CLOCK_REGRESSION"):
                meter.snapshot()
        raw = meter.snapshot()
        self.assertEqual(
            (raw["capture_errors"], raw["events"][-1]["monotonic_ns"]),
            (["CLOCK_REGRESSION"], earlier),
        )
        self.assertFalse(verify_record(raw)["valid"])

    def test_sink_failure_prevents_work_and_retains_unknown_durable_prefix(self):
        published = []

        def sink(raw):
            if len(published) == 2:
                raise OSError("fsync failed")
            published.append(raw)

        meter = SpanMeter("sink-failure", event_sink=sink)
        with self.assertRaisesRegex(OSError, "fsync failed"):
            with meter.attempt("never-admitted"):
                self.fail("Publication failure must precede actual work")
        self.assertEqual(meter.snapshot()["capture_errors"], ["EVENT_SINK_FAILED"])
        self.assertFalse(verify_record(meter.snapshot())["valid"])
        prefix = verify_record(record_from_jsonl(b"".join(published)))
        self.assertTrue(prefix["valid"])
        self.assertFalse(prefix["complete_record"])

    def test_foreign_thread_cannot_mutate_event_tree(self):
        meter, errors = SpanMeter("one-thread"), []

        def other_thread():
            try:
                meter.snapshot()
            except MeterError as error:
                errors.append(str(error))

        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        self.assertEqual(errors, ["FOREIGN_PROCESS_OR_THREAD"])
        self.assertTrue(verify_record(meter.finish())["valid"])

    def test_journal_truncation_and_ambiguous_json_are_rejected(self):
        with self.assertRaisesRegex(MeterError, "TRUNCATED_JOURNAL_LINE"):
            record_from_jsonl(b'{"header":')
        with self.assertRaisesRegex(MeterError, "DUPLICATE_JSON_KEY"):
            record_from_jsonl(b'{"header":{},"header":{}}\n')

    def test_actual_bounded_subprocess_and_timeout_keep_cpu_scopes_separate(self):
        observed = run_subprocess_probe(timeout_seconds=5)
        self.assertTrue(observed["replay"]["valid"], observed)
        self.assertEqual(observed["subprocess"]["returncode"], 0)
        body = json.loads(observed["subprocess"]["stdout"])
        self.assertGreater(
            body["end_process_time_ns"] - body["start_process_time_ns"], 0
        )
        self.assertEqual(observed["replay"]["child_process_cpu_ns"], None)
        # The success path above is real. Deadline classification is injected to
        # avoid a scheduler race on machines where a tiny process finishes first.
        with patch(
            "ndu_real_runtime.span_meter.subprocess.run",
            side_effect=subprocess.TimeoutExpired("probe", 0.1),
        ):
            timed_out = run_subprocess_probe(timeout_seconds=0.1)
        self.assertTrue(timed_out["replay"]["valid"])
        self.assertEqual(timed_out["replay"]["attempts"][0]["status"], "CANCELED")
        self.assertIsNone(timed_out["subprocess"]["body"])


if __name__ == "__main__":
    unittest.main()
