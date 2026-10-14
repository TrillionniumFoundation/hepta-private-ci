"""Exercise the REAL existing prequential verifier, not a fabricated PASS report."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from four_gate_common import canonical, digest
from four_gate_review import review_learning, review_all
from four_gate_controls import V2, DEPTHS
from test_four_gate_controls import validation_fixture
from test_four_gate_selective import selective_fixture
from test_four_gate_fixtures import plan_fixture
import test_prequential_threeway as existing


class ExistingLearningBridgeTests(unittest.TestCase):
    def setUp(self):
        self.old = existing.PrequentialThreeWayTests()
        self.old.setUp()
        self.plan = plan_fixture()
        self.plan.update(preregistered_at="2025-12-01T00:00:00Z",
                         selection_cutoff="2026-01-03T23:59:59Z")
        self.plan["windows"] = {"future_1": ["2026-01-04T00:00:00Z", "2026-01-04T23:59:59Z"],
                                "future_2": ["2026-01-05T00:00:00Z", "2026-01-05T23:59:59Z"]}
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def evidence_refs(self):
        originals = {"dataset": b"".join(canonical(r) + b"\n" for r in self.old.rows),
                     "trial": canonical(self.old.trial), "prelabel_journal": self.old.journal,
                     "no_change": b"".join(canonical(r) + b"\n" for r in self.old.nochange),
                     "ood_receipts": b"".join(canonical(r) + b"\n" for r in self.old.synthetic_threeway_ood_receipts())}
        refs = {}
        for name, raw in originals.items():
            (Path(self.root.name) / name).write_bytes(raw)
            refs[name] = {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}
        return refs

    def test_existing_threeway_plus_raw_ood_is_recomputed(self):
        report = review_learning(self.plan, self.evidence_refs(), self.root.name)
        self.assertEqual(report["status"], "diagnostic_pass")
        self.assertEqual(len(report["metrics"]["family_adjusted_comparisons"]), 10)
        self.assertFalse(report["production_promotion_permitted"])

    def test_v2_labelled_sidecar_uses_the_original_trial_verifier(self):
        selective_plan, sidecar, _, _ = selective_fixture()
        self.plan["schema"] = V2
        self.plan["learning"]["selective"] = selective_plan["learning"]["selective"]
        sidecar["trial_sha256"] = digest(self.old.trial)
        sidecar["calibration_sealed_at"] = "2026-01-06T00:00:00Z"
        for detector in sidecar["detectors"].values():
            detector["fit_completed_at"] = "2026-01-06T00:00:00Z"
        owner = self.old.nochange[0]
        for split in ("calibration", "evaluation"):
            for row in sidecar[split]:
                row["scope_id"], row["cell_id"] = "S", "cell-A"
                row["event_time"] = "2026-01-02T00:00:00Z" if split == "calibration" else "2026-01-07T00:00:00Z"
                row["outcome_observed_at"] = "2026-01-07T00:00:00Z"
                for arm, pred in row["predictions"].items():
                    pred["weights_digest"] = owner["weights_digest"] if arm == "no_change" else self.old.trial[
                        "initial_head_digests" if arm == "frozen" else "final_head_digests"][str(("S", "cell-A"))]
                    pred["model_revision"] = owner["model_revision"] if arm == "no_change" else self.old.trial["revision"]
                    pred["predicted_at"] = "2026-01-06T00:00:00Z" if split == "calibration" else row["event_time"]
                    pred["detector_bundle_sha256"] = digest(sidecar["detectors"])
        refs = self.evidence_refs()
        raw = canonical(sidecar)
        (Path(self.root.name) / "selective").write_bytes(raw)
        refs["selective"] = {"path": "selective", "sha256": hashlib.sha256(raw).hexdigest()}
        report = review_learning(self.plan, refs, self.root.name)
        self.assertEqual(report["status"], "diagnostic_pass")
        self.assertIsNotNone(report["metrics"]["labelled_selective_review"])
        for gate in ("reasoning", "ndu"):
            self.plan[gate].update(validation_sha256=digest(validation_fixture(self.plan)),
                validation_depths=list(DEPTHS), selection_cost_weights={})
        self.plan["reasoning"]["exact_algorithm_applicable"] = True
        bundle = {"schema": "hepta.four-gate.evidence-bundle.v1", "plan_sha256": digest(self.plan),
                  "evidence": {"compute": None, "learning": refs, "reasoning": None, "ndu": None}}
        complete = review_all(self.plan, bundle, self.root.name)
        self.assertEqual(complete["gates"]["learning"]["status"], "diagnostic_pass")
        self.assertFalse(complete["current_acceptance_profile_passed"])
        self.assertFalse(complete["production_promotion_permitted"])

    def test_v2_missing_labelled_sidecar_is_not_replaced_by_old_pass(self):
        self.plan["schema"] = V2
        with self.assertRaisesRegex(ValueError, "all original"):
            review_learning(self.plan, self.evidence_refs(), self.root.name)

    def test_success_flag_cannot_hide_broken_head_lineage(self):
        self.old.trial["temporal_receipts"][-1]["preupdate_head_digest"] = digest("forged head")
        self.old.trial["quality_three_way_precheck_passed"] = True
        with self.assertRaises(ValueError):
            review_learning(self.plan, self.evidence_refs(), self.root.name)

    def test_omitted_nochange_is_not_a_learning_claim(self):
        self.old.nochange.pop()
        with self.assertRaises(ValueError):
            review_learning(self.plan, self.evidence_refs(), self.root.name)

    def test_unobserved_calendar_data_cannot_pass(self):
        self.plan["assessment_time"] = "2026-01-04T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "unobserved"):
            review_learning(self.plan, self.evidence_refs(), self.root.name)


if __name__ == "__main__":
    unittest.main()
