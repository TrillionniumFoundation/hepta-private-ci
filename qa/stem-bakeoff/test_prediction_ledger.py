"""Prediction math, pair-block inference, provenance and safe artifact tests."""

from dataclasses import asdict, replace
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from prediction_ledger import (LedgerIdentityV1, PredictionLedgerV1,
    ResearchQualificationV1, assess_multimodal_research, assess_research_qualification,
    average_precision, binomial_risk_upper, canonical, cluster_intervals,
    load_prediction_ledger, paired_intervention_summary, save_prediction_ledger, sha)

PLAN = {"schema": "fixture-preregistered-plan", "research_qualification": asdict(ResearchQualificationV1())}
IDENTITY = LedgerIdentityV1("a" * 64, "b" * 64, "c" * 64, "d" * 64, sha(canonical(PLAN)))


def ledger(*, rows=256, probabilities=None, labels=None, **overrides):
    labels = np.arange(rows, dtype=np.int64) % 2 if labels is None else np.asarray(labels)
    if probabilities is None:
        probabilities = np.where(labels == 1, 0.95, 0.05)
    probs = np.stack((1 - np.asarray(probabilities), probabilities), axis=1)
    args = {"logits": np.log(probs), "labels": labels,
        "source_ids": [f"row-{i}" for i in range(rows)],
        "image_group_ids": [f"image-{i // 2}" for i in range(rows)],
        "pair_block_ids": [f"block-{i // 4:04}" for i in range(rows)],
        "identity": IDENTITY, "split": "test", "arm": "joint_gated"}
    return PredictionLedgerV1.from_logits(**{**args, **overrides})


class PredictionLedgerTests(unittest.TestCase):
    def test_known_confusion_probabilities_calibration_and_selective_risk(self):
        item = ledger(rows=4, labels=[0, 1, 1, 0], probabilities=[0.2, 0.6, 0.4, 0.9])
        metrics = item.metrics()
        self.assertEqual(metrics["confusion_tn_fp_fn_tp"], [1, 1, 1, 1])
        for key in ("accuracy", "balanced_accuracy", "positive_recall", "coverage", "selective_risk"):
            self.assertEqual(metrics[key], 0.5)
        self.assertAlmostEqual(metrics["nll"], -np.log([.8, .6, .4, .1]).mean())
        self.assertAlmostEqual(metrics["brier_multiclass_sum"], .685)
        self.assertAlmostEqual(metrics["ece10_equal_width"], .325)
        self.assertEqual(metrics["accepted_count"], 2)

    def test_average_precision_keeps_ties_together(self):
        labels, scores = np.array([1, 1, 0, 0]), np.array([.9, .8, .8, .1])
        self.assertAlmostEqual(average_precision(labels, scores), 5 / 6)
        self.assertEqual(average_precision(labels[[0, 2, 1, 3]], scores), average_precision(labels, scores))
        self.assertEqual(average_precision(labels, np.ones(4)), 0.5)
        self.assertIsNone(average_precision(np.zeros(4, dtype=int), scores))

    def test_no_accepted_rows_are_not_zero_risk_or_a_pass(self):
        item = ledger(probabilities=np.where(np.arange(256) % 2, .6, .4))
        self.assertIsNone(item.metrics()["selective_risk"])
        result = assess_research_qualification(item, PLAN)
        self.assertEqual(result["status"], "INSUFFICIENT")
        self.assertEqual(result["cluster_intervals"]["bounds"]["selective_risk"]["upper_one_sided_95"], 1.0)

    def test_majority_prediction_cannot_pass_positive_recall_screen(self):
        item = ledger(probabilities=np.full(256, .1))
        result = assess_research_qualification(item, PLAN)
        self.assertEqual(item.metrics()["majority_accuracy"], .5)
        self.assertEqual(item.metrics()["positive_recall"], 0)
        self.assertEqual(result["status"], "FAIL_RESEARCH_SCREEN")
        self.assertFalse(result["checks"]["positive_recall"])

    def test_one_class_does_not_acquire_balanced_accuracy_or_multimodal_status(self):
        item = ledger(labels=np.ones(256, dtype=int))
        self.assertIsNone(item.metrics()["balanced_accuracy"])
        paired = paired_intervention_summary(item, item)
        self.assertIsNone(paired["paired_deltas"]["balanced_accuracy"]["lower_one_sided_95"])
        result = assess_multimodal_research(item,
            unimodal={name: item for name in ("text_only", "image_only")},
            interventions={name: item for name in ("shuffled_image", "missing_image", "missing_text")}, plan=PLAN)
        self.assertEqual(result["status"], "INSUFFICIENT")
        self.assertFalse(result["production_activation_allowed"])

    def test_perfect_arm_remains_research_only_and_group_budget_is_real(self):
        result = assess_research_qualification(ledger(), PLAN)
        self.assertEqual(result["status"], "PASS_RESEARCH_SCREEN")
        self.assertFalse(result["production_activation_allowed"])
        self.assertFalse(result["multimodal_gain_qualified"])
        fewer = ledger(pair_block_ids=[f"block-{i // 8}" for i in range(256)])
        self.assertEqual(assess_research_qualification(fewer, PLAN)["status"], "INSUFFICIENT")

    def test_cluster_resampling_respects_block_correlation_and_is_reproducible(self):
        labels = np.arange(256) % 2
        # Every row in each of 16 blocks fails; the other 48 blocks are correct.
        predictions = np.where(np.arange(256) // 4 < 16, 1 - labels, labels)
        item = ledger(probabilities=np.where(predictions, .95, .05))
        one, two = cluster_intervals(item), cluster_intervals(item)
        self.assertEqual(one, two)
        self.assertEqual(one["replicates"], 2000)
        self.assertGreater(one["bounds"]["selective_risk"]["upper_one_sided_95"], .30)
        self.assertFalse(one["distribution_free_guarantee"])

    def test_paired_resampling_preserves_zero_delta_and_reorders_by_source(self):
        first = ledger()
        rows = first.rows()[::-1]
        second = PredictionLedgerV1.from_logits(logits=[r["logits"] for r in rows],
            labels=[r["label"] for r in rows], source_ids=[r["source_id"] for r in rows],
            image_group_ids=[r["image_group_id"] for r in rows], pair_block_ids=[r["pair_block_id"] for r in rows],
            identity=IDENTITY, split="test", arm="joint_gated", intervention="missing_text")
        result = paired_intervention_summary(first, second)
        self.assertEqual(result["paired_deltas"]["balanced_accuracy"],
                         {"reference_minus_comparison": 0., "lower_one_sided_95": 0., "upper_one_sided_95": 0.})
        self.assertEqual(result["both_correct"], 256)

    def test_paired_comparisons_reject_changed_labels_groups_identity_or_head(self):
        first = ledger()
        changed = (ledger(labels=1 - np.arange(256) % 2),
            ledger(image_group_ids=[f"other-{i // 2}" for i in range(256)]),
            ledger(identity=replace(IDENTITY, data_sha256="e" * 64)),
            ledger(identity=replace(IDENTITY, head_sha256="e" * 64)))
        for other in changed:
            with self.assertRaises(ValueError):
                paired_intervention_summary(first, other)
        self.assertEqual(paired_intervention_summary(first, changed[-1], comparison_kind="head")["paired_rows"], 256)

    def test_multimodal_screen_needs_joint_gain_and_fixed_head_sensitivities(self):
        joint = ledger()
        unimodal = {name: ledger(probabilities=np.full(256, .1), arm=name,
                    identity=replace(IDENTITY, head_sha256=letter * 64))
                    for name, letter in (("text_only", "e"), ("image_only", "f"))}
        interventions = {name: ledger(probabilities=np.full(256, .1), intervention=name)
                        for name in ("shuffled_image", "missing_image", "missing_text")}
        result = assess_multimodal_research(joint, unimodal=unimodal, interventions=interventions, plan=PLAN)
        self.assertEqual(result["status"], "PASS_RESEARCH_SCREEN")
        self.assertEqual(result["gain_vs_best_unimodal"], .5)
        self.assertFalse(result["production_activation_allowed"])
        self.assertTrue(result["shuffled_original_labels_are_sensitivity_only"])
        unimodal["text_only"] = ledger(arm="text_only", identity=replace(IDENTITY, head_sha256="e" * 64))
        rejected = assess_multimodal_research(joint, unimodal=unimodal, interventions=interventions, plan=PLAN)
        self.assertFalse(rejected["checks"]["gain_vs_best_unimodal"])

    def test_plan_hash_prevents_retroactive_threshold_change_and_test_misuse(self):
        changed = json.loads(canonical(PLAN))
        changed["research_qualification"]["min_coverage"] = 0.0
        with self.assertRaisesRegex(ValueError, "prior plan SHA"):
            assess_research_qualification(ledger(), changed)
        for split in ("train", "dev", "calibration"):
            with self.assertRaises(ValueError):
                assess_research_qualification(ledger(split=split), PLAN)
        with self.assertRaises(ValueError):
            ledger(confidence_threshold=.5)

    def test_source_ids_and_pair_blocks_reject_ambiguous_or_crossed_groups(self):
        with self.assertRaises(ValueError):
            ledger(source_ids=["same"] * 256)
        with self.assertRaisesRegex(ValueError, "crosses"):
            ledger(pair_block_ids=[f"block-{i}" for i in range(256)])
        with self.assertRaises(ValueError):
            ledger(logits=np.full((256, 2), np.nan))

    def test_rows_and_original_tensors_cannot_mutate_owned_evidence(self):
        logits = np.tile([1., -1.], (256, 1))
        item = ledger(logits=logits)
        before = item.ledger_sha256
        logits.fill(0)
        rows = item.rows()
        rows[0]["logits"][0] = 999
        rows[0]["identity"]["head_sha256"] = "0" * 64
        item.verify()
        self.assertEqual(item.ledger_sha256, before)
        item._arrays["logits"].setflags(write=True)
        item._arrays["logits"][0, 0] = 0
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            item.metrics()

    def test_exact_binomial_bound_is_diagnostic_and_known_tail_correct(self):
        self.assertIsNone(binomial_risk_upper(0, 0))
        self.assertEqual(binomial_risk_upper(10, 10), 1)
        self.assertAlmostEqual(binomial_risk_upper(0, 1), .95)
        bound = binomial_risk_upper(1, 10)
        self.assertAlmostEqual((1 - bound) ** 10 + 10 * bound * (1 - bound) ** 9, .05, places=12)

    def test_npz_reload_is_exact_and_external_hash_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "ledger"
            item = ledger()
            receipt = save_prediction_ledger(item, directory)
            loaded = load_prediction_ledger(directory, expected_manifest_sha256=receipt["manifest_sha256"], expected_identity=IDENTITY)
            self.assertEqual(loaded.rows(), item.rows())
            self.assertEqual(loaded.metrics(), item.metrics())
            with self.assertRaises(FileExistsError):
                save_prediction_ledger(item, directory)
            with self.assertRaises(ValueError):
                load_prediction_ledger(directory, expected_manifest_sha256="0" * 64, expected_identity=IDENTITY)
            raw = bytearray((directory / "predictions.npz").read_bytes())
            raw[-1] ^= 1
            (directory / "predictions.npz").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "tensor bytes"):
                load_prediction_ledger(directory, expected_manifest_sha256=receipt["manifest_sha256"], expected_identity=IDENTITY)

    def test_rehashed_forged_predictions_are_rejected_by_recomputation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "ledger"
            item = ledger()
            save_prediction_ledger(item, directory)
            arrays = {k: v.copy() for k, v in item._arrays.items()}
            arrays["accepted"][:] = False
            np.savez(directory / "predictions.npz", **arrays)
            manifest = json.loads((directory / "manifest.json").read_text())
            manifest["arrays_sha256"] = sha((directory / "predictions.npz").read_bytes())
            raw = canonical(manifest)
            (directory / "manifest.json").write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "derived probabilities"):
                load_prediction_ledger(directory, expected_manifest_sha256=sha(raw), expected_identity=IDENTITY)

    def test_oversized_npy_header_fails_before_numpy_allocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "ledger"
            save_prediction_ledger(ledger(), directory)
            original = (directory / "predictions.npz").read_bytes()
            replacement = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(replacement, "w") as target:
                for name in source.namelist():
                    if name == "logits.npy":
                        header = io.BytesIO()
                        np.lib.format.write_array_header_1_0(header, {"descr": "<f8", "fortran_order": False, "shape": (10**12, 2)})
                        target.writestr(name, header.getvalue())
                    else:
                        target.writestr(name, source.read(name))
            (directory / "predictions.npz").write_bytes(replacement.getvalue())
            manifest = json.loads((directory / "manifest.json").read_text())
            manifest["arrays_sha256"] = sha(replacement.getvalue())
            raw = canonical(manifest)
            (directory / "manifest.json").write_bytes(raw)
            with patch("prediction_ledger.np.load", side_effect=AssertionError("allocation reached")):
                with self.assertRaisesRegex(ValueError, "NPY tensor header"):
                    load_prediction_ledger(directory, expected_manifest_sha256=sha(raw), expected_identity=IDENTITY)


if __name__ == "__main__":
    unittest.main()
