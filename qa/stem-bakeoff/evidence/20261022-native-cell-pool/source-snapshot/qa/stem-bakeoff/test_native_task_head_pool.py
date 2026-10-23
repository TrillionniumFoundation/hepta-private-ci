"""Resource-accounting regressions; fixtures are not semantic model evidence."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_task_head_pool as pool


def fixture():
    cells = 32
    artifact = {"manifest_sha256": "1" * 64, "weights_sha256": "2" * 64, "weights_bytes": 144}
    reference = [{"source_record_digest": pool.sha(str(i).encode()), "prediction": {
        "task_logits": [0.5, -0.5], "task_probabilities": [0.9, 0.1],
        "predicted_class": 0, "accepted": True, "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "gate": 0.5}}
        for i in range(256)]
    memory = {"source": "native /proc/self/status", "proc_self_pid": 200,
              "getpid": 5, "rss_bytes": 20480, "rss_anon_bytes": 4096,
              "post_exec_peak_rss_bytes": 20480, "virtual_bytes": 40960}
    value = {"schema": "hepta.native-task-head-pool.v1", "status": "PASS", "cells": cells,
        "resident_heads": cells, "independently_trained_templates": 1,
        "weights_bytes_per_head": 144, "private_weights_payload_bytes": 4608,
        "manifest_sha256": artifact["manifest_sha256"], "weights_sha256": artifact["weights_sha256"],
        "request_stream_sha256": "3" * 64, "input_rows": 256, "warmup_calls": cells,
        "dispatch_calls_per_head": [128] * cells, "fanout_predictions_per_sample": cells,
        "validation_extra_reference_calls": 272, "reference_validation_outside_measurement": True,
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "energy_joules": None,
        "rss_budget_bytes": pool.MEMORY_BYTES, "address_space_hard_limit_bytes": pool.MEMORY_BYTES,
        "reference_predictions": [copy.deepcopy(row["prediction"]) for row in reference],
        "reference_source_record_digests": [row["source_record_digest"] for row in reference],
        "dispatch_nanoseconds": [2000] * 4095 + [10000],
        "fanout_nanoseconds": [100000 * (i + 1) for i in range(16)],
        "elapsed_nanoseconds": 100000000, "allocation_nanoseconds": 1000000, "warmup_nanoseconds": 2000000}
    for key in ("task_admission_allowed", "action_execution_allowed", "native_encoder_executed",
                "new_training_or_calibration", "new_independent_quality_trial", "target_device_qualified"):
        value[key] = False
    for key in ("baseline", "post_load", "post_warmup", "post_measurement"):
        value[key] = copy.deepcopy(memory)
    return value, cells, artifact, "3" * 64, reference


class PoolAccountingTests(unittest.TestCase):
    def test_native_samples_recompute_quantiles_and_keep_fanout_coarse(self):
        observed, cells, artifact, digest, reference = fixture()
        value = pool.summarize(observed, cells, artifact, digest, reference)
        self.assertEqual(value["timings"]["dispatch"]["p99_ms"], 0.002)
        self.assertEqual(value["timings"]["dispatch"]["max_ms"], 0.01)
        self.assertEqual(value["timings"]["fanout"]["median_ms"], 0.85)
        self.assertEqual(value["timings"]["fanout"]["max_ms"], 1.6)
        self.assertFalse(any(key.startswith("p9") for key in value["timings"]["fanout"]))
        self.assertEqual(value["post_load"]["proc_self_pid"], 200)
        self.assertEqual(value["post_load"]["getpid"], 5)

    def test_false_resident_count_and_unvisited_head_are_rejected(self):
        for mutate in (lambda v: v.update(resident_heads=1),
                       lambda v: v.update(private_weights_payload_bytes=144),
                       lambda v: v["dispatch_calls_per_head"].__setitem__(0, 0)):
            args = fixture()
            mutate(args[0])
            with self.assertRaises(ValueError):
                pool.summarize(*args)

    def test_input_and_prediction_source_swaps_are_rejected(self):
        for mutate in (lambda v: v.update(request_stream_sha256="a" * 64),
                       lambda v: v.update(manifest_sha256="b" * 64),
                       lambda v: v["reference_source_record_digests"].reverse()):
            args = fixture()
            mutate(args[0])
            with self.assertRaises(ValueError):
                pool.summarize(*args)

    def test_probability_drift_nonfinite_and_decision_changes_rejected(self):
        for key, value in (("accepted", False), ("accepted", 1), ("predicted_class", False),
                           ("task_logits", [0.5001, -0.5]),
                           ("task_probabilities", [float("nan"), 0.1])):
            args = fixture()
            args[0]["reference_predictions"][10][key] = value
            with self.assertRaises(ValueError):
                pool.summarize(*args)

    def test_inconsistent_proc_pid_peak_and_budget_are_rejected(self):
        for key, value in (("proc_self_pid", 999), ("rss_bytes", pool.MEMORY_BYTES + 1),
                           ("post_exec_peak_rss_bytes", 1024), ("rss_anon_bytes", 30000)):
            args = fixture()
            args[0]["post_measurement"][key] = value
            with self.assertRaises(ValueError):
                pool.summarize(*args)

    def test_fake_duration_or_coverage_of_requests_is_rejected(self):
        for mutate in (lambda v: v.update(fanout_nanoseconds=v["fanout_nanoseconds"][:-1]),
                       lambda v: v["dispatch_nanoseconds"].__setitem__(0, True),
                       lambda v: v.update(elapsed_nanoseconds=100),
                       lambda v: v.update(allocation_nanoseconds=float("nan"))):
            args = fixture()
            mutate(args[0])
            with self.assertRaises(ValueError):
                pool.summarize(*args)

    def test_execution_cannot_upgrade_authority_or_learning_claim(self):
        for key in ("task_admission_allowed", "action_execution_allowed", "new_independent_quality_trial"):
            args = fixture()
            args[0][key] = True
            with self.assertRaises(ValueError):
                pool.summarize(*args)


class BoundedProcessTests(unittest.TestCase):
    def test_output_cannot_be_created_inside_frozen_inputs_or_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, old = root / "source", root / "p40"
            source.mkdir()
            old.mkdir()
            with patch.object(pool, "ROOT", source):
                for parent in (source, old):
                    with self.assertRaisesRegex(ValueError, "external output"):
                        pool.run_pool(old, root / "missing", parent / "new",
                            expected_report="1" * 64, expected_binary="2" * 64, expected_source="3" * 40)
                    self.assertFalse((parent / "new").exists())

    def test_pinned_read_rejects_changes_links_and_oversized_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data"
            path.write_bytes(b"one")
            expected = pool.sha(b"one")
            self.assertEqual(pool.read_pinned(path, expected, 3), b"one")
            path.write_bytes(b"two")
            with self.assertRaises(ValueError):
                pool.read_pinned(path, expected, 3)
            with self.assertRaises(ValueError):
                pool.read_pinned(path, limit=2)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                pool.read_pinned(link)

    def test_timeout_kills_and_waits_for_its_own_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(subprocess.TimeoutExpired):
                pool.execute_child([sys.executable, "-c", "import time; time.sleep(10)"],
                    root / "out", root / "err", 0.05)
            self.assertEqual((root / "out").read_bytes(), b"")

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("prlimit"), "Linux resource driver")
    def test_real_filesize_limit_prevents_unbounded_child_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [shutil.which("prlimit"), "--fsize=4096:4096", "--", sys.executable, "-c",
                       "import sys; sys.stdout.buffer.write(b'x'*1000000); sys.stdout.flush()"]
            with self.assertRaises(ValueError):
                pool.execute_child(command, root / "out", root / "err", 3)
            self.assertLessEqual((root / "out").stat().st_size, 4096)


if __name__ == "__main__":
    unittest.main()
