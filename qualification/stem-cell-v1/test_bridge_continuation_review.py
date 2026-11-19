"""Independent continuation qualification mutations; no neural execution."""

import copy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from binding_protocol import build_binding_protocol, score_binding_probabilities
from bridge_continuation_review import (audit_continuation_budget, audit_global_retention,
    audit_natural_diagnostics, audit_retention, review_run)


class BridgeContinuationReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = build_binding_protocol()
        cls.cases = cls.parts["reader_train"]
        cls.probabilities = [.99 if case.label else .01 for case in cls.cases]
        cls.baseline = score_binding_probabilities(cls.cases, cls.probabilities)

    def receipt(self, arm):
        replay = 0 if arm == "natural_only" else 500
        return dict(arm=arm, requested_natural_updates=500, completed_natural_updates=500,
            requested_binding_updates=replay, completed_binding_updates=replay, completed_steps=500,
            status="completed", actual_natural_exposures=8000, actual_binding_exposures=replay * 16,
            actual_total_exposures=8000 + replay * 16, optimizer="Adam_foreach_false", learning_rate=.001,
            depth=3, pair_weight=.5 if arm == "contrastive" else 0., natural_case_identity_verified=True,
            diagnostics=[dict(logical_step=step, optimizer_steps=step * (1 if arm == "natural_only" else 2))
                         for step in range(0, 501, 100)])

    def test_all_arms_preserve_exact_natural_exposure_with_explicit_extra_replay(self):
        plan = dict(updates=500, batch_size=16, logical_update_order=["natural", "binding"])
        reports = [audit_continuation_budget(self.receipt(arm), plan) for arm in ("natural_only", "replay", "contrastive")]
        self.assertEqual([report["natural_exposures"] for report in reports], [8000] * 3)
        self.assertEqual([report["binding_exposures"] for report in reports], [0, 8000, 8000])
        changed = self.receipt("contrastive")
        changed["actual_total_exposures"] = 8000
        with self.assertRaisesRegex(ValueError, "exposure"):
            audit_continuation_budget(changed, plan)

    def test_incomplete_budget_changed_loss_or_unbound_rows_cannot_qualify(self):
        plan = dict(updates=500, batch_size=16, logical_update_order=["natural", "binding"])
        for field, value, message in (("completed_natural_updates", 499, "budget"),
                                      ("pair_weight", .25, "loss changed"),
                                      ("natural_case_identity_verified", False, "row identity")):
            changed = self.receipt("contrastive")
            changed[field] = value
            with self.assertRaisesRegex(ValueError, message):
                audit_continuation_budget(changed, plan)
        changed = self.receipt("replay")
        changed["diagnostics"] = changed["diagnostics"][1:]
        with self.assertRaisesRegex(ValueError, "diagnostics missing"):
            audit_continuation_budget(changed, plan)

    def test_retention_recomputed_from_world_pairs_can_fail_despite_candidate_accuracy(self):
        self.assertTrue(audit_retention(self.baseline, self.baseline)["passed"])
        for wrong_groups, passed in ((3, True), (4, False)):
            probabilities = list(self.probabilities)
            for index in range(wrong_groups):
                probabilities[index * 4] = 1 - probabilities[index * 4]
            measured = score_binding_probabilities(self.cases, probabilities)
            self.assertGreaterEqual(measured["accuracy"], .95)
            self.assertEqual(audit_retention(measured, self.baseline)["passed"], passed)
        bad_reference = dict(self.baseline, both_worlds_correct=.99)
        with self.assertRaisesRegex(ValueError, "reference"):
            audit_retention(self.baseline, bad_reference)

    def test_natural_training_diagnostics_reconstruct_the_first_eight_complete_questions(self):
        natural = [asdict(case) for case in self.parts["internal_tune"]]
        # The generator supplies two candidates per question, so eight complete
        # questions are the first sixteen rows; labels stay outside model args.
        labels = [row["label"] for row in natural[:16]]
        diagnostic = dict(n=16, probabilities=[.99 if label else .01 for label in labels], predictions=labels, accuracy=1.)
        receipt = dict(diagnostics=[dict(logical_step=step, natural=copy.deepcopy(diagnostic)) for step in range(0, 501, 100)])
        report = audit_natural_diagnostics(receipt, natural)
        self.assertEqual(len(report["diagnostics"]), 6)
        changed = copy.deepcopy(receipt)
        changed["diagnostics"][0]["natural"]["probabilities"][0] = .5
        with self.assertRaisesRegex(ValueError, "strict raw probability"):
            audit_natural_diagnostics(changed, natural)

    def test_global_gate_requires_each_seed_and_never_uses_natural_internal_scores(self):
        good = {"41": True, "47": True, "53": True}
        self.assertTrue(audit_global_retention(good, True))
        self.assertFalse(audit_global_retention(dict(good, **{"47": False}), False))
        with self.assertRaisesRegex(ValueError, "three"):
            audit_global_retention({"41": True, "47": True}, True)
        with self.assertRaisesRegex(ValueError, "contradicts"):
            audit_global_retention(dict(good, **{"53": False}), True)

    def test_support_code_without_completed_run_cannot_claim_an_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "no continuation audit was performed"):
                review_run(Path(directory), Path(directory), Path(directory) / "unused.json")


if __name__ == "__main__":
    unittest.main()
