"""CPU learning, split isolation and real tensor-artifact replay regressions."""

from dataclasses import replace
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np
import torch

from cell_head_training import (HeadCohortV1, HeadTrainingConfigV1,
                                HeadTrainingError, load_head_artifact,
                                save_head_artifact, task_metrics, train_cell_head)
from feature_bundle import FeatureBundleV1, FeatureIdentityV1


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


IDENTITY = FeatureIdentityV1(encoder_sha256=digest("frozen-encoder"),
                            checkpoint_revision="1" * 40,
                            preprocess_sha256=digest("preprocess"))


def cohort(name, *, identity=IDENTITY, rows=24):
    generator = torch.Generator().manual_seed(13)
    labels = torch.arange(rows, dtype=torch.int64) % 2
    features = torch.randn((rows, 6), generator=generator) * 0.05
    features[:, 0] = labels.float() * 2 - 1
    features[:, 1] = 1.0
    missing = torch.ones((rows, 5), dtype=torch.bool)
    missing[:, 0] = False
    bundle = FeatureBundleV1.from_tensors(global_features=features,
        source_record_digests=tuple(digest(f"{name}:{i}") for i in range(rows)),
        identity=identity, missing_mask=missing)
    return HeadCohortV1(bundle, labels, tuple(f"{name}-story-{i}" for i in range(rows)))


def repack_artifact(path, mutation):
    """Re-sign adversarial tensor bytes so tests reach the structural boundary."""
    with zipfile.ZipFile(path / "weights.npz") as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    mutation(entries)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    weights = stream.getvalue()
    (path / "weights.npz").write_bytes(weights)
    manifest = json.loads((path / "manifest.json").read_bytes())
    manifest["weights_file_sha256"] = hashlib.sha256(weights).hexdigest()
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    (path / "manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class CellHeadTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        cls.train = cohort("train")
        cls.cal = cohort("calibration")
        cls.holdouts = {name: cohort(name) for name in ("future_1", "future_2", "ood")}
        cls.config = HeadTrainingConfigV1(task_count=2, steps=60, learning_rate=0.3,
                                         adapter_rank=2, seed=17)
        cls.trained = train_cell_head(cls.train, cls.cal, cls.holdouts, config=cls.config)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def test_actual_task_learning_and_private_parameter_changes(self):
        report = self.trained.report
        self.assertNotEqual(report["initial_tensor_sha256"], report["trained_tensor_sha256"])
        self.assertEqual(report["optimizer_steps"], 60)
        self.assertEqual(report["encoder_training_steps"], 0)
        self.assertLess(report["last_train_loss_before_step"], report["initial_train_loss"])
        self.assertTrue(any(n.startswith("gate.") for n in report["changed_parameter_names"]))
        self.assertTrue(any(n.startswith("up.") for n in report["changed_parameter_names"]))
        for name in self.holdouts:
            self.assertEqual(report["splits"][name]["metrics"]["trained"]["accuracy"], 1.0)
        self.assertFalse(report["production_activation_allowed"])
        self.assertEqual(report["value_head_status"], "untrained")
        self.assertEqual(report["uncertainty_head_status"], "untrained_not_calibrated")

    def test_linear_control_starts_identically_and_updates_only_classifier(self):
        linear = train_cell_head(self.train, self.cal, self.holdouts,
                                 config=replace(self.config, mode="linear"))
        report = linear.report
        self.assertEqual(report["initial_tensor_sha256"], self.trained.report["initial_tensor_sha256"])
        self.assertTrue(all(n.startswith("task_head.") for n in report["changed_parameter_names"]))
        self.assertLess(report["trainable_parameter_count"], self.trained.report["trainable_parameter_count"])

    def test_holdout_labels_cannot_change_weights_or_temperature(self):
        changed = {name: replace(c, labels=1 - c.labels) for name, c in self.holdouts.items()}
        second = train_cell_head(self.train, self.cal, changed, config=self.config)
        self.assertEqual(second.report["trained_tensor_sha256"], self.trained.report["trained_tensor_sha256"])
        self.assertEqual(second.report["temperature"], self.trained.report["temperature"])
        self.assertEqual(second.report["splits"]["future_1"]["metrics"]["trained"]["accuracy"], 0.0)

    def test_calibration_labels_do_not_update_weights(self):
        changed = replace(self.cal, labels=1 - self.cal.labels)
        second = train_cell_head(self.train, changed, self.holdouts, config=self.config)
        self.assertEqual(second.report["trained_tensor_sha256"], self.trained.report["trained_tensor_sha256"])
        self.assertNotEqual(second.report["temperature"], self.trained.report["temperature"])

    def test_row_and_group_leakage_fail_before_training(self):
        with self.assertRaisesRegex(HeadTrainingError, "leakage"):
            train_cell_head(self.train, self.train, self.holdouts, config=self.config)
        bad = replace(self.cal, source_group_ids=self.train.source_group_ids)
        with self.assertRaisesRegex(HeadTrainingError, "leakage"):
            train_cell_head(self.train, bad, self.holdouts, config=self.config)

    def test_foreign_encoder_preprocess_scope_and_generation_rejected(self):
        identities = (replace(IDENTITY, encoder_sha256=digest("other")),
                      replace(IDENTITY, preprocess_sha256=digest("other")),
                      replace(IDENTITY, scope_id="different-scope"),
                      replace(IDENTITY, generation=2))
        for identity in identities:
            with self.subTest(identity=identity), self.assertRaises(HeadTrainingError):
                self.trained.predict_task(cohort("foreign", identity=identity).bundle)
        with self.assertRaisesRegex(HeadTrainingError, "identities"):
            train_cell_head(self.train, cohort("cal", identity=identities[0]),
                            self.holdouts, config=self.config)

    def test_bundle_and_caller_rng_are_unchanged_by_training(self):
        original = self.train.bundle.read_global()
        caller_rng = torch.random.get_rng_state().clone()
        train_cell_head(self.train, self.cal, self.holdouts, config=self.config)
        self.assertTrue(torch.equal(caller_rng, torch.random.get_rng_state()))
        self.assertTrue(torch.equal(original, self.train.bundle.read_global()))
        predictions = self.trained.predict_task(self.train.bundle)["task_probabilities"]
        predictions.zero_()
        self.assertTrue(bool((self.trained.predict_task(self.train.bundle)["task_probabilities"] > 0).all()))

    def test_actual_serialized_tensor_reload_prediction_parity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "head"
            receipt = save_head_artifact(self.trained, path)
            loaded = load_head_artifact(path,
                expected_manifest_sha256=receipt["manifest_sha256"], expected_identity=IDENTITY)
            original = self.trained.predict_task(self.holdouts["future_1"].bundle)
            restored = loaded.predict_task(self.holdouts["future_1"].bundle)
            self.assertTrue(torch.equal(original["task_probabilities"], restored["task_probabilities"]))
            self.assertTrue(torch.equal(original["task_logits"], restored["task_logits"]))
            self.assertEqual(original["temperature"], restored["temperature"])
            self.assertEqual(loaded.report, self.trained.report)
            with self.assertRaises(FileExistsError):
                save_head_artifact(self.trained, path)

    def test_retained_digest_and_weight_byte_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "head"
            receipt = save_head_artifact(self.trained, path)
            with self.assertRaisesRegex(HeadTrainingError, "manifest"):
                load_head_artifact(path, expected_manifest_sha256="0" * 64,
                                   expected_identity=IDENTITY)
            weights = bytearray((path / "weights.npz").read_bytes())
            weights[-1] ^= 1
            (path / "weights.npz").write_bytes(weights)
            with self.assertRaisesRegex(HeadTrainingError, "weights"):
                load_head_artifact(path, expected_manifest_sha256=receipt["manifest_sha256"],
                                   expected_identity=IDENTITY)

    def test_huge_array_declarations_rejected_before_numpy_allocation(self):
        for version, writer in (((1, 0), np.lib.format.write_array_header_1_0),
                                ((2, 0), np.lib.format.write_array_header_2_0)):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "head"
                save_head_artifact(self.trained, path)
                stream = io.BytesIO()
                writer(stream, {"descr": "<f4", "fortran_order": False, "shape": (2**40,)})
                digest = repack_artifact(path, lambda entries:
                    entries.__setitem__("task_head.weight.npy", stream.getvalue()))
                with mock.patch("cell_head_training.np.load", side_effect=AssertionError("array allocation reached")):
                    with self.assertRaisesRegex(HeadTrainingError, "header"):
                        load_head_artifact(path, expected_manifest_sha256=digest, expected_identity=IDENTITY)

    def test_invalid_tensor_headers_and_payload_lengths_rejected_before_loading(self):
        array = self.trained._head.state_dict()["task_head.weight"].numpy()
        header = {"descr": np.lib.format.dtype_to_descr(array.dtype),
                  "fortran_order": False, "shape": array.shape}
        cases = []
        for update in ({"descr": "|O"}, {"descr": "<f8"}, {"fortran_order": True}):
            stream = io.BytesIO()
            np.lib.format.write_array_header_1_0(stream, header | update)
            cases.append(stream.getvalue() + array.tobytes())
        stream = io.BytesIO()
        np.lib.format.write_array_header_1_0(stream, header)
        valid = stream.getvalue() + array.tobytes()
        cases.extend((valid[:-1], valid + b"extra", b"\x93NUMPY\x02\x00" + (2**32 - 1).to_bytes(4, "little")))
        for index, payload in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "head"
                save_head_artifact(self.trained, path)
                digest = repack_artifact(path, lambda entries:
                    entries.__setitem__("task_head.weight.npy", payload))
                with mock.patch("cell_head_training.np.load", side_effect=AssertionError("array allocation reached")):
                    with self.assertRaisesRegex(HeadTrainingError, "header"):
                        load_head_artifact(path, expected_manifest_sha256=digest, expected_identity=IDENTITY)

    def test_exact_tensor_member_names_checked_before_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "head"
            save_head_artifact(self.trained, path)
            digest = repack_artifact(path, lambda entries:
                entries.__setitem__("foreign.npy", entries.pop("task_head.weight.npy")))
            with mock.patch("cell_head_training.np.load", side_effect=AssertionError("array allocation reached")):
                with self.assertRaisesRegex(HeadTrainingError, "archive"):
                    load_head_artifact(path, expected_manifest_sha256=digest, expected_identity=IDENTITY)

    def test_corrupt_bundle_bytes_cannot_be_trained_or_predicted(self):
        broken = cohort("broken")
        broken.bundle._tensors["global_features"].add_(1.0)
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            train_cell_head(broken, self.cal, self.holdouts, config=self.config)
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            self.trained.predict_task(broken.bundle)

    def test_multiple_bundles_keep_ordered_source_rows(self):
        first, second = cohort("train-a", rows=12), cohort("train-b", rows=12)
        combined = HeadCohortV1((first.bundle, second.bundle),
            torch.cat((first.labels, second.labels)), first.source_group_ids + second.source_group_ids)
        result = train_cell_head(combined, self.cal, self.holdouts, config=self.config)
        self.assertEqual(result.report["splits"]["train"]["source_record_digests"],
                         list(first.bundle.source_record_digests + second.bundle.source_record_digests))

    def test_metrics_known_probabilities_and_no_coverage(self):
        metrics = task_metrics(torch.tensor([[math.log(0.8), math.log(0.2)],
                                            [math.log(0.6), math.log(0.4)]]),
                               torch.tensor([0, 1]), confidence_threshold=0.9)
        self.assertAlmostEqual(metrics["accuracy"], 0.5)
        self.assertAlmostEqual(metrics["brier_multiclass_sum"], 0.4, places=6)
        self.assertEqual(metrics["coverage"], 0.0)
        self.assertIsNone(metrics["selective_accuracy"])

    def test_global_optimizer_hook_cannot_mutate_foreign_parameter(self):
        from torch.optim.optimizer import register_optimizer_step_pre_hook
        foreign = torch.tensor(1.0)
        handle = register_optimizer_step_pre_hook(lambda *_: foreign.add_(7))
        try:
            with self.assertRaisesRegex(ValueError, "global"):
                train_cell_head(self.train, self.cal, self.holdouts, config=self.config)
            self.assertEqual(float(foreign), 1.0)
        finally:
            handle.remove()

    def test_invalid_label_and_training_budget_rejected(self):
        with self.assertRaises(HeadTrainingError):
            train_cell_head(replace(self.train, labels=self.train.labels.float()), self.cal,
                            self.holdouts, config=self.config)
        with self.assertRaises(HeadTrainingError):
            train_cell_head(self.train, self.cal, self.holdouts,
                            config=replace(self.config, learning_rate=float("nan")))

if __name__ == "__main__":
    unittest.main()
