"""Regression gates for the preregistered factorial evidence audit."""

import copy
import hashlib
import json
import unittest

from factorial_evidence_gate import (
    ARMS,
    CONDITIONS,
    READERS,
    TASKS,
    COST_KEYS,
    analyze,
    sha,
)


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def fixture():
    cases = [
        {
            "id": f"case-{i}",
            "root": f"family-{i // 2}",
            "task": TASKS[i % len(TASKS)],
            "answer_sha256": digest(f"a{i}"),
            "oracle_source_sha256": digest(f"o{i}"),
            "premise_sha256": digest(f"p{i}"),
        }
        for i in range(4)
    ]
    plan = {
        "schema": "hepta.memory-factorial.plan.v1",
        "conditions": list(CONDITIONS),
        "readers": list(READERS),
        "arms": list(ARMS),
        "tasks": list(TASKS),
        "cutoff": "2026-10-15T00:00:00Z",
        "registered_before_exposure": True,
        "tool_permissions_equal": True,
        "reader_budget": {"total_tokens": 1024},
        "cases": cases,
    }
    rows = []
    for case in cases:
        for arm in ARMS:
            for reader in READERS:
                for condition in CONDITIONS:
                    rows.append(
                        {
                            "id": case["id"],
                            "root": case["root"],
                            "arm": arm,
                            "reader": reader,
                            "condition": condition,
                            "plan_sha256": sha(plan),
                            "verified": True,
                            "success": condition == "oracle",
                            "answer_digest": digest("answer"),
                            "source_digest": digest("source" + condition),
                            "reader_revision": f"immutable-model-{reader}-sha",
                            "prompt_digest": digest("same-prompt"),
                            "tokens": 500,
                            "cost": {k: 1.0 for k in COST_KEYS},
                            "diagnostic_count": 2,
                            "recovery_success": False,
                        }
                    )
    return plan, rows


class FactorialAuditTest(unittest.TestCase):
    def test_complete_matrix_and_costs(self):
        plan, rows = fixture()
        report = analyze(plan, rows)
        self.assertEqual(report["observations"], 160)
        self.assertEqual(report["source_families_claimed"], 2)
        self.assertEqual(
            report["arms"]["hybrid_rag"]["frozen"]["oracle"]["success_rate"], 1
        )
        self.assertEqual(
            report["arms"]["hybrid_rag"]["frozen"]["hybrid"]["total_cost"][
                "raw_storage"
            ],
            4,
        )
        self.assertFalse(report["production_qualified"])
        self.assertTrue(report["diagnosis"]["learning_candidate_rejected"])

    def test_reject_unrepresented_prospective_task_family(self):
        plan, rows = fixture()
        plan["cases"][3]["task"] = "new_fact"
        # Observation digests bind the changed registration, not a stale plan.
        for row in rows:
            row["plan_sha256"] = sha(plan)
        with self.assertRaisesRegex(ValueError, "every preregistered task family"):
            analyze(plan, rows)

    def test_reject_unchanged_premise_ablation_payload(self):
        plan, rows = fixture()
        for row in rows:
            if row["condition"] == "ablated":
                row["source_digest"] = digest("sourceoracle")
        with self.assertRaisesRegex(ValueError, "payload collision"):
            analyze(plan, rows)

    def test_reject_oracle_that_is_actually_empty(self):
        plan, rows = fixture()
        for row in rows:
            if row["condition"] == "oracle":
                row["source_digest"] = digest("sourcenone")
        with self.assertRaisesRegex(ValueError, "payload collision"):
            analyze(plan, rows)

    def test_reader_reference_must_be_a_different_model(self):
        plan, rows = fixture()
        for row in rows:
            row["reader_revision"] = "same-revision-both-tiers"
        with self.assertRaisesRegex(ValueError, "distinct immutable revisions"):
            analyze(plan, rows)

    def test_parametric_only_can_have_no_raw_evidence_under_all_conditions(self):
        plan, rows = fixture()
        for row in rows:
            if row["arm"] == "knowledge_only":
                row["source_digest"] = digest("identical-empty-evidence")
        self.assertFalse(analyze(plan, rows)["production_qualified"])

    def test_reject_missing_arm(self):
        plan, rows = fixture()
        with self.assertRaisesRegex(ValueError, "incomplete matrix"):
            analyze(plan, rows[:-1])

    def test_reject_duplicate(self):
        plan, rows = fixture()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            analyze(plan, rows + [rows[0]])

    def test_reject_unbound_observation(self):
        plan, rows = fixture()
        rows[0]["plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "frozen plan"):
            analyze(plan, rows)

    def test_reject_prompt_drift(self):
        plan, rows = fixture()
        rows[0]["prompt_digest"] = digest("modified")
        with self.assertRaisesRegex(ValueError, "prompt changed"):
            analyze(plan, rows)

    def test_reject_reader_drift(self):
        plan, rows = fixture()
        rows[0]["reader_revision"] = "different"
        with self.assertRaisesRegex(ValueError, "reader changed"):
            analyze(plan, rows)

    def test_reject_tool_inequality(self):
        plan, rows = fixture()
        plan["tool_permissions_equal"] = False
        with self.assertRaisesRegex(ValueError, "permissions"):
            analyze(plan, rows)

    def test_reject_unverified_success(self):
        plan, rows = fixture()
        rows[0]["verified"] = False
        with self.assertRaisesRegex(ValueError, "unverified"):
            analyze(plan, rows)

    def test_reject_free_storage(self):
        plan, rows = fixture()
        del rows[0]["cost"]["raw_storage"]
        with self.assertRaisesRegex(ValueError, "full lifecycle"):
            analyze(plan, rows)


if __name__ == "__main__":
    unittest.main()
