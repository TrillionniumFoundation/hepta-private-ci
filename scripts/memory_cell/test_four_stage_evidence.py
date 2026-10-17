"""Negative-control regressions and original pinned four-stage evidence audit."""

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from four_stage_evidence import (
    ARMS,
    COST_FIELDS,
    EMPTY_SHA,
    PINNED,
    ROOT,
    break_even,
    historical,
    prospective_guard,
    strict_json,
    total_cost,
)

SHA = "a" * 64


def future_fixture():
    kinds = ("new_fact", "updated_fact", "composition", "program")
    cases = [
        {
            "id": f"case-{i}",
            "family": f"root-{i}",
            "kind": kind,
            "snapshot_frozen_at": "2026-10-13T00:00:00Z",
            "revealed_at": "2026-10-14T00:00:00Z",
            "candidate_pool_sha256": "e" * 64,
            "policy_snapshot_sha256": "6" * 64,
            "knowledge_snapshot_sha256": "7" * 64,
        }
        for i, kind in enumerate(kinds)
    ]
    plan = {
        "schema": "hepta.memory.four-stage-prospective-plan.v1",
        "arms": list(ARMS),
        "cases": cases,
        "contains_gold_answers": False,
        "answer_space_oracle": False,
        "frozen_execution": {
            "base_reader_sha256": "b" * 64,
            "reference_reader_sha256": "f" * 64,
            "prompt_template_sha256": "d" * 64,
            "tools_sha256": SHA,
            "input_budget": 2048,
            "output_budget": 64,
        },
    }
    rows = []
    for case in cases:
        for arm in ARMS:
            rows.append(
                {
                    "task_id": case["id"],
                    "arm": arm,
                    "status": "succeeded",
                    "reader_sha256": "f" * 64
                    if arm.startswith("reference:")
                    else "b" * 64,
                    "prompt_template_sha256": "d" * 64,
                    "tools_sha256": SHA,
                    "candidate_pool_sha256": "e" * 64,
                    "specialization_sha256": (
                        "6" * 64
                        if arm == "base:learned_policy"
                        else "7" * 64
                        if arm in ("base:knowledge", "base:knowledge_only")
                        else EMPTY_SHA
                    ),
                    "evidence_sha256": EMPTY_SHA
                    if arm in ("base:none", "base:knowledge_only", "reference:none")
                    else "c" * 64,
                    "input_budget": 2048,
                    "output_budget": 64,
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "strict_task_success": False,
                    "complete_citation_chain": False,
                }
            )
    return plan, rows


class OriginalPinnedEvidenceTests(unittest.TestCase):
    def test_four_observed_negative_stages(self):
        result = historical()
        self.assertEqual(result["admission"], "DENY_ALL")
        self.assertEqual(result["new_model_inferences"], 0)
        self.assertFalse(result["phase1_reader"]["reader_sufficiency_qualified"])
        self.assertEqual(
            result["phase1_reader"]["real_original_reader_conditions"]["qwen-3b"][
                "strict_success"
            ]["without_prerequisite"],
            4,
        )
        self.assertEqual(
            result["phase2_organization"][
                "organized_additional_success_vs_complete_path"
            ],
            0,
        )
        self.assertEqual(
            result["phase2_organization"][
                "organized_saved_input_tokens_vs_complete_path"
            ],
            573,
        )
        self.assertEqual(
            result["phase3_parameters"][
                "heldout_development_task_answer_changes_per_head"
            ],
            0,
        )
        self.assertIsNone(result["phase4_lifetime"]["complete_lifecycle_cost"])
        self.assertFalse(result["phase4_lifetime"]["production_accepted"])

    def test_modified_real_receipt_is_not_accepted_as_fresh_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, _ in PINNED.values():
                destination = Path(temp) / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, destination)
            path = Path(temp) / PINNED["strong"][0]
            content = json.loads(path.read_text())
            content["actual_evaluation_calls"] = 999
            path.write_text(json.dumps(content))
            with self.assertRaisesRegex(ValueError, "pinned Git blob mismatch"):
                historical(Path(temp))

    def test_duplicate_json_and_nonfinite_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    strict_json(raw)


class LifetimeCostTests(unittest.TestCase):
    def full(self):
        return {name: 1.0 for name in COST_FIELDS}

    def test_all_components_and_storage_included(self):
        obj = self.full()
        cost = total_cost(obj, 10)
        self.assertEqual(cost["complete_total"], 28.0)
        self.assertEqual(cost["unit"], "USD at one fixed retention horizon")
        self.assertFalse(cost["production_cost_qualified"])

    def test_unknown_revocation_never_zero(self):
        obj = self.full()
        obj["revocation"] = None
        cost = total_cost(obj, 100)
        self.assertIsNone(cost["complete_total"])
        self.assertIn("revocation", cost["missing"])
        self.assertIsNone(break_even(self.full(), obj))

    def test_invalid_values_and_missing_storage_denied(self):
        for invalid in (True, -1.0, float("nan"), float("inf")):
            obj = self.full()
            obj["query_per_use"] = invalid
            with self.subTest(invalid=str(invalid)):
                with self.assertRaises(ValueError):
                    total_cost(obj, 10)
        obj = self.full()
        del obj["source_storage"]
        with self.assertRaisesRegex(ValueError, "full cost"):
            total_cost(obj, 10)

    def test_observable_break_even_under_complete_assumptions(self):
        original = {k: 0.0 for k in COST_FIELDS}
        proposed = {k: 0.0 for k in COST_FIELDS}
        original["query_per_use"] = 10.0
        proposed["train"] = 100.0
        self.assertEqual(break_even(original, proposed), 10)
        original["query_per_use"] = 0.0
        self.assertIsNone(break_even(original, proposed))


class ProspectiveControlsTests(unittest.TestCase):
    def test_complete_synthetic_fixture_still_not_production_evidence(self):
        plan, rows = future_fixture()
        result = prospective_guard(plan, rows)
        self.assertEqual(result["recorded_tasks"], 4)
        self.assertEqual(result["by_arm"]["base:retrieved"]["correct"], 0)
        self.assertFalse(result["journal_authenticity_certified"])
        self.assertFalse(result["production_accepted"])

    def test_changed_prompt_or_tool_permission_denied(self):
        for field in ("prompt_template_sha256", "tools_sha256", "input_budget"):
            plan, rows = future_fixture()
            row = next(x for x in rows if x["arm"] == "base:learned_policy")
            row[field] = 512 if field == "input_budget" else "9" * 64
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    ValueError, "frozen execution config drift"
                ):
                    prospective_guard(plan, rows)

    def test_same_evidence_required_for_knowledge_gain(self):
        plan, rows = future_fixture()
        row = next(x for x in rows if x["arm"] == "base:knowledge")
        row["evidence_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "knowledge gain"):
            prospective_guard(plan, rows)

    def test_no_raw_context_in_knowledge_only(self):
        plan, rows = future_fixture()
        row = next(x for x in rows if x["arm"] == "base:knowledge_only")
        row["evidence_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "module-only"):
            prospective_guard(plan, rows)

    def test_snapshot_must_precede_task_reveal(self):
        plan, rows = future_fixture()
        plan["cases"][0]["snapshot_frozen_at"] = "2026-10-15T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "snapshot must freeze"):
            prospective_guard(plan, rows)

    def test_all_attempts_in_denominator(self):
        plan, rows = future_fixture()
        with self.assertRaisesRegex(ValueError, "all planned"):
            prospective_guard(plan, rows[:-1])
        plan, rows = future_fixture()
        rows[0] = dict(rows[1])
        with self.assertRaisesRegex(ValueError, "duplicate/unplanned"):
            prospective_guard(plan, rows)

    def test_training_after_gold_cannot_reclassify_oracle_as_prospective(self):
        plan, rows = future_fixture()
        plan["answer_space_oracle"] = True
        with self.assertRaisesRegex(ValueError, "oracle forbidden"):
            prospective_guard(plan, rows)

    def test_candidate_drift_and_reader_replacement(self):
        plan, rows = future_fixture()
        for key, new_value, message in (
            ("candidate_pool_sha256", "9" * 64, "candidate pool changed"),
            ("reader_sha256", "9" * 64, "frozen reader identity drift"),
        ):
            broken = copy.deepcopy(rows)
            row = next(x for x in broken if x["arm"] == "base:organized")
            row[key] = new_value
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, message):
                    prospective_guard(plan, broken)

    def test_exceeded_tokens_or_failed_attempt_forgery(self):
        plan, rows = future_fixture()
        rows[0]["input_tokens"] = 2049
        with self.assertRaisesRegex(ValueError, "budget exceeded"):
            prospective_guard(plan, rows)
        plan, rows = future_fixture()
        rows[0]["status"] = "failed"
        rows[0]["strict_task_success"] = True
        with self.assertRaisesRegex(ValueError, "failed model call"):
            prospective_guard(plan, rows)

    def test_program_success_needs_real_verifier_receipt(self):
        plan, rows = future_fixture()
        row = next(x for x in rows if x["task_id"] == "case-3")
        row["strict_task_success"] = True
        with self.assertRaisesRegex(ValueError, "actual program verifier"):
            prospective_guard(plan, rows)
        row["program_exit_code"] = 0
        row["program_test_sha256"] = SHA
        result = prospective_guard(plan, rows)
        self.assertEqual(result["by_arm"][row["arm"]]["correct"], 1)
        self.assertFalse(result["strict_execution_success_independently_certified"])

    def test_reference_has_identical_evidence_for_every_regime(self):
        plan, rows = future_fixture()
        row = next(x for x in rows if x["arm"] == "reference:sufficient")
        row["evidence_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "reference evidence parity"):
            prospective_guard(plan, rows)

    def test_reference_no_evidence_cannot_get_hidden_document(self):
        plan, rows = future_fixture()
        row = next(x for x in rows if x["arm"] == "reference:none")
        row["evidence_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "no-evidence or module-only"):
            prospective_guard(plan, rows)

    def test_frozen_parameter_bytes_same_before_task_exposure(self):
        for arm in ("base:learned_policy", "base:knowledge", "base:knowledge_only"):
            plan, rows = future_fixture()
            row = next(x for x in rows if x["arm"] == arm)
            row["specialization_sha256"] = "9" * 64
            with self.subTest(arm=arm):
                with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
                    prospective_guard(plan, rows)
        plan, rows = future_fixture()
        plan["cases"][0]["knowledge_snapshot_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(ValueError, "snapshot identity required"):
            prospective_guard(plan, rows)

    def test_organized_always_measured_against_strong_hybrid(self):
        plan, rows = future_fixture()
        report = prospective_guard(plan, rows)
        self.assertIn(
            "base:organized__vs__base:retrieved", report["paired_descriptive"]
        )

    def test_reader_weights_and_token_limits_frozen_for_entire_cohort(self):
        plan, rows = future_fixture()
        plan["frozen_execution"]["base_reader_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "frozen reader identity drift"):
            prospective_guard(plan, rows)
        plan, rows = future_fixture()
        plan["frozen_execution"]["output_budget"] = 16
        with self.assertRaisesRegex(ValueError, "frozen execution config drift"):
            prospective_guard(plan, rows)

    def test_policy_only_gain_requires_same_organized_evidence(self):
        plan, rows = future_fixture()
        row = next(x for x in rows if x["arm"] == "base:learned_policy")
        row["evidence_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "read-policy gain"):
            prospective_guard(plan, rows)

    def test_knowledge_only_also_compared_with_no_memory(self):
        plan, rows = future_fixture()
        report = prospective_guard(plan, rows)
        self.assertIn(
            "base:knowledge_only__vs__base:none", report["paired_descriptive"]
        )


if __name__ == "__main__":
    unittest.main()
