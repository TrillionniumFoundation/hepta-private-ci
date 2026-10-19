"""Small synthetic census tests; do not certify actual task quality."""

import math
import unittest
from stem_strict_residual_opportunity import (
    audit_rank_opportunity,
    ARMS,
    STAGES,
    PHASES,
    SOURCE,
)


def fixture(threshold=15.0):
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES})
    plan = dict(
        source_commit=SOURCE,
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
        questions=questions,
        arms=ARMS,
        curriculum_attempted_examples=STAGES,
    )
    raw = []
    summary = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                key = f"{stage}/{phase}/{arm}"
                summary[key] = dict(
                    observed_pre_reader_decisions=8,
                    changed_top1_count=0,
                    joint_direction_can_flip_count=0 if arm == "frozen_rerank" else 8,
                    joint_direction_cannot_flip_count=8
                    if arm == "frozen_rerank"
                    else 0,
                )
            for i, qid in enumerate(questions[phase]):
                for arm in ARMS:
                    geo = dict(
                        schema="hepta.stem-selection-geometry.v2",
                        selected_index=0,
                        candidate_count=2,
                        has_ranking_competition=True,
                        baseline_top_id="B",
                        changed_selected_candidate=False,
                        residual_scaling_is_not_a_validated_policy=True,
                        label_free=True,
                        frozen_top1_gap=10.0,
                        joint_flip_scale_infimum=None
                        if arm == "frozen_rerank"
                        else threshold,
                    )
                    raw.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            status="succeeded",
                            selected=0,
                            pool_digest="candidate-seal-" + qid,
                            cell="general" if i % 2 == 0 else "temporal",
                            family="family-" + qid,
                            selection_geometry=geo,
                        )
                    )
    return plan, raw, dict(selection_geometry=summary)


class StrictResidualTests(unittest.TestCase):
    def test_full_576_receipts_and_64_grid_cannot_mean_source_gain(self):
        report = audit_rank_opportunity(*fixture())
        self.assertEqual(len(report["groups"]), 60)
        z = report["groups"]["48/test/gated"]
        self.assertEqual(z["actual_source_selection_changes"], 0)
        self.assertEqual(z["possible_flip_at_or_below_grid"]["16.0"], 8)
        self.assertEqual(z["strict_flip_potential_within_grid"]["16.0"], 8)
        self.assertFalse(report["production_accepted"])
        self.assertTrue(z["winner_could_be_wrong_even_after_flip"])

    def test_infimum_tie_keeps_strict_and_weak_bounds_distinct(self):
        r = audit_rank_opportunity(*fixture(threshold=16.0))
        z = r["groups"]["48/test/gated"]
        self.assertEqual(z["strict_flip_potential_within_grid"]["16.0"], 0)
        self.assertEqual(z["possible_flip_at_or_below_grid"]["16.0"], 8)
        self.assertEqual(z["strict_flip_potential_within_grid"]["32.0"], 8)

    def test_wrong_direction_cannot_prove_rerank_capacity(self):
        p, raw, report = fixture()
        for row in raw:
            if row["arm"] != "frozen_rerank":
                row["selection_geometry"]["joint_flip_scale_infimum"] = None
        for k, v in report["selection_geometry"].items():
            if not k.endswith("/frozen_rerank"):
                v["joint_direction_can_flip_count"] = 0
                v["joint_direction_cannot_flip_count"] = 8
        z = audit_rank_opportunity(p, raw, report)["groups"]["48/test/gated"]
        self.assertEqual(z["wrong_or_uniform_residual_directions"], 8)
        self.assertEqual(z["strict_flip_potential_within_grid"]["64.0"], 0)

    def test_duplicate_missing_status_drift_and_bad_raw_threshold_refuse(self):
        for mode in (
            "dup",
            "missing",
            "failed",
            "nan",
            "negative",
            "changed_top",
            "wrong_pool",
        ):
            p, raw, reports = fixture()
            if mode == "dup":
                raw[-1] = dict(raw[0])
            elif mode == "missing":
                raw.pop()
            elif mode == "failed":
                raw[0]["status"] = "failed"
            elif mode == "nan":
                raw[1]["selection_geometry"]["joint_flip_scale_infimum"] = math.nan
            elif mode == "negative":
                raw[1]["selection_geometry"]["joint_flip_scale_infimum"] = -1
            elif mode == "changed_top":
                raw[1]["selected"] = 1
            else:
                raw[1]["pool_digest"] = "alien-pool"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_rank_opportunity(p, raw, reports)

    def test_unsafe_registration_and_uncertified_source_reject(self):
        for mode in ("source", "question", "arms", "extra"):
            p, r, s = fixture()
            if mode == "source":
                p["source_commit"] = "new-source"
            elif mode == "question":
                p["questions"]["train"] = ["same"] * 48
            elif mode == "arms":
                p["arms"] = ("frozen_rerank",)
            else:
                r[0]["question_id"] = "fake-unknown"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit_rank_opportunity(p, r, s)


if __name__ == "__main__":
    unittest.main()
