"""Fail-closed synthetic rank directions; no pretrained model task claims."""

from copy import deepcopy
import unittest

from stem_audit_archive import AuditError
from stem_pinned_rank_direction import (
    ARMS,
    PHASES,
    STAGES,
    audit_rank_direction,
)


def registered():
    questions = {"train": [f"train-{i}" for i in range(48)]}
    questions.update({phase: [f"{phase}-{i}" for i in range(8)] for phase in PHASES})
    qids = [qid for group in questions.values() for qid in group]
    plan = dict(
        arms=list(ARMS),
        curriculum_attempted_examples=list(STAGES),
        cells=["general", "temporal"],
        questions=questions,
        question_families={q: "family-" + q for q in qids},
        routes={
            q: ("general" if int(q.rsplit("-", 1)[1]) % 2 == 0 else "temporal")
            for q in qids
        },
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
    )
    raw, summary = [], {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                gs = []
                for i, qid in enumerate(questions[phase]):
                    changed = arm != "frozen_rerank" and i == 2
                    scale = (
                        0.5
                        if changed
                        else 2.0
                        if arm != "frozen_rerank" and i == 0
                        else None
                    )
                    g = dict(
                        schema="hepta.stem-selection-geometry.v2",
                        candidate_count=8,
                        has_ranking_competition=True,
                        forced_top1=False,
                        empty_pool=False,
                        encoder_adapted=arm
                        in ("lineage_lora_gated", "independent_lora_gated"),
                        baseline_top_id="A",
                        encoder_only_top_id="A",
                        learned_top_id="B" if changed else "A",
                        selected_index=1 if changed else 0,
                        changed_selected_candidate=changed,
                        encoder_only_changed_selected_candidate=False,
                        head_changed_selected_candidate=changed,
                        joint_flip_scale_infimum=scale,
                        encoder_only_flip_scale_infimum=None,
                        head_conditional_flip_scale_infimum=scale,
                        residual_scaling_is_not_a_validated_policy=True,
                        frozen_top1_gap=6.0,
                        max_abs_score_delta=4.0 if changed else 2.0,
                        gap_exceeds_twice_max_residual=False,
                        raw_scores_sha256="d" * 64,
                        evidence_entailment_evaluated=False,
                        no_answer_policy_calibrated=False,
                        label_free=True,
                    )
                    gs.append(g)
                    raw.append(
                        dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            cell=plan["routes"][qid],
                            family=plan["question_families"][qid],
                            status="succeeded",
                            selected=g["selected_index"],
                            selection_geometry=g,
                        )
                    )
                summary[f"{stage}/{phase}/{arm}"] = dict(
                    observed_pre_reader_decisions=8,
                    competing_pools=8,
                    changed_top1_count=sum(g["changed_selected_candidate"] for g in gs),
                    joint_direction_can_flip_count=sum(
                        g["joint_flip_scale_infimum"] is not None for g in gs
                    ),
                    joint_direction_cannot_flip_count=sum(
                        g["joint_flip_scale_infimum"] is None for g in gs
                    ),
                    joint_requires_scale_above_one_count=sum(
                        g["joint_flip_scale_infimum"] is not None
                        and g["joint_flip_scale_infimum"] > 1
                        for g in gs
                    ),
                )
    return plan, raw, summary


class PinnedRankDirectionTests(unittest.TestCase):
    def test_complete_source_only_576_census_and_stratification(self):
        report = audit_rank_direction(*registered())
        self.assertEqual(report["policy_attempts"], 576)
        self.assertEqual(len(report["by_stage_phase_arm"]), 72)
        self.assertEqual(
            report["final_test_transfer"]["gated"]["natural_rank_flips"], 2
        )
        self.assertEqual(
            report["final_test_transfer"]["gated"]["direction_cannot_flip"], 12
        )
        self.assertEqual(
            report["final_test_transfer"]["gated"][
                "direction_correct_but_scale_above_one"
            ],
            2,
        )
        self.assertEqual(report["model_or_reader_executions"], 0)
        self.assertFalse(report["production_accepted"])

    def test_missing_duplicated_failed_or_extra_attempt_fails_closed(self):
        for which in ("missing", "duplicate", "failed", "unregistered"):
            plan, rows, saved = registered()
            if which == "missing":
                rows.pop()
            elif which == "duplicate":
                rows[-1] = rows[0]
            elif which == "failed":
                rows[0]["status"] = "failed"
            else:
                rows[0]["question_id"] = "heldout-other"
            with self.subTest(which=which), self.assertRaises(AuditError):
                audit_rank_direction(plan, rows, saved)

    def test_stored_original_aggregate_must_match_every_count(self):
        for which in ("missing", "overcount", "phase"):
            plan, rows, saved = registered()
            if which == "missing":
                saved.pop("48/test/gated")
            elif which == "overcount":
                saved["48/test/gated"]["changed_top1_count"] = 7
            else:
                saved["48/test/gated"] = saved.pop("48/select/gated")
            with self.subTest(which=which), self.assertRaises(AuditError):
                audit_rank_direction(plan, rows, saved)

    def test_rank_direction_and_counterfactual_scale_cannot_be_faked(self):
        for which in ("fake-flip", "fake-boundary", "unscalable-flip", "wrong-encoder"):
            plan, rows, saved = registered()
            item = next(
                row
                for row in rows
                if row["arm"] == "gated"
                and row["phase"] == "test"
                and row["stage"] == 48
                and row["question_id"] == "test-2"
            )
            g = item["selection_geometry"]
            if which == "fake-flip":
                g["changed_selected_candidate"] = False
            elif which == "fake-boundary":
                g["joint_flip_scale_infimum"] = 5.0
            elif which == "unscalable-flip":
                g["joint_flip_scale_infimum"] = None
            else:
                g["encoder_adapted"] = True
            with self.subTest(which=which), self.assertRaises(AuditError):
                audit_rank_direction(plan, rows, saved)

    def test_invalid_score_geometry_and_schema_are_rejected(self):
        for field, value in (
            ("candidate_count", 1),
            ("raw_scores_sha256", "fake"),
            ("label_free", False),
            ("residual_scaling_is_not_a_validated_policy", False),
            ("gap_exceeds_twice_max_residual", None),
            ("max_abs_score_delta", float("inf")),
        ):
            plan, rows, saved = registered()
            g = rows[0]["selection_geometry"]
            g[field] = value
            with self.subTest(field=field), self.assertRaises(AuditError):
                audit_rank_direction(plan, rows, saved)

    def test_frozen_control_cannot_claim_a_learned_rank_flip(self):
        plan, rows, saved = registered()
        g = rows[0]["selection_geometry"]
        g["joint_flip_scale_infimum"] = 0.7
        with self.assertRaises(AuditError):
            audit_rank_direction(plan, rows, saved)

    def test_candidate_and_family_registration_precede_looking_at_labels(self):
        plan, rows, saved = registered()
        plan["question_families"]["test-0"] = "new-family-after-review"
        with self.assertRaises(AuditError):
            audit_rank_direction(plan, rows, saved)


if __name__ == "__main__":
    unittest.main()
