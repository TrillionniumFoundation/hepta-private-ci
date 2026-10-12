"""Actual tiny-Torch native shadow control; NOT benchmark gain evidence."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as Obj
import tempfile
import unittest

import torch

from native import Target
from selector_evaluation import support_indices
from selector_head import Supervision, TrainingCut
from stem_native_pairwise_shadow import (
    native_pairwise_shadow, review_pairwise_shadow,
)
from test_stem_cell import features


PHASES = ("select", "retention", "test", "transfer")


def fixture():
    questions = {"train": [Obj(identity=f"train-{i}") for i in range(48)]}
    questions.update({
        phase: [Obj(identity=f"{phase}-{i}") for i in range(8)]
        for phase in PHASES
    })
    ordered = [q.identity for group in questions.values() for q in group]
    routes = {qid: ("general" if i % 2 == 0 else "temporal")
              for i, qid in enumerate(ordered)}
    encoded = {qid: features(qid) for qid in ordered}
    # Only a previously admitted TRAIN cut supplies weak native positives.
    supervised = tuple(
        Supervision(encoded[f"train-{i}"], (0,))
        for i in range(8)
    )
    cut = TrainingCut(
        frozenset(q.identity for q in questions["train"]),
        frozenset({"family"}), frozenset({"root"}),
        frozenset({"held-out"}), "pinned-train-admission",
    )
    return questions, supervised, encoded, cut, routes


def targets_and_frozen(questions, encoded):
    pools, targets, frozen = {}, {}, {}
    for phase in PHASES:
        for q in questions[phase]:
            qid = q.identity
            # The original frozen scores [0.2,0.5] select index 1;
            # the weak source id at index 0 is only opened AFTER choices.
            pools[qid] = Obj(windows=(
                Obj(source_id="doc-positive"),
                Obj(source_id="doc-distractor"),
            ))
            targets[qid] = Target(
                "target", "fixture", ("doc-positive",), False,
            )
            for stage in (16, 32, 48):
                frozen[(stage, phase, qid)] = dict(
                    status="succeeded", selected=1,
                    pool_digest=encoded[qid].pool_digest,
                )
    return pools, targets, frozen


class NativePairwiseShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def run_fixture(self):
        args = fixture()
        with tempfile.TemporaryDirectory() as d:
            fits, decisions = native_pairwise_shadow(
                *args, Path(d),
            )
            artifacts = sorted(Path(d).glob("shadow-*.json"))
            self.assertEqual(len(artifacts), 12)
            self.assertTrue(all(f.stat().st_size > 0 for f in artifacts))
        return args, fits, decisions

    def test_real_head_updates_and_192_original_label_free_choices(self):
        args, fits, choices = self.run_fixture()
        self.assertEqual(len(fits), 12)
        self.assertEqual(len(choices), 192)
        self.assertTrue(all(f["status"] == "succeeded" for f in fits))
        self.assertTrue(all(f["artifact_reload_matched"] for f in fits))
        self.assertTrue(all(f["receipt"]["null_weights_unchanged"] for f in fits))
        self.assertTrue(all(f["receipt"]["actual_heldout_task_gain_established"] is False
                            for f in fits))
        self.assertEqual(sum(r["status"] == "failed" for r in choices), 0)
        self.assertEqual(sum(r["actual_reader_calls"] for r in choices), 0)
        self.assertGreater(sum(r["selected"] != r["original_frozen_selected"]
                               for r in choices), 0)
        # There are only 8 * 4 new subjects; three stages are repeats.
        pools, targets, base = targets_and_frozen(args[0], args[2])
        report = review_pairwise_shadow(
            args[0], fits, choices, base, pools, targets,
            support_indices=support_indices,
        )
        self.assertEqual(report["total_label_blind_decisions"], 192)
        self.assertEqual(len(report["by_checkpoint_phase_arm"]), 24)
        self.assertEqual(report["observed_reader_calls"], 0)
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["independently_established_generalization"])

    def test_heldout_question_in_training_cut_rejected(self):
        questions, rows, feat, cut, routes = fixture()
        leak = Supervision(feat["test-0"], (0,))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "held-out"):
                native_pairwise_shadow(
                    questions, rows + (leak,), feat, cut, routes, Path(d),
                )
            self.assertFalse(tuple(Path(d).iterdir()))

    def test_missing_encoder_features_or_changed_head_budget_rejected(self):
        for mode in ("missing", "encoder", "budget"):
            questions, rows, feat, cut, routes = fixture()
            opts = {}
            if mode == "missing":
                feat.pop("test-0")
            elif mode == "encoder":
                feat["test-0"] = features("test-0", identity="different")
            else:
                opts["steps"] = 512
            with tempfile.TemporaryDirectory() as d:
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    native_pairwise_shadow(
                        questions, rows, feat, cut, routes, Path(d), **opts,
                    )

    def test_duplicate_shadow_choice_missing_stage_or_tampered_fit_rejected(self):
        args, fits, decisions = self.run_fixture()
        pools, targets, frozen = targets_and_frozen(args[0], args[2])
        for mode in ("duplicate", "missing", "fit"):
            f, rows = deepcopy(fits), deepcopy(decisions)
            if mode == "duplicate":
                rows[0] = dict(rows[1])
            elif mode == "missing":
                rows.pop()
            else:
                f[0]["receipt"]["strictly_train_source_only"] = False
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                review_pairwise_shadow(
                    args[0], f, rows, frozen, pools, targets,
                    support_indices=support_indices,
                )

    def test_native_unanswerable_is_not_counted_as_supported_source(self):
        args, fits, decisions = self.run_fixture()
        pools, targets, frozen = targets_and_frozen(args[0], args[2])
        targets["test-0"] = Target("", "fixture", (), True)
        result = review_pairwise_shadow(
            args[0], fits, decisions, frozen, pools, targets,
            support_indices=support_indices,
        )
        for stage in (16, 32, 48):
            for arm in ("pairwise_linear", "pairwise_gated"):
                report = result["by_checkpoint_phase_arm"][f"{stage}/test/{arm}"]
                self.assertEqual(report["attempted"], 8)
                self.assertEqual(report["source_label_scored"], 7)
                self.assertEqual(report["source_label_unresolved_or_failure"], 1)

    def test_frozen_source_choice_baseline_must_really_match(self):
        args, fits, decisions = self.run_fixture()
        pools, targets, frozen = targets_and_frozen(args[0], args[2])
        frozen[(48, "test", "test-0")]["selected"] = 0
        with self.assertRaisesRegex(ValueError, "original frozen ranker"):
            review_pairwise_shadow(
                args[0], fits, decisions, frozen, pools, targets,
                support_indices=support_indices,
            )


    def test_reader_failure_after_frozen_selection_keeps_source_scoring(self):
        args, fits, choices = self.run_fixture()
        pools, targets, frozen = targets_and_frozen(args[0], args[2])
        frozen[(48, "test", "test-0")]["status"] = "failed"
        outcome = review_pairwise_shadow(
            args[0], fits, choices, frozen, pools, targets,
            support_indices=support_indices,
        )["by_checkpoint_phase_arm"]
        for arm in ("pairwise_linear", "pairwise_gated"):
            observed = outcome[f"48/test/{arm}"]
            self.assertEqual(observed["attempted"], 8)
            self.assertEqual(observed["baseline_reader_failed_with_top1"], 1)
            self.assertEqual(observed["source_selection_pairs_observed"], 8)
            self.assertEqual(observed["source_label_scored"], 8)
            self.assertEqual(observed["source_label_unresolved_or_failure"], 0)
            self.assertTrue(observed["reader_failure_never_erases_pre_read_source_selection"])
            self.assertTrue(observed["shadow_answers_never_generated"])

    def test_failed_before_selection_remains_unknown_not_source_gain(self):
        args, fits, choices = self.run_fixture()
        pools, targets, frozen = targets_and_frozen(args[0], args[2])
        frozen[(48, "test", "test-0")] = dict(status="failed")
        report = review_pairwise_shadow(
            args[0], fits, choices, frozen, pools, targets,
            support_indices=support_indices,
        )["by_checkpoint_phase_arm"]
        for arm in ("pairwise_linear", "pairwise_gated"):
            case = report[f"48/test/{arm}"]
            self.assertEqual(case["attempted"], 8)
            self.assertEqual(case["source_selection_pairs_observed"], 7)
            self.assertEqual(case["frozen_selector_unobserved_or_empty"], 1)
            self.assertEqual(case["source_label_scored"], 7)
            self.assertEqual(case["source_label_unresolved_or_failure"], 1)

    def test_failed_reader_does_not_allow_forged_pool_or_out_of_range_top1(self):
        for tamper in ("changed_pool", "out_of_bounds", "bool_selected"):
            args, fits, choices = self.run_fixture()
            pools, targets, frozen = targets_and_frozen(args[0], args[2])
            base = frozen[(48, "test", "test-0")]
            base["status"] = "failed"
            if tamper == "changed_pool":
                base["pool_digest"] = "unbound-candidates"
            elif tamper == "out_of_bounds":
                base["selected"] = 17
            else:
                base["selected"] = True
            with self.subTest(tamper=tamper), self.assertRaises(ValueError):
                review_pairwise_shadow(
                    args[0], fits, choices, frozen, pools, targets,
                    support_indices=support_indices,
                )


if __name__ == "__main__":
    unittest.main()
