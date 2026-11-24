"""Artifact-only diagnosis tests. Synthetic scores are not task evidence."""

from copy import deepcopy
import unittest

from stem_audit_archive import AuditError
from stem_audit_diagnosis import ARMS, STAGES, CELLS, diagnose
from test_stem_audit import fixture


def inputs():
    data = fixture()
    plan, report = data["plan"], data["report"]
    train = [f"train-{i}" for i in range(48)]
    plan["questions"]["train"] = train
    plan["routes"] = {
        **{q: CELLS[i % 2] for i, q in enumerate(train)},
        **{
            q: "general"
            for phase in ("select", "retention", "test", "transfer")
            for q in plan["questions"][phase]
        },
    }
    learning = []
    for stage in STAGES:
        for arm in ARMS:
            for cell in CELLS:
                sha = f"head-{stage}-{arm}-{cell}"
                learning.append(
                    dict(
                        stage=stage,
                        arm=arm,
                        cell=cell,
                        status="succeeded",
                        after_sha256=sha,
                        artifact_bytes=500,
                        receipt=dict(
                            consumed_steps=0 if arm == "frozen_rerank" else 16,
                            tensor_delta_squared_norm=0.0
                            if arm == "frozen_rerank"
                            else 1.0,
                            state_changed=arm != "frozen_rerank",
                        ),
                    )
                )
    report["learning"] = learning
    report["plan"] = deepcopy(plan)
    for row in data["raw"]:
        row["cell"] = "general"
        row["head_sha256"] = f"head-{row['stage']}-{row['arm']}-general"
    for i, row in enumerate(data["scored"]):
        row["head_sha256"] = data["raw"][i]["head_sha256"]
    dispositions = dict(
        skipped_training=[
            dict(
                question_id=train[i],
                reason="unresolved_or_missing_positive_not_abstention",
            )
            for i in (1, 4, 21)
        ]
    )
    adapters = dict(
        receipts={
            "lineage": {"steps": 24},
            "independent-general": {"steps": 12},
        },
        failures={
            "independent-temporal": {"error_type": "ValueError", "error": "fixture"}
        },
    )
    return data, dispositions, {}, adapters


def check(data, skipped, features, adapters):
    return diagnose(
        data["plan"],
        data["raw"],
        data["scored"],
        data["report"],
        skipped,
        features,
        adapters,
    )


class DiagnosisTests(unittest.TestCase):
    def test_training_is_counted_as_admitted_not_attempted(self):
        data, skipped, features, adapters = inputs()
        result = check(data, skipped, features, adapters)
        self.assertEqual(result["admitted_training_questions"], 45)
        self.assertEqual(result["skipped_training_questions"], 3)
        self.assertEqual(result["admitted_prefixes"]["16"]["admitted"], 14)
        self.assertEqual(result["admitted_prefixes"]["32"]["admitted"], 29)
        self.assertEqual(result["admitted_prefixes"]["48"]["admitted"], 45)
        self.assertEqual(
            result["adapter_training_status"]["independent-temporal"], "failed"
        )
        self.assertEqual(len(result["learning_journal"]), 36)
        self.assertEqual(len(result["paired_diagnostics"]), 60)
        self.assertFalse(result["independent_task_gain_established"])

    def test_common_failure_is_not_attributed_to_lora_alone(self):
        data, skipped, features, adapters = inputs()
        for row in data["raw"]:
            if row["stage"] == 48 and row["phase"] == "test":
                row.update(
                    status="failed",
                    error_type="ValueError",
                    error="upstream",
                    error_stage="features",
                )
                row.pop("answer")
                row.pop("receipt")
        features["test"] = dict(error_type="ValueError", error="upstream")
        result = check(data, skipped, features, adapters)
        self.assertEqual(len(result["all_six_arms_failed_tasks"]), 1)
        self.assertEqual(result["lora_only_failed_tasks"], [])
        self.assertEqual(result["failed_policy_arms"], {arm: 1 for arm in ARMS})
        self.assertEqual(result["feature_failures_by_phase"]["test"], 1)

    def test_lora_only_failure_has_distinct_classification(self):
        data, skipped, features, adapters = inputs()
        for row in data["raw"]:
            if (
                row["stage"] == 16
                and row["phase"] == "transfer"
                and row["arm"] in ARMS[-2:]
            ):
                row["status"] = "failed"
                row["error_type"] = "RuntimeError"
                row["error"] = "adapter missing"
        result = check(data, skipped, features, adapters)
        self.assertEqual(len(result["lora_only_failed_tasks"]), 1)
        self.assertEqual(result["all_six_arms_failed_tasks"], [])

    def test_policy_head_sha_must_match_checkpoint_snapshot(self):
        data, skipped, features, adapters = inputs()
        data["raw"][0]["head_sha256"] = "wrong"
        with self.assertRaisesRegex(AuditError, "checkpoint Head"):
            check(data, skipped, features, adapters)

    def test_head_update_claim_cannot_be_invented_from_counter(self):
        data, skipped, features, adapters = inputs()
        data["report"]["learning"][2]["receipt"]["tensor_delta_squared_norm"] = 0.0
        with self.assertRaisesRegex(AuditError, "tensor delta"):
            check(data, skipped, features, adapters)

    def test_disposition_duplicate_or_unadmitted_question_rejected(self):
        for extra in (
            dict(
                question_id="test",
                reason="unresolved_or_missing_positive_not_abstention",
            ),
            dict(
                question_id="train-1",
                reason="unresolved_or_missing_positive_not_abstention",
            ),
            dict(question_id="train-2", reason="invented-support"),
        ):
            data, skipped, features, adapters = inputs()
            skipped["skipped_training"].append(extra)
            with self.assertRaises(AuditError):
                check(data, skipped, features, adapters)

    def test_adapter_attempt_inventory_cannot_silently_shrink(self):
        data, skipped, features, adapters = inputs()
        adapters["failures"].clear()
        with self.assertRaisesRegex(AuditError, "inventory incomplete"):
            check(data, skipped, features, adapters)

    def test_original_answer_and_selection_unchanged_is_zero_pair_gain(self):
        data, skipped, features, adapters = inputs()
        result = check(data, skipped, features, adapters)
        pairs = result["paired_diagnostics"]
        self.assertEqual(pairs["48/transfer/gated"]["both_succeeded"], 1)
        self.assertEqual(pairs["48/transfer/gated"]["selected_candidate_changed"], 0)
        self.assertEqual(pairs["48/transfer/gated"]["original_answer_changed"], 0)
        self.assertEqual(
            pairs["48/transfer/gated"]["measured_answer_f1_delta_mean"], 0.0
        )


if __name__ == "__main__":
    unittest.main()
