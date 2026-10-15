"""Pre-registered tiny learned evidence gate; archived model calls are NOT new."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import system2_cell_support_gate as trial

FIXTURES = {
    "train_lexical": os.environ.get(
        "HEPTA_GATE_TRAIN_320", "/mnt/data/hepta-qwen-320-lexical-factorial.zip"
    ),
    "train_label": os.environ.get(
        "HEPTA_GATE_TRAIN_180", "/mnt/data/hepta-qwen-180-tag-label-order.zip"
    ),
    "eval_placebo": os.environ.get(
        "HEPTA_GATE_EVAL_200", "/mnt/data/hepta-qwen-200-equal-token-labels.zip"
    ),
}
SHA = "d01d8f4fc9b1efce72346260b254fd66f24dabfa"


class TinyCellSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(Path(p).exists() for p in FIXTURES.values()):
            if os.environ.get("HEPTA_CELL_GATE_REQUIRED") == "1":
                raise RuntimeError(
                    "CI-required externally pinned original Qwen archives absent"
                )
            raise unittest.SkipTest(
                "exact externally pinned archives not staged for source-only tests"
            )
        cls.snapshots, cls.training, cls.eval_rows = trial.prepare(FIXTURES)

    def test_historical_source_sha_manifest_and_reader_are_all_verified(self):
        self.assertEqual(
            {k: x["files"] for k, x in self.snapshots.items()},
            {"train_lexical": 20, "train_label": 19, "eval_placebo": 21},
        )
        self.assertEqual((len(self.training), len(self.eval_rows)), (180, 200))
        self.assertEqual(len({r["qid"] for r in self.training}), 40)
        self.assertEqual(len({r["qid"] for r in self.eval_rows}), 20)
        self.assertFalse(
            {r["qid"] for r in self.training} & {r["qid"] for r in self.eval_rows}
        )

    def test_same_question_and_source_features_ignore_gold_outputs_and_labels(self):
        source = next(
            x
            for x in self.eval_rows
            if x["arm"] == "target_decoy_first" and x["view"] == "e_label"
        )
        target = trial.feature(source)
        altered = source | dict(
            target="TAG-FAKEABC",
            reader_answer="TAG-0000000",
            arm="no_evidence",
            view="neutral_alias",
            reader_cost_ns=0,
        )
        self.assertEqual(trial.feature(altered), target)
        row = next(
            x
            for x in self.eval_rows
            if x["arm"] == source["arm"]
            and x["view"] == "neutral_alias"
            and x["qid"] == source["qid"]
        )
        self.assertEqual(trial.feature(row), target)
        row = next(
            x
            for x in self.eval_rows
            if x["arm"] == source["arm"]
            and x["view"] == "unlabeled"
            and x["qid"] == source["qid"]
        )
        self.assertEqual(trial.feature(row), target)

    def test_six_parameter_head_freeze_and_shuffled_control_are_deterministic(self):
        a, b = trial.fit(self.training), trial.fit(self.training)
        shuffled = trial.fit(self.training, shuffled=True)
        self.assertEqual(a["weights"], b["weights"])
        self.assertNotEqual(a["weights"], shuffled["weights"])
        self.assertEqual(a["parameters"], 6)
        self.assertEqual(a["optimizer_updates"], 240)
        self.assertEqual(a["train_subjects"], 40)

    def test_frozen_rule_and_learned_head_choose_same_actions_on_new_subjects(self):
        model = trial.fit(self.training)
        for row in self.eval_rows:
            learned, _ = trial.decision(row, model)
            self.assertEqual(learned, trial.frozen_matcher(row))
            self.assertEqual(learned, row["support"])

    def test_no_model_new_inference_and_original_200_answer_census_is_preserved(self):
        with tempfile.TemporaryDirectory() as path:
            target = Path(path) / "study"
            result = trial.run(FIXTURES, target, source_commit=SHA)
            self.assertEqual(
                (
                    result["train_contexts"],
                    result["eval_contexts"],
                    result["event_count"],
                ),
                (180, 200, 1000),
            )
            self.assertEqual(result["actual_new_inference_calls"], 0)
            self.assertEqual(result["actual_inference_cpu_saved"], 0)
            self.assertFalse(result["learned_exceeds_frozen_in_safe_correct_total"])
            per = {x["head"]: x for x in result["arms"]}
            self.assertEqual(per["learned_head"]["correct_total"], 121)
            self.assertEqual(per["frozen_exact_match"]["correct_total"], 121)
            self.assertEqual(per["always_call"]["correct_total"], 61)
            self.assertEqual(per["never_call"]["correct_total"], 80)
            self.assertEqual(per["learned_head"]["would_call_reader"], 120)
            self.assertEqual(per["shuffled_labels"]["correct_total"], 61)
            self.assertFalse(result["production_accepted"])
            raw = (target / "sealed-actions.jsonl").read_bytes()
            seal = json.loads((target / "prediction-seal.json").read_text())
            self.assertEqual(
                seal,
                {
                    "rows": 1000,
                    "scoring_started": False,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
            )
            self.assertNotIn(b"TAG-", raw)
            self.assertEqual(len(result["conditions"]), 50)

    def test_source_mismatch_detected_even_if_outer_zip_is_pinned_by_attacker(self):
        row = self.snapshots["eval_placebo"]["rows"][0]
        cases = trial.cohort(trial.PINS["eval_placebo"]["indices"])
        with self.assertRaisesRegex(ValueError, "provenance"):
            tampered = copy.deepcopy(row)
            tampered["reader"]["delivered_evidence"][0]["excerpt"] = (
                "falsified provenance"
            )
            trial.validated_row(tampered, kind="eval_placebo", cases=cases)

    def test_bogus_answer_does_not_change_predicted_cell_action(self):
        model = trial.fit(self.training)
        positive = copy.deepcopy(next(x for x in self.eval_rows if x["support"]))
        negative = copy.deepcopy(next(x for x in self.eval_rows if not x["support"]))
        a = trial.decision(positive, model)
        b = trial.decision(negative, model)
        self.assertTrue(a[0])
        self.assertFalse(b[0])
        positive["reader_answer"] = "E1"
        negative["reader_answer"] = "TAG-FAKEABC"
        self.assertEqual(a, trial.decision(positive, model))
        self.assertEqual(b, trial.decision(negative, model))

    def test_failed_head_attempt_is_not_free_or_marked_success(self):
        with tempfile.TemporaryDirectory() as path:
            out = Path(path) / "fail"
            with patch.object(trial, "prepare", side_effect=RuntimeError("injected")):
                with self.assertRaises(RuntimeError):
                    trial.run(FIXTURES, out, source_commit=SHA)
            status = json.loads((out / "failure.json").read_text())
            self.assertTrue(status["missing_work_not_imputed"])
            self.assertFalse((out / "summary.json").exists())

    def test_train_only_gold_mutation_does_not_change_head_weights(self):
        baseline = trial.fit(self.training)["weights"]
        masked = [
            r | {"target": "TAG-FAKEABC", "reader_answer": "fake"}
            for r in self.training
        ]
        self.assertEqual(baseline, trial.fit(masked)["weights"])

    def test_external_archive_pin_is_mandatory(self):
        pin = trial.PINS["train_lexical"]
        with tempfile.TemporaryDirectory() as p:
            path = Path(p) / "bad.zip"
            shutil.copyfile(FIXTURES["train_lexical"], path)
            with path.open("ab") as f:
                f.write(b"altered after sealed model inference")
            with self.assertRaisesRegex(ValueError, "external SHA"):
                trial.archive(path, pin)

    def test_required_sources_correctly_detected_with_exact_public_question_device(
        self,
    ):
        positives = [
            r
            for r in self.eval_rows
            if r["arm"] in ("target_decoy_first", "target_decoy_last")
        ]
        negatives = [
            r for r in self.eval_rows if r["arm"] in ("decoy_only", "no_evidence")
        ]
        self.assertEqual((len(positives), len(negatives)), (120, 80))
        self.assertTrue(all(trial.frozen_matcher(r) for r in positives))
        self.assertTrue(all(not trial.frozen_matcher(r) for r in negatives))
        self.assertTrue(
            all(trial.feature(r)[1] == float(r["support"]) for r in self.eval_rows)
        )

    def test_replaying_incomplete_predictions_rejects_missing_planned_arm(self):
        head = {"learned_head": trial.fit(self.training)}
        rows = [
            dict(
                qid=r["qid"],
                arm=r["arm"],
                view=r["view"],
                head="learned_head",
                call_reader=True,
            )
            for r in self.eval_rows
        ]
        with self.assertRaisesRegex(ValueError, "missing a scheduled"):
            trial.summarize(rows[:-1], self.eval_rows, head)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            trial.summarize(rows[:1] + rows[:1] + rows[2:], self.eval_rows, head)

    def test_invalid_source_commit_rejected_before_any_output_written(self):
        with tempfile.TemporaryDirectory() as p:
            out = Path(p) / "out"
            with self.assertRaisesRegex(ValueError, "commit"):
                trial.run(FIXTURES, out, source_commit="not-a-commit")
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
