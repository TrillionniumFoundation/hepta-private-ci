"""Counter/parser and manual GC callback boundaries; no model or dataset."""

import gc
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from independent import telemetry as t


class TelemetryTests(unittest.TestCase):
    def test_same_process_numerical_metadata_fingerprints_loaded_library_without_configuration(self):
        import threadpoolctl
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "manual-library"
            library.write_bytes(b"manual numerical library fixture")
            pool = {"internal_api": "manual", "num_threads": 1, "filepath": str(library),
                    "version": "fixture", "architecture": "manual"}
            with patch.object(threadpoolctl, "threadpool_info", return_value=[pool]):
                observed = t.numerical_runtime()
            self.assertEqual(observed["threadpools"][0]["sha256"], hashlib.sha256(library.read_bytes()).hexdigest())
            self.assertEqual(observed["threadpools"][0]["num_threads"], 1)
            self.assertEqual(pool, {"internal_api": "manual", "num_threads": 1,
                "filepath": str(library), "version": "fixture", "architecture": "manual"})
            self.assertFalse(observed["threadpools_truncated"])
            self.assertEqual(observed["errors"], {})
            json.dumps(observed, allow_nan=False)

    def test_optional_backend_discovery_failure_is_retained_without_aborting_model_work(self):
        import threadpoolctl
        with patch.object(threadpoolctl, "threadpool_info", side_effect=RuntimeError("manual unavailable backend")):
            observed = t.numerical_runtime()
        self.assertEqual(observed["threadpools"], [])
        self.assertIn("manual unavailable backend", observed["errors"]["threadpool_discovery"])
        self.assertIn("numpy_version", observed)
        json.dumps(observed, allow_nan=False)

    def test_capture_and_real_read_only_delta_are_json(self):
        before, after = t.capture(), t.capture()
        delta = t.difference(before, after)
        json.dumps([before, after, delta], allow_nan=False)
        self.assertGreaterEqual(delta["process_cpu_ns"], 0)
        self.assertGreaterEqual(delta["wall_ns"], 0)
        self.assertGreaterEqual(after["process_threads"], 1)
        self.assertGreaterEqual(after["sampling"]["cpu_ns"], 0)
        self.assertEqual(delta["container"]["scope"], t.CONTAINER_SCOPE)

    def test_optional_missing_counter_is_an_error_not_zero(self):
        with patch.object(t, "_counter_file", side_effect=FileNotFoundError("missing fixture")):
            snapshot = t.capture()
        self.assertIsNone(snapshot["container"]["cpu_stat"])
        self.assertIn("FileNotFoundError", snapshot["errors"]["container.cpu_stat"])
        delta = t.difference(snapshot, snapshot)
        self.assertIsNone(delta["container"]["cpu_stat"])
        self.assertIn("before.container.cpu_stat", delta["errors"])

    def test_counter_file_rejects_duplicate_negative_and_malformed(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "counter"
            path.write_text("usage_usec 42\nnr_throttled 3\n")
            self.assertEqual(t._counter_file(path), {"usage_usec": 42, "nr_throttled": 3})
            for text in ("a 1\na 2", "a -1", "a 1 2", "", "a nan"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    t._counter_file(path)

    def test_reset_missing_counter_and_thread_gauge_are_distinct(self):
        before = {"schema": t.SCHEMA, "process_cpu_ns": 10, "wall_ns": 20,
                  "identity": {"pid": 3, "start_ticks": 4, "thread_id": 5},
                  "thread_cpu_ns": 5, "process_threads": 4, "rusage": {"minor_faults": 2},
                  "container": {"cpu_stat": {"usage_usec": 9}, "memory_events": {"oom": 0}}}
        after = {**before, "process_cpu_ns": 15, "wall_ns": 25, "thread_cpu_ns": 2,
                 "process_threads": 1, "rusage": {"minor_faults": 3, "major_faults": 0}}
        delta = t.difference(before, after)
        self.assertEqual(delta["process_cpu_ns"], 5)
        self.assertEqual(delta["process_threads"], {"before": 4, "after": 1})
        self.assertIsNone(delta["thread_cpu_ns"])
        self.assertIsNone(delta["rusage"]["major_faults"])
        self.assertIn("reset", delta["errors"]["thread_cpu_ns"])
        with self.assertRaises(ValueError):
            t.difference({}, after)

    def test_process_and_native_thread_identity_cannot_cross(self):
        before = t.capture()
        after = {**before, "identity": {**before["identity"], "thread_id": -1}}
        self.assertIsNone(t.difference(before, after)["thread_cpu_ns"])
        self.assertEqual(t.difference(before, after)["process_cpu_ns"], 0)
        after["identity"]["pid"] = -1
        self.assertIsNone(t.difference(before, after)["process_cpu_ns"])
        after["identity"] = {key: value for key, value in before["identity"].items() if key != "thread_id"}
        self.assertIsNone(t.difference(after, after)["thread_cpu_ns"])

    def test_manual_gc_events_bounded_with_complete_totals(self):
        monitor = t.GCMonitor(max_events=2)
        with monitor, patch.object(t, "_stamp", side_effect=[(0, 0), (2, 3), (10, 10), (14, 15), (20, 20), (26, 27)]):
            for _ in range(3):
                monitor._observe("start", {"generation": 1})
                monitor._observe("stop", {})
        result = monitor.snapshot()
        self.assertEqual([result[k] for k in ("count", "cpu_ns_total", "wall_ns_total", "cpu_ns_max", "wall_ns_max", "dropped_events")], [3, 12, 15, 6, 7, 1])
        self.assertEqual(len(result["events"]), 2)
        self.assertNotIn(monitor._callback, gc.callbacks)
        json.dumps(result, allow_nan=False)

    def test_gc_detaches_on_exception_and_keeps_other_callbacks(self):
        original = list(gc.callbacks)
        monitor = t.GCMonitor()
        with self.assertRaisesRegex(RuntimeError, "sentinel"):
            with monitor:
                gc.collect()
                raise RuntimeError("sentinel")
        self.assertEqual(gc.callbacks, original)
        self.assertFalse(monitor.snapshot()["active"])
        self.assertGreaterEqual(monitor.snapshot()["count"], 1)

    def test_gc_mismatches_and_reentry_do_not_leak_callback(self):
        monitor = t.GCMonitor()
        with monitor:
            monitor._observe("stop", {})
            monitor._observe("start", {})
            monitor._observe("start", {})
            with self.assertRaises(RuntimeError):
                monitor.__enter__()
        self.assertEqual(monitor.snapshot()["unmatched_stops"], 1)
        self.assertEqual(monitor.snapshot()["unmatched_starts"], 2)
        self.assertFalse(monitor.snapshot()["pending"])
        self.assertNotIn(monitor._callback, gc.callbacks)


if __name__ == "__main__":
    unittest.main()
