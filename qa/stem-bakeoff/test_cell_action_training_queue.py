"""Synthetic-input integration checks for source-bound real optimizer jobs."""

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from cell_action_training_queue import (MODES, load_job_inputs, owned_path, persist_training_jobs,
    sha_file, train_persisted_job, verify_queue_publications)
from cell_calibration_bounded import apply_bounded_calibrator, fit_bounded_calibrator
from cell_learning_models import NumpyCellHead, canonical
from cell_training_queue import TrainingQueue
from probe_action_training_queue import run_probe


IDENTITY, BUNDLE = "a"*64, "b"*64


class ActionTrainingQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "queue"
        rng = np.random.default_rng(918)
        self.x = rng.normal(size=(32, 770)).astype(np.float32)
        self.y = (np.arange(32) % 2).astype(np.int64)
        self.rows = [{"source_id": f"source-{i}", "group_id": f"group-{i}"} for i in range(32)]
        self.meta = {"feature_identity": IDENTITY, "generation": 1, "task_id": "action_usefulness"}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, root=None, *, deadline_ns=None):
        return persist_training_jobs(root or self.root, self.meta, self.x, self.y, self.rows,
            bundle_manifest_sha256=BUNDLE, deadline_ns=deadline_ns or time.time_ns()+60_000_000_000)

    def claim(self, submission):
        with TrainingQueue(self.root / "training.sqlite", max_jobs=3) as queue:
            queue.submit(**submission)
            return queue.claim(lease_ns=30_000_000_000)

    def test_parameter_update_invalidates_old_calibrator_and_roundtrips_artifact(self):
        prepared = self.prepare()
        job = self.claim(prepared["submissions"][0])
        result = train_persisted_job(self.root, job)
        self.assertNotEqual(result["tensor_sha256"], result["initial_tensor_sha256"])
        self.assertEqual((result["training"]["optimizer_steps"], result["training"]["training_rows"],
                          result["calibration"], result["calibration_status"]),
                         (20, 32, None, "unavailable_after_parameter_update"))
        bindings = {"feature_identity": IDENTITY, "predictor_sha256": result["initial_tensor_sha256"],
                    "calibration_context_sha256": "c"*64}
        fit = fit_bounded_calibrator(np.array([-.5, .5, -.2, .2]), np.array([0, 1, 0, 1]),
            [{"source_id": f"cal-{i}", "group_id": f"cal-{i}"} for i in range(4)],
            effective_training_prior=[.5, .5], bindings=bindings)
        with self.assertRaises(ValueError):
            apply_bounded_calibrator(np.array([.2]), fit,
                expected_bindings={**bindings, "predictor_sha256": result["tensor_sha256"]})
        with TrainingQueue(self.root / "training.sqlite", max_jobs=3) as queue:
            queue.complete(job["job_id"], job["lease_token"], result)
            self.assertEqual(queue.read_current(job["cell_id"])["result"], result)

    def test_queue_header_and_optimizer_tampering_reject_before_training(self):
        job = self.claim(self.prepare()["submissions"][1])
        for key, value in (("generation", 2), ("feature_identity", "c"*64), ("source_digest", "d"*64)):
            changed = {**job, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                train_persisted_job(self.root, changed)
        changed = copy.deepcopy(job)
        changed["payload"]["steps"] = 21
        changed["source_digest"] = hashlib.sha256(canonical(changed["payload"])).hexdigest()
        with self.assertRaises(ValueError):
            train_persisted_job(self.root, changed)
        self.assertEqual(list((self.root / "artifacts").iterdir()), [])
        with TrainingQueue(self.root / "training.sqlite", max_jobs=3) as queue:
            self.assertIsNone(queue.read_current(job["cell_id"]))

    def test_input_and_initial_parameter_bytes_cannot_change_under_saved_pins(self):
        job = self.claim(self.prepare()["submissions"][2])
        for path in (self.root / "inputs.npz", self.root / "initial/residual/weights.npz",
                     self.root / "initial/residual/manifest.json"):
            original = path.read_bytes()
            path.write_bytes(original+b"changed")
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                train_persisted_job(self.root, job)
            path.write_bytes(original)
        self.assertEqual(list((self.root / "artifacts").iterdir()), [])

    def test_source_rows_and_symlink_ancestors_are_bound(self):
        job = self.claim(self.prepare()["submissions"][0])
        for relative in ("C:escape.npz", "../escape.npz", "initial\\linear\\weights.npz"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                owned_path(self.root, relative)
        source = self.root / "sources.json"
        original = source.read_bytes()
        source.write_bytes(original+b" ")
        with self.assertRaises(ValueError):
            load_job_inputs(self.root, job)
        source.write_bytes(original)
        initial = self.root / "initial"
        initial.rename(self.root / "initial-real")
        initial.symlink_to("initial-real", target_is_directory=True)
        with self.assertRaises(ValueError):
            load_job_inputs(self.root, job)

    def test_hostile_numpy_header_is_rejected_before_array_allocation(self):
        job = self.claim(self.prepare()["submissions"][0])
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(header,
            {"descr": "<f4", "fortran_order": False, "shape": (2**60, 770)})
        labels = io.BytesIO()
        np.save(labels, self.y, allow_pickle=False)
        archive = self.root / "inputs.npz"
        with zipfile.ZipFile(archive, "w") as packed:
            packed.writestr("features.npy", header.getvalue())
            packed.writestr("labels.npy", labels.getvalue())
        changed = copy.deepcopy(job)
        changed["payload"]["inputs"]["sha256"] = sha_file(archive)
        changed["source_digest"] = hashlib.sha256(canonical(changed["payload"])).hexdigest()
        with self.assertRaisesRegex(ValueError, "shape, layout or dtype"):
            load_job_inputs(self.root, changed)

    def hostile_head(self, directory):
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(header,
            {"descr": "<f8", "fortran_order": False, "shape": (2**60, 2)})
        bias = io.BytesIO()
        np.save(bias, np.zeros(2), allow_pickle=False)
        weights = directory / "weights.npz"
        with zipfile.ZipFile(weights, "w") as packed:
            packed.writestr("W.npy", header.getvalue())
            packed.writestr("b.npy", bias.getvalue())
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["weights_sha256"] = sha_file(weights)
        manifest_path.write_bytes(canonical(manifest)+b"\n")
        return sha_file(manifest_path)

    def test_initial_head_header_rejects_before_legacy_head_loader(self):
        job = self.claim(self.prepare()["submissions"][0])
        job["payload"]["initial_manifest_sha256"] = self.hostile_head(self.root / "initial/linear")
        job["source_digest"] = hashlib.sha256(canonical(job["payload"])).hexdigest()
        with patch("cell_action_training_queue.NumpyCellHead.load",
                   side_effect=AssertionError("legacy loader reached before preflight")):
            with self.assertRaisesRegex(ValueError, "before allocation"):
                load_job_inputs(self.root, job)

    def test_published_head_header_rejects_before_legacy_head_loader(self):
        submissions = self.prepare()["submissions"]
        with TrainingQueue(self.root / "training.sqlite", max_jobs=3) as queue:
            for submission in submissions:
                queue.submit(**submission)
                job = queue.claim(lease_ns=30_000_000_000)
                result = train_persisted_job(self.root, job)
                queue.complete(job["job_id"], job["lease_token"], result)
            publication = queue.read_current("runtime-training-linear")
            result = publication["result"]
            result["manifest_sha256"] = self.hostile_head(self.root / result["artifact"])
            raw = canonical(result)
            digest = hashlib.sha256(raw).hexdigest()
            queue.db.execute("UPDATE publication SET result=?,result_sha256=? WHERE cell_id=?",
                             (raw, digest, "runtime-training-linear"))
        original = NumpyCellHead.load
        def load(path, identity):
            if Path(path) == self.root / result["artifact"]:
                raise AssertionError("published legacy loader reached before header check")
            return original(path, identity)
        with patch("cell_action_training_queue.NumpyCellHead.load", side_effect=load):
            with self.assertRaisesRegex(ValueError, "before allocation"):
                verify_queue_publications(self.root)

    def test_published_task_initial_state_and_authority_must_match_job(self):
        submissions = self.prepare()["submissions"]
        with TrainingQueue(self.root / "training.sqlite", max_jobs=3) as queue:
            for submission in submissions:
                queue.submit(**submission)
                job = queue.claim(lease_ns=30_000_000_000)
                result = train_persisted_job(self.root, job)
                queue.complete(job["job_id"], job["lease_token"], result)
            original = queue.read_current("runtime-training-linear")["result"]
            for key, value in (("task_id", "different_task"), ("initial_tensor_sha256", "0"*64),
                               ("authority", "ALLOW"), ("quality_qualified", True)):
                raw = canonical({**original, key: value})
                digest = hashlib.sha256(raw).hexdigest()
                queue.db.execute("UPDATE publication SET result=?,result_sha256=? WHERE cell_id=?",
                                 (raw, digest, "runtime-training-linear"))
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "bindings"):
                    verify_queue_publications(self.root)

    def test_synthetic_probe_trains_three_modes_and_reopens_in_fresh_process(self):
        def prepare_bundle(_bundle, output, *, expected_manifest_sha256, deadline_ns):
            self.assertEqual(expected_manifest_sha256, BUNDLE)
            return self.prepare(output, deadline_ns=deadline_ns)
        with patch("probe_action_training_queue.prepare_training_jobs", side_effect=prepare_bundle), \
                patch("probe_action_training_queue.load_training_inputs", return_value=(self.meta, self.x, self.y, self.rows)):
            result = run_probe("synthetic-fixture", self.root, expected_manifest_sha256=BUNDLE)
        recovered = result["fresh_process_recovery"]["result"]["verified_publications"]
        self.assertEqual(sorted(row["mode"] for row in recovered), sorted(MODES))
        self.assertTrue(all(row["logits_bitwise_equal"] for row in recovered))
        self.assertEqual((result["training_jobs"], result["logical_tasks"], result["actual_optimizer_updates"],
                          result["unique_training_source_groups"], result["learning_quality_measured"]),
                         (3, 1, 60, 32, False))
        fence = result["lease_generation_control"]
        self.assertEqual((fence["reclaimed_attempt"], fence["late_worker_rejected"],
                          fence["stale_generation_hidden"], fence["old_generation_rejected"],
                          fence["optimizer_updates"]), (2, True, True, True, 0))
        self.assertEqual(result["queue"]["queue_costs_open"]["jobs_by_status"], {"done": 3})
        recovery = result["queue"]["real_job_recovery"]
        self.assertTrue(recovery["same_job_reclaimed"])
        self.assertTrue(recovery["old_token_rejected"])
        self.assertEqual((recovery["abandoned_attempt_optimizer_updates"], recovery["replacement_optimizer_updates"]), (0, 20))
        self.assertEqual(result["queue"]["attempts_by_cell"],
                         {"runtime-training-linear": 2, "runtime-training-gated": 1, "runtime-training-residual": 1})
        old = recovery["abandoned_worker"]["result"]["claimed_job"]
        new = recovery["replacement_worker"]["result"]
        self.assertEqual((old["job_id"], new["job_id"]), (old["job_id"], old["job_id"]))
        self.assertGreaterEqual(new["claim_call_started_unix_ns"], old["lease_until_ns"])
        self.assertLess(new["completed_unix_ns"], new["deadline_unix_ns"])
        self.assertTrue(result["source_code_unchanged"])
        self.assertTrue(result["original_bundle_reverified_after_training"])
        self.assertGreater(result["persisted_file_bytes_before_report"], 0)
        self.assertGreater(result["memory"]["parent_process_lifetime_peak_rss_bytes"], 0)
        self.assertGreater(result["fresh_process_recovery"]["result"]["process_lifetime_peak_rss_bytes_at_receipt"], 0)


if __name__ == "__main__":
    unittest.main()
