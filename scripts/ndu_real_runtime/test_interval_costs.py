"""Exercise real process clocks, journals, interruption and runtime integration."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .interval_costs import actor_receipts, close_observer_tail, reconcile, replay_receipt
from .metering import Meter, transport_receipt
from .span_meter import MeterError, record_from_jsonl, verify_record


SCRIPTS = str(Path(__file__).resolve().parents[1])


class IntervalIntegrationTests(unittest.TestCase):
    def child_source(self, journal, *, interrupted=False, operation="host/decision/00"):
        lines = ["import sys,json,hashlib,time", "from pathlib import Path",
                 "sys.path.insert(0," + repr(SCRIPTS) + ")",
                 "from ndu_real_runtime.metering import Meter",
                 "meter=Meter(" + repr(operation) + ",journal_path=Path(" + repr(str(journal)) + "))",
                 "with meter.stage('encoder','actual bounded child work'):",
                 "    value=b'interval-integration'",
                 "    for _ in range(4000): value=hashlib.sha256(value).digest()"]
        if interrupted:
            lines += ["    meter.observer.snapshot()", "    print('READY',flush=True)", "    time.sleep(10)"]
        else:
            lines += ["print(json.dumps(meter.finish()),flush=True)"]
        return "\n".join(lines)

    def run_pair(self, directory):
        meter = Meter("host", journal_path=directory / "host.jsonl")
        with meter.stage("sync", "mandatory isolated actor lifetime"):
            child = subprocess.run([sys.executable, "-I", "-c", self.child_source(directory / "decision-00.meter.jsonl")],
                                   capture_output=True, timeout=5, check=True)
            with meter.stage("codec", "host action after actor"):
                json.dumps({"real": "host serialization"})
        return meter.finish(), json.loads(child.stdout)

    def test_real_child_partition_and_journal_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            host, child = self.run_pair(directory)
            observed = actor_receipts([child], directory)
            result = reconcile(host, observed)
            self.assertEqual(result["interval_reconciliation"], "EXACT_MONOTONIC_INTERVALS_SAME_HOST")
            self.assertEqual(result["costs"]["sync"], 0)
            self.assertGreater(result["costs"]["encoder"], 0)
            self.assertGreater(result["observed_unclassified_overhead_seconds"], 0)
            self.assertAlmostEqual(sum(result["costs"].values()) + result["observed_unclassified_overhead_seconds"],
                                   result["wall_seconds"], places=9)
            self.assertIsNone(result["child_process_cpu_seconds"])
            self.assertFalse(result["full_physical_cost_complete"])
            self.assertEqual(result["actor_observed_prefixes"], 1)

    def test_killed_child_has_retained_unknown_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            meter = Meter("host-kill")
            with meter.stage("sync", "mandatory isolated actor lifetime"):
                process = subprocess.Popen([sys.executable, "-I", "-u", "-c",
                                            self.child_source(directory / "decision-00.meter.jsonl", interrupted=True,
                                                              operation="host-kill/decision/00")],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertEqual(process.stdout.readline(), b"READY\n")
                finally:
                    process.kill()
                    process.communicate(timeout=5)
            observed = actor_receipts([], directory)
            result = reconcile(meter.finish("FAILED"), observed)
            self.assertTrue(result["unclosed_actor_subcategories"])
            self.assertEqual(replay_receipt(observed[0])["envelope"]["status"], "UNKNOWN")
            self.assertGreater(result["costs"]["encoder"], 0)
            self.assertGreater(result["observed_unclassified_overhead_seconds"], 0)

    def test_duplicate_and_tampered_records_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            host, child = self.run_pair(directory)
            with self.assertRaisesRegex(MeterError, "DUPLICATE"):
                reconcile(host, [child, child])
            child["raw_spans"]["events"][0]["monotonic_ns"] += 1
            with self.assertRaisesRegex(MeterError, "INVALID_RAW_SPANS"):
                reconcile(host, [child])

    def test_child_outside_lifetime_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            _old_host, child = self.run_pair(Path(temporary))
            host = Meter("host")
            with host.stage("sync", "mandatory isolated actor lifetime"):
                pass
            with self.assertRaisesRegex(MeterError, "OUTSIDE_HOST"):
                reconcile(host.finish(), [child])

    def test_callback_receives_observed_cost_and_failure_survives(self):
        callbacks = []
        meter = Meter("callback", native_attempt_callback=lambda event, row: callbacks.append((event, row)))
        with self.assertRaisesRegex(RuntimeError, "real failure"):
            with meter.stage("planning", "failure-boundary"):
                raise RuntimeError("real failure")
        result = meter.finish()
        self.assertEqual(callbacks[-1][0], "finish")
        self.assertGreaterEqual(callbacks[-1][1]["wall_seconds"], 0)
        self.assertGreaterEqual(callbacks[-1][1]["cpu_seconds"], 0)
        self.assertEqual(replay_receipt(result)["envelope"]["status"], "FAILED")
        self.assertEqual(result["stages"][0]["status"], "failed")

    def test_truncated_journal_is_preserved_and_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _host, child = self.run_pair(directory)
            path = directory / "decision-00.meter.jsonl"
            raw = path.read_bytes() + b'{"event":'
            path.write_bytes(raw)
            with self.assertRaisesRegex(MeterError, "TRUNCATED"):
                actor_receipts([child], directory)
            self.assertEqual(path.read_bytes(), raw)

    def test_create_only_journal_and_empty_stage_gaps(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "meter.jsonl"
            receipt = Meter("only-envelope", journal_path=path).finish()
            record = record_from_jsonl(path.read_bytes())
            self.assertEqual(record, receipt["raw_spans"])
            self.assertTrue(verify_record(record)["complete_record"])
            self.assertEqual(sum(receipt["costs"].values()), 0)
            self.assertEqual(receipt["observed_unclassified_overhead_seconds"], receipt["wall_seconds"])
            with self.assertRaises(FileExistsError):
                Meter("no-overwrite", journal_path=path)

    def test_missing_and_duplicate_journal_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _host, child = self.run_pair(directory)
            path = directory / "decision-00.meter.jsonl"
            raw = path.read_bytes()
            (directory / "decision-01.meter.jsonl").write_bytes(raw)
            with self.assertRaisesRegex(MeterError, "DUPLICATE_ACTOR_JOURNAL"):
                actor_receipts([child], directory)
            path.unlink()
            (directory / "decision-01.meter.jsonl").unlink()
            with self.assertRaisesRegex(MeterError, "MISSING_RETURNED"):
                actor_receipts([child], directory)

    def test_unrelated_operation_and_startup_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            host = Meter("host")
            with host.stage("sync", "mandatory isolated actor lifetime"):
                child = subprocess.run([sys.executable, "-I", "-c", self.child_source(
                    Path(temporary) / "decision-00.meter.jsonl", operation="unrelated/decision/00")],
                    capture_output=True, timeout=5, check=True)
            with self.assertRaisesRegex(MeterError, "UNBOUND_ACTOR_OPERATION"):
                reconcile(host.finish(), [json.loads(child.stdout)])
        failed = Meter("failed-startup")
        with self.assertRaises(OSError):
            with failed.stage("sync", "mandatory isolated actor lifetime"):
                raise OSError("actor never starts")
        result = reconcile(failed.finish(), [])
        self.assertTrue(result["unclosed_actor_subcategories"])
        self.assertEqual(result["observed_unclassified_overhead_seconds"], result["wall_seconds"])

    def test_compact_transport_requires_exact_durable_raw_journal(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            host, full = self.run_pair(directory)
            compact = transport_receipt(full)
            self.assertNotIn("raw_spans", compact)
            self.assertNotIn("stages", compact)
            self.assertLess(len(json.dumps(compact)), 4096)
            recovered = actor_receipts([compact], directory)
            self.assertEqual(recovered[0]["raw_spans"], full["raw_spans"])
            self.assertEqual(reconcile(host, recovered)["costs"], reconcile(host, [full])["costs"])
            compact["wall_seconds"] += 0.01
            with self.assertRaisesRegex(MeterError, "SUMMARY_DIFFERS"):
                actor_receipts([compact], directory)
            compact = transport_receipt(full)
            compact["raw_spans_sha256"] = "0" * 64
            with self.assertRaisesRegex(MeterError, "JOURNAL_RECEIPT_MISMATCH"):
                actor_receipts([compact], directory)

    def test_observer_tail_is_charged_once_with_raw_clock_endpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            host, full = self.run_pair(directory)
            reconciled = reconcile(host, actor_receipts([transport_receipt(full)], directory))
            final = close_observer_tail(reconciled)
            tail = final["observer_tail"]
            expected = (tail["end_monotonic_ns"] - tail["start_monotonic_ns"]) / 1e9
            self.assertGreater(expected, 0)
            self.assertAlmostEqual(final["wall_seconds"] - reconciled["wall_seconds"], expected)
            self.assertAlmostEqual(sum(final["costs"].values()) + final["observed_unclassified_overhead_seconds"],
                                   final["wall_seconds"], places=9)
            with self.assertRaisesRegex(MeterError, "ALREADY_RECORDED"):
                close_observer_tail(final)


if __name__ == "__main__":
    unittest.main()
