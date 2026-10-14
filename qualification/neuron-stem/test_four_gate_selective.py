"""Known-answer/unknown-input distinction and compatible calibration regressions."""
from copy import deepcopy
import unittest

from four_gate_common import digest
from four_gate_selective import ARMS, DETECTORS, KINDS, _metrics, review_selective
from test_four_gate_fixtures import plan_fixture


def selective_fixture():
    plan = plan_fixture()
    plan["assessment_time"] = "2026-10-10T00:00:00Z"
    plan["learning"]["selective"] = {"calibration_reject_fraction": .05,
        "max_accepted_error": .05, "min_answerable_coverage": .8,
        "max_unknown_acceptance": .05, "max_benign_rejection": .05,
        "selected_detector": "feature_support"}
    cell = str(("scope", "cell"))
    trial = {"revision": "a" * 40, "initial_head_digests": {cell: digest("frozen")},
             "final_head_digests": {cell: digest("trained")}}
    owner = ("b" * 40, digest("nochange"), 1)
    ev = {"schema": "hepta.four-gate.selective.v1", "trial_sha256": digest(trial),
          "objective_sha256": plan["objective_sha256"],
          "calibration_sealed_at": "2026-09-05T00:00:00Z",
          "detectors": {d: {"artifact_sha256": digest(d), "training_data_sha256": digest("same data"),
                             "fit_completed_at": "2026-09-05T00:00:00Z"} for d in DETECTORS},
          "calibration": [], "evaluation": []}
    for split in ("calibration", "evaluation"):
        kinds = ("in_domain",) if split == "calibration" else KINDS
        for kind in kinds:
            for group in range(4):
                unknown = kind in ("unknown_task", "missing_evidence")
                cid = f"{split}-{kind}-{group}"
                event = "2026-08-20T00:00:00Z" if split == "calibration" else "2026-09-06T00:00:00Z"
                predicted = "2026-09-04T00:00:00Z" if split == "calibration" else event
                row = {"case_id": cid, "scope_id": "scope", "cell_id": "cell",
                    "source_cluster": f"{split}-{group}", "input_sha256": digest(cid),
                    "kind": kind, "answerable": not unknown, "label": None if unknown else 0,
                    "event_time": event, "outcome_observed_at": event,
                    "observer_id": "fixture observer", "outcome_receipt_sha256": digest([cid, "outcome"]),
                    "predictions": {}}
                for arm in ARMS:
                    row["predictions"][arm] = {"probabilities": [.95, .05],
                        "weights_digest": owner[1] if arm == "no_change" else trial[
                            "initial_head_digests" if arm == "frozen" else "final_head_digests"][cell],
                        "model_revision": owner[0] if arm == "no_change" else trial["revision"],
                        "generation": 1, "predicted_at": predicted, "producer_id": "fixture predictor",
                        "detector_bundle_sha256": digest(ev["detectors"]),
                        "scores": {d: (.95 if d == "confidence" else .1 if unknown else .9) for d in DETECTORS}}
                ev[split].append(row)
    return plan, ev, trial, owner


class SelectiveTests(unittest.TestCase):
    def test_acceptance_is_not_error(self):
        values = _metrics([(True, True, True, False)] * 20)
        self.assertEqual(values["accepted_error"], 0)
        self.assertEqual(values["answerable_coverage"], 1)
        self.assertEqual(values["benign_rejection"], 0)
        self.assertIsNone(values["unknown_acceptance"])

    def test_reject_all_has_no_defined_accepted_error(self):
        value = _metrics([(True, True, False, False)])
        self.assertIsNone(value["accepted_error"])
        self.assertEqual(value["answerable_coverage"], 0)

    def test_labeled_support_detector_pass_does_not_hide_confidence_failure(self):
        plan, ev, trial, owner = selective_fixture()
        report = review_selective(plan, ev, trial=trial, nochange_identity=owner)
        self.assertEqual(report["status"], "diagnostic_pass")
        self.assertFalse(report["metrics"]["detector_passes"]["confidence"])
        self.assertTrue(report["metrics"]["detector_passes"]["feature_support"])
        self.assertFalse(report["production_promotion_permitted"])

    def test_same_initial_and_final_head_cannot_be_substituted(self):
        plan, ev, trial, owner = selective_fixture()
        ev["calibration"][0]["predictions"]["trained"]["weights_digest"] = digest("frozen")
        with self.assertRaisesRegex(ValueError, "Head identity drift"):
            review_selective(plan, ev, trial=trial, nochange_identity=owner)

    def test_unsupported_ood_does_not_get_a_fake_label(self):
        plan, ev, trial, owner = selective_fixture()
        next(r for r in ev["evaluation"] if r["kind"] == "unknown_task")["label"] = 0
        with self.assertRaisesRegex(ValueError, "invented unknown"):
            review_selective(plan, ev, trial=trial, nochange_identity=owner)

    def test_substituted_detector_score_artifact_rejected(self):
        plan, ev, trial, owner = selective_fixture()
        ev["evaluation"][0]["predictions"]["trained"]["detector_bundle_sha256"] = digest("substitution")
        with self.assertRaisesRegex(ValueError, "detector artifacts"):
            review_selective(plan, ev, trial=trial, nochange_identity=owner)

    def test_future_calibration_rejected(self):
        plan, ev, trial, owner = selective_fixture()
        ev["calibration"][0]["predictions"]["trained"]["predicted_at"] = "2026-10-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "after seal"):
            review_selective(plan, ev, trial=trial, nochange_identity=owner)

    def test_duplicate_input_does_not_create_source_independence(self):
        plan, ev, trial, owner = selective_fixture()
        ev["evaluation"][1]["input_sha256"] = ev["evaluation"][0]["input_sha256"]
        with self.assertRaisesRegex(ValueError, "independent selective"):
            review_selective(plan, ev, trial=trial, nochange_identity=owner)

    def test_answering_wrong_is_detected_separately_from_shift(self):
        plan, ev, trial, owner = selective_fixture()
        for row in ev["evaluation"]:
            if row["answerable"]:
                row["label"] = 1
        report = review_selective(plan, ev, trial=trial, nochange_identity=owner)
        self.assertEqual(report["status"], "not_passed")
        self.assertEqual(report["metrics"]["profiles"]["trained:feature_support"]["accepted_error"]["estimate"], 1)


if __name__ == "__main__":
    unittest.main()
