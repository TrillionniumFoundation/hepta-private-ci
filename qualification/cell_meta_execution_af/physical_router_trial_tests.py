"""Real CPU SGD + independently replayed numeric, lineage and negative tests.

Intentionally excluded from stdlib A-F shadow `test_*.py` workflow: Torch is required.
"""

from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qualification.cell_meta_execution_af import physical_router_audit as auditor
from qualification.cell_meta_execution_af import physical_router_trial as trial


class PhysicalRouterTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.conditional = trial.synthetic_panel(seed=41, rule="conditional")
        cls.stable = trial.synthetic_panel(seed=41, rule="stable")
        cls.conditional_result = trial.run(cls.conditional)
        cls.stable_result = trial.run(cls.stable)

    def test_actual_cpu_numeric_replay_conditional(self):
        self.assertEqual(auditor.validate(self.conditional, self.conditional_result)["outcome"],
                         "NUMERIC_REPLAY_ONLY")

    def test_actual_cpu_numeric_replay_stable(self):
        self.assertFalse(auditor.validate(self.stable, self.stable_result)["production_selection_authorized"])

    def test_conditional_task_triggers_train_only_split(self):
        arms = {x["arm"]: x for x in self.conditional_result["results"]}
        self.assertFalse(arms["no_change"]["split_proposed"])
        self.assertTrue(arms["adaptive_split"]["split_proposed"])
        self.assertEqual(arms["adaptive_split"]["weights_sha256"],
                         arms["learned_router"]["weights_sha256"])

    def test_stable_task_prevents_unnecessary_split(self):
        arms = {x["arm"]: x for x in self.stable_result["results"]}
        self.assertFalse(arms["adaptive_split"]["split_proposed"])
        self.assertEqual(arms["adaptive_split"]["predictions"], arms["no_change"]["predictions"])
        self.assertLess(arms["adaptive_split"]["meters"]["head_forward_rows"],
                        arms["fixed_router"]["meters"]["head_forward_rows"])

    def test_split_is_not_declared_a_superiority_result(self):
        self.assertEqual(self.conditional_result["production_admission"], "BLOCKED")
        self.assertFalse(self.conditional_result["statistical_winner_certified"])
        arms = {x["arm"]: x for x in self.conditional_result["results"]}
        # In this real Torch toy panel the stronger fixed router actually wins.
        self.assertGreater(arms["fixed_router"]["evaluation"]["future_1"]["accuracy"],
                           arms["adaptive_split"]["evaluation"]["future_1"]["accuracy"])

    def test_all_arms_same_tensor_slots_and_train_exposure(self):
        records = self.conditional_result["results"]
        self.assertEqual({x["parameter_slots"] for x in records}, {15})
        self.assertEqual({x["meters"]["sample_exposures"] for x in records}, {6912})
        self.assertEqual({x["meters"]["optimizer_steps"] for x in records}, {48})
        self.assertFalse(self.conditional_result["total_compute_matched"])

    def test_future_labels_cannot_change_trained_weights_or_preseal_predictions(self):
        altered = copy.deepcopy(self.conditional)
        for part in trial.EVAL_PARTITIONS:
            for row in altered["partitions"][part]:
                row["label"] = 1 - row["label"]
        p0 = trial.train_arm(self.conditional, "adaptive_split", steps=8)
        p1 = trial.train_arm(altered, "adaptive_split", steps=8)
        self.assertEqual((p0["weights_sha256"], p0["prediction_sha256"], p0["split_proposed"]),
                         (p1["weights_sha256"], p1["prediction_sha256"], p1["split_proposed"]))
        self.assertNotEqual(trial.score_sealed(self.conditional, p0), trial.score_sealed(altered, p1))

    def test_train_label_change_affects_physical_weights(self):
        altered = copy.deepcopy(self.conditional)
        for row in altered["partitions"]["new_train"]:
            row["label"] = 1 - row["label"]
        p0 = trial.train_arm(self.conditional, "adaptive_split", steps=8)
        p1 = trial.train_arm(altered, "adaptive_split", steps=8)
        self.assertNotEqual(p0["weights_sha256"], p1["weights_sha256"])

    def test_repeat_seed_exact_weight_and_prediction_replay(self):
        p0 = trial.train_arm(self.conditional, "adaptive_split", steps=8)
        p1 = trial.train_arm(self.conditional, "adaptive_split", steps=8)
        self.assertEqual((p0["weights_fp32"], p0["predictions"]),
                         (p1["weights_fp32"], p1["predictions"]))

    def test_duplicate_source_group_rejected(self):
        altered = copy.deepcopy(self.conditional)
        altered["partitions"]["future_1"][0]["source_group"] = (
            altered["partitions"]["old_train"][0]["source_group"])
        with self.assertRaises(trial.InvalidPanel):
            trial.validate(altered)

    def test_future_row_already_in_old_train_rejected(self):
        altered = copy.deepcopy(self.conditional)
        altered["partitions"]["future_1"][0]["id"] = altered["partitions"]["old_train"][0]["id"]
        with self.assertRaises(trial.InvalidPanel):
            trial.validate(altered)

    def test_wrong_time_causality_rejected(self):
        altered = copy.deepcopy(self.conditional)
        altered["partitions"]["future_1"][0]["step"] = 0
        with self.assertRaises(trial.InvalidPanel):
            trial.validate(altered)

    def test_missing_cohort_blocks_without_training(self):
        altered = copy.deepcopy(self.conditional)
        del altered["partitions"]["old_retention"]
        with self.assertRaises(trial.InvalidPanel):
            trial.run(altered)

    def test_future_only_invalid_label_rejected(self):
        altered = copy.deepcopy(self.conditional)
        altered["partitions"]["future_2"][0]["label"] = 2
        with self.assertRaises(trial.InvalidPanel):
            trial.validate(altered)

    def test_nan_and_bool_features_blocked(self):
        for bad in (float("nan"), float("inf"), True, "1.0"):
            with self.subTest(bad=bad):
                altered = copy.deepcopy(self.conditional)
                altered["partitions"]["ood"][0]["features"][0] = bad
                with self.assertRaises(trial.InvalidPanel):
                    trial.validate(altered)

    def test_tampered_prediction_and_hash_rejected(self):
        altered = copy.deepcopy(self.conditional_result)
        item = altered["results"][2]
        item["predictions"]["future_1"][0]["probability"] = 0.9
        item["prediction_sha256"] = trial.digest(item["predictions"])
        with self.assertRaisesRegex(auditor.AuditError, "do not reproduce"):
            auditor.validate(self.conditional, altered)

    def test_tampered_final_weight_bytes_rejected(self):
        altered = copy.deepcopy(self.conditional_result)
        altered["results"][2]["weights_fp32"]["gate"]["data_le_hex"] = "00" * 20
        with self.assertRaises(auditor.AuditError):
            auditor.validate(self.conditional, altered)

    def test_fake_score_rejected(self):
        altered = copy.deepcopy(self.conditional_result)
        altered["results"][0]["evaluation"]["future_1"]["accuracy"] = 1.0
        with self.assertRaisesRegex(auditor.AuditError, "scoring"):
            auditor.validate(self.conditional, altered)

    def test_fake_split_decision_rejected(self):
        altered = copy.deepcopy(self.stable_result)
        altered["results"][3]["split_proposed"] = True
        with self.assertRaisesRegex(auditor.AuditError, "split selection"):
            auditor.validate(self.stable, altered)

    def test_fake_forward_meter_rejected(self):
        altered = copy.deepcopy(self.conditional_result)
        altered["results"][3]["meters"]["head_forward_rows"] = 1
        with self.assertRaisesRegex(auditor.AuditError, "head forward"):
            auditor.validate(self.conditional, altered)

    def test_false_independence_or_prod_promotion_rejected(self):
        for mutation in ({"independent_outcome_verified": True},
                         {"statistical_winner_certified": True},
                         {"authority_posture": "ALLOW"},
                         {"production_admission": "ACCEPTED"}):
            with self.subTest(mutation=mutation):
                altered = copy.deepcopy(self.conditional_result)
                altered.update(mutation)
                with self.assertRaises(auditor.AuditError):
                    auditor.validate(self.conditional, altered)

    def test_wrong_source_panel_rejected(self):
        with self.assertRaisesRegex(auditor.AuditError, "source panel drift"):
            auditor.validate(self.stable, self.conditional_result)

    def test_read_rejects_duplicate_json_keys_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "panel.json"
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
                path.write_bytes(raw)
                with self.assertRaises((trial.InvalidPanel, ValueError)):
                    trial.read_panel(path)

    def test_read_rejects_symlink_and_fifo(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            real = root / "real.json"
            real.write_text("{}")
            link = root / "link.json"
            link.symlink_to(real)
            with self.assertRaises((OSError, trial.InvalidPanel)):
                trial.read_panel(link)
            if hasattr(os, "mkfifo"):
                fifo = root / "a.fifo"
                os.mkfifo(fifo)
                with self.assertRaises(trial.InvalidPanel):
                    trial.read_panel(fifo)

    def test_source_reader_real_canonical(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "panel.json"
            path.write_bytes(trial.canonical(self.conditional))
            self.assertEqual(trial.read_panel(path), self.conditional)

    def test_report_create_only_no_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "blocked.json"
            out.write_text("keep")
            script = Path(trial.__file__)
            run = subprocess.run([sys.executable, str(script), "--synthetic-rule", "stable",
                                  "--seed", "41", "--steps", "2", "--out", str(out)],
                                 capture_output=True, text=True, timeout=40, check=False)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(out.read_text(), "keep")

    def test_auditor_is_numpy_torch_free(self):
        source = Path(auditor.__file__).read_text()
        self.assertNotIn("import torch", source)
        self.assertNotIn("import numpy", source)
        self.assertNotIn("physical_router_trial import", source)


if __name__ == "__main__":
    unittest.main()
