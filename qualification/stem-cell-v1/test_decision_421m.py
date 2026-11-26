"""L1 fixture tests for the exact four-model offline decision comparison.

These contain NO genuine 421M model weights or task utility measurements.
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from decision_421m import (SOURCES, PHASES, audit_dataset, build_plan,
                           evaluate, input_fingerprint, load_plan,
                           read_strict_jsonl, write_frozen)
from model_runner import snapshot_digest


class FourWayDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "cases.jsonl"
        self.rows = []
        for day, split in enumerate(("train", "calibration", "held_out",
                                     "future_1", "future_2", "ood"), 1):
            for i in range(8):
                ident = f"{split}-{i}"
                self.rows.append({
                    "sample_id": ident, "source_group": ident, "episode_id": ident,
                    "split": split, "label": i % 2, "language": "en",
                    "scope": "approved-scope", "state": f"state for {ident}",
                    "question": "pick a valid option",
                    "options": ["A", "B"],
                    "event_time": f"2026-01-0{day}T01:00:00Z",
                })
        self.data.write_text("".join(json.dumps(r) + "\n" for r in self.rows))
        self.descriptors = {}
        for key, (source, parameters) in SOURCES.items():
            folder = self.root / key
            folder.mkdir()
            (folder / "config.json").write_text(json.dumps({"model": key}))
            self.descriptors[key] = {
                "source": source, "parameter_count": parameters,
                "upstream_revision": "a" * 40,
                "snapshot_path": str(folder), "sha256": snapshot_digest(folder),
                "license_approved": True, "adapter_reviewed": True,
            }
        self.plan = build_plan(self.data, self.descriptors, train_steps=100,
                               trainable_budget=262144, batch_size=16,
                               context_tokens=512, seed=7347,
                               device="cpu", dtype="fp32")
        self.indexed, _, _ = audit_dataset(self.rows)
        self.runs = []
        self.predictions = []
        for key in SOURCES:
            for phase in PHASES:
                arm = f"{key}:{phase}"
                weights = hashlib.sha256(arm.encode()).hexdigest()
                self.runs.append({
                    "arm": arm,
                    "checkpoint_sha256": self.descriptors[key]["sha256"],
                    "upstream_revision": "a" * 40,
                    "dataset_sha256": self.plan["dataset_sha256"],
                    "training_sample_groups_sha256":
                        self.plan["training_sample_groups_sha256"],
                    "weights_sha256": weights,
                    "seed": 7347, "truncated_input_count": 0,
                    "input_contract": "state_question_all_ordered_options",
                    "runtime_profile": {
                        "device": "cpu", "dtype": "fp32", "batch_size": 16,
                        "context_tokens": 512},
                    "train_steps": 0 if phase == "checkpoint" else 100,
                    "trainable_parameters": 0 if phase == "checkpoint" else 250000,
                    "pretrained_typed_decision_head_present": phase == "checkpoint",
                    "upstream_task_exposure": (
                        "task_specific" if key == "laya_typed" else "unknown"),
                    "optimizer": "adamw" if phase == "equal_budget" else "none",
                    "training_split": "train" if phase == "equal_budget" else "none",
                })
                for row in self.rows:
                    if row["split"] == "train":
                        continue
                    if key == "laya_original":
                        logits = [2., -2.]
                    elif row["label"] == 0:
                        logits = [3., -3.]
                    else:
                        logits = [-3., 3.]
                    self.predictions.append({
                        "arm": arm, "sample_id": row["sample_id"],
                        "input_digest": input_fingerprint(row),
                        "logits": logits, "weights_sha256": weights,
                        "latency_ms": 2.5,
                    })

    def run_report(self):
        return evaluate(self.plan, self.runs, self.predictions, self.indexed,
                        replicates=1000)

    def test_eight_complete_matched_arms_remain_non_authorizing(self):
        result = self.run_report()
        self.assertEqual(len(result["arm_metrics"]), 8)
        self.assertEqual(len(result["paired_future_vs_original_laya"]), 6)
        self.assertFalse(result["production_promotion_permitted"])
        self.assertFalse(result["independent_ndu_signature_verified"])
        self.assertTrue(result["checkpoint_is_not_proven_zero_shot"])
        self.assertEqual(result["arm_metrics"]["laya_original:checkpoint"]
                         ["by_split"]["future_1"]["count"], 8)

    def test_four_model_batch_capacity_must_be_precommitted(self):
        self.assertEqual(self.plan["encoder_microbatch_size"], 1)
        altered = copy.deepcopy(self.runs)
        altered[0]["physical_encoder_microbatch_ceiling"] = 4
        with self.assertRaisesRegex(ValueError, "run provenance"):
            evaluate(self.plan, altered, self.predictions, self.indexed,
                     replicates=1000)
        plan = copy.deepcopy(self.plan)
        plan["encoder_microbatch_size"] = 4
        with self.assertRaisesRegex(ValueError, "run provenance"):
            evaluate(plan, self.runs, self.predictions, self.indexed,
                     replicates=1000)
        # Research-only fixtures may exercise coverage with a matching
        # manifest, but that does not attest that four actual models ran.
        for item in altered:
            item["physical_encoder_microbatch_ceiling"] = 4
        matched = evaluate(plan, altered, self.predictions, self.indexed,
                           replicates=1000)
        self.assertFalse(matched["production_promotion_permitted"])
        with self.assertRaisesRegex(ValueError, "unregistered physical Encoder"):
            build_plan(
                self.data, self.descriptors, train_steps=100,
                trainable_budget=262144, batch_size=16, context_tokens=512,
                seed=7347, device="cpu", dtype="fp32",
                encoder_microbatch_size=33)

    def test_equal_budget_only_is_comparable_without_fake_checkpoint(self):
        runs = [r for r in self.runs if r["arm"].endswith(":equal_budget")]
        predictions = [r for r in self.predictions
                       if r["arm"].endswith(":equal_budget")]
        review = evaluate(self.plan, runs, predictions, self.indexed,
                          comparison_scope="equal_budget", replicates=1000)
        self.assertEqual(len(review["arm_metrics"]), 4)
        self.assertEqual(len(review["paired_future_vs_original_laya"]), 3)
        self.assertFalse(review["full_comparison_present"])
        self.assertEqual(review["comparison_scope"], "equal_budget")
        self.assertEqual(len(review["excluded_checkpoint_arms"]), 4)
        self.assertIn("NOT_COMPARABLE", review["checkpoint_comparison_status"])
        self.assertFalse(review["production_promotion_permitted"])
        with self.assertRaisesRegex(ValueError, "all four equal-budget"):
            evaluate(self.plan, runs[:-1], predictions, self.indexed,
                     comparison_scope="equal_budget", replicates=1000)
        with self.assertRaisesRegex(ValueError, "unknown run arm"):
            evaluate(self.plan, self.runs, self.predictions, self.indexed,
                     comparison_scope="equal_budget", replicates=1000)
        with self.assertRaisesRegex(ValueError, "full four-model"):
            evaluate(self.plan, runs, predictions, self.indexed,
                     comparison_scope="full", replicates=1000)
        with self.assertRaisesRegex(ValueError, "unknown preregistered"):
            evaluate(self.plan, runs, predictions, self.indexed,
                     comparison_scope="invalid", replicates=1000)

    def test_calibration_never_uses_future_labels(self):
        baseline = self.run_report()["arm_metrics"]["deberta_v3_large:checkpoint"]
        altered = copy.deepcopy(self.predictions)
        future = next(r for r in altered if r["arm"] == "deberta_v3_large:checkpoint"
                      and r["sample_id"].startswith("future_"))
        future["logits"] = [-.1, .1]
        after = evaluate(self.plan, self.runs, altered, self.indexed, replicates=1000)
        self.assertEqual(baseline["temperature_calibration_only"],
                         after["arm_metrics"]["deberta_v3_large:checkpoint"]
                         ["temperature_calibration_only"])
        self.assertEqual(baseline["confidence_threshold_calibration_only"],
                         after["arm_metrics"]["deberta_v3_large:checkpoint"]
                         ["confidence_threshold_calibration_only"])

    def test_unpinned_license_and_lineage_fail_closed(self):
        bad = copy.deepcopy(self.descriptors)
        bad["laya_typed"]["license_approved"] = False
        with self.assertRaisesRegex(ValueError, "license"):
            build_plan(self.data, bad, train_steps=100, trainable_budget=262144,
                       batch_size=16, context_tokens=512, seed=7347,
                       device="cpu", dtype="fp32")
        altered = copy.deepcopy(self.runs)
        altered[0]["upstream_revision"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "provenance"):
            evaluate(self.plan, altered, self.predictions, self.indexed, replicates=1000)

    def test_random_new_head_is_not_a_pretrained_zero_shot_baseline(self):
        invalid = copy.deepcopy(self.runs)
        candidate = next(r for r in invalid
                         if r["arm"] == "deberta_v3_large:checkpoint")
        candidate["pretrained_typed_decision_head_present"] = False
        with self.assertRaisesRegex(ValueError, "genuinely pretrained"):
            evaluate(self.plan, invalid, self.predictions, self.indexed,
                     replicates=1000)

    def test_same_id_but_different_option_or_source_input_is_rejected(self):
        changed = copy.deepcopy(self.predictions)
        changed[0]["input_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "input/source/options"):
            evaluate(self.plan, self.runs, changed, self.indexed,
                     replicates=1000)
        row = next(r for r in self.rows if r["sample_id"] == changed[0]["sample_id"])
        altered_row = copy.deepcopy(row)
        altered_row["options"].reverse()
        self.assertNotEqual(input_fingerprint(row), input_fingerprint(altered_row))

    def test_missing_prediction_and_leaked_labels_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            evaluate(self.plan, self.runs, self.predictions[:-1], self.indexed,
                     replicates=1000)
        bad = copy.deepcopy(self.predictions)
        bad[0]["label"] = 0
        with self.assertRaisesRegex(ValueError, "cannot contain labels"):
            evaluate(self.plan, self.runs, bad, self.indexed, replicates=1000)
        bad = copy.deepcopy(self.predictions)
        bad[0]["logits"] = [float("nan"), 0.]
        with self.assertRaisesRegex(ValueError, "invalid aligned"):
            evaluate(self.plan, self.runs, bad, self.indexed, replicates=1000)

    def test_unequal_training_steps_parameters_and_context_fail_closed(self):
        bad = copy.deepcopy(self.runs)
        target = next(r for r in bad if r["arm"] == "modernbert_large:equal_budget")
        target["train_steps"] = 1
        with self.assertRaisesRegex(ValueError, "training budget"):
            evaluate(self.plan, bad, self.predictions, self.indexed, replicates=1000)
        bad = copy.deepcopy(self.runs)
        target = next(r for r in bad if r["arm"] == "modernbert_large:equal_budget")
        target["trainable_parameters"] = 200000
        with self.assertRaisesRegex(ValueError, "differ"):
            evaluate(self.plan, bad, self.predictions, self.indexed, replicates=1000)
        bad = copy.deepcopy(self.runs)
        bad[0]["truncated_input_count"] = 1
        with self.assertRaisesRegex(ValueError, "provenance"):
            evaluate(self.plan, bad, self.predictions, self.indexed, replicates=1000)

    def test_time_and_group_disjointness(self):
        tampered = copy.deepcopy(self.rows)
        next(r for r in tampered if r["split"] == "future_1")["event_time"] = (
            "2025-01-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "chronological"):
            audit_dataset(tampered)
        tampered = copy.deepcopy(self.rows)
        next(r for r in tampered if r["split"] == "future_1")["source_group"] = "train-0"
        with self.assertRaisesRegex(ValueError, "source-group leakage"):
            audit_dataset(tampered)

    def test_duplicate_json_keys_and_blank_evidence_rows_fail_closed(self):
        duplicate = self.root / "duplicate-case.jsonl"
        duplicate.write_text('{"sample_id":"x","label":0,"label":1}\n')
        with self.assertRaisesRegex(ValueError, "invalid/duplicate"):
            list(read_strict_jsonl(duplicate))
        duplicate.write_text('{"sample_id":"x"}\n\n')
        with self.assertRaisesRegex(ValueError, "empty Decision JSONL"):
            list(read_strict_jsonl(duplicate))
        duplicate.write_text('["not", "a", "case"]\n')
        with self.assertRaisesRegex(ValueError, "must be objects"):
            list(read_strict_jsonl(duplicate))

    def test_frozen_plans_reject_tamper_and_overwrite(self):
        path = self.root / "plan.json"
        write_frozen(path, self.plan)
        plan, token = load_plan(path)
        self.assertEqual(plan, self.plan)
        self.assertEqual(len(token), 64)
        with self.assertRaises(FileExistsError):
            write_frozen(path, self.plan)
        changed = json.loads(path.read_text())
        changed["train_steps"] = 1000
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "modified"):
            load_plan(path)


if __name__ == "__main__":
    unittest.main()
