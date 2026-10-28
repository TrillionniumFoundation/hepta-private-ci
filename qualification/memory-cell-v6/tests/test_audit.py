"""Fault injection into raw evidence, without importing the execution grader."""

import copy
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "independent_audit", Path(__file__).resolve().parents[1] / "audit_results.py"
)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def fixture():
    queries = {
        "known": {
            "id": "known",
            "operation": "current",
            "language": "en",
            "family": "known.test",
        },
        "unsupported": {
            "id": "unsupported",
            "operation": None,
            "language": "en",
            "family": "ood.test",
        },
    }
    rows = []
    for arm in ("parameter_actual", "exact_same_router"):
        for template, gold in queries.items():
            known = gold["operation"] is not None
            rows.append(
                {
                    "template_id": template,
                    "seed": 1,
                    "domain": "test",
                    "arm": arm,
                    "language": "en",
                    "query_family": gold["family"],
                    "gold_operation": gold["operation"],
                    "actual_operation": gold["operation"],
                    "accepted": known,
                    "expected_value": 7 if known else None,
                    "actual_value": 7 if known else None,
                    "expected_value_digest": AUDIT.value_digest(7) if known else None,
                    "actual_value_digest": AUDIT.value_digest(7) if known else None,
                    "expected_sources": ["event-a", "event-b"] if known else [],
                    "actual_sources": ["event-a", "event-b"] if known else [],
                    "source_versions_valid": True,
                    "value_correct": known,
                    "source_correct": known,
                    "snapshot_digest": "2" * 64,
                    "router_digest": "3" * 64,
                    "model_digest": "4" * 64,
                    "latency_seconds": 0.01,
                    "rpc_bytes": 32,
                    "hops": int(known),
                    "status": "ok" if known else "abstain",
                    "prediction_kind": "exact_reference" if known else "abstain",
                }
            )
    protocol = {
        "languages": ["en"],
        "gate_correct_known_acceptance_minimum": 0.8,
        "gate_unsupported_acceptance_maximum": 0.05,
    }
    return rows, queries, protocol


class AuditTests(unittest.TestCase):
    def test_transport_and_final_validation_costs_are_conserved(self):
        rows, queries, protocol = fixture()
        for row in rows:
            active = int(row["accepted"])
            row["rpc_bytes"] = 32 * active
            row["transport"] = {
                "rpc_attempts": 2 * active,
                "read_attempts": active,
                "validation_attempts": active,
                "attempted_request_bytes": 10 * active,
                "received_response_bytes": 22 * active,
                "node_count": active,
                "rpc_bytes": 32 * active,
            }
            row["routing_batch_amortized_seconds"] = 0.002
            row["read_plus_amortized_routing_seconds"] = 0.012
        clean = AUDIT.audit_records(rows, queries, protocol)
        self.assertTrue(clean["audit_passed"])
        self.assertEqual(clean["cases"][0]["transport_totals"]["rpc_attempts"], 2)
        rows[0]["transport"]["validation_attempts"] = 0
        rows[0]["read_plus_amortized_routing_seconds"] = 0.01
        altered = AUDIT.audit_records(rows, queries, protocol)
        self.assertFalse(altered["audit_passed"])
        self.assertTrue(
            any("conservation" in failure for failure in altered["failures"])
        )

    def test_complete_paired_evidence_and_real_failure(self):
        rows, queries, protocol = fixture()
        clean = AUDIT.audit_records(rows, queries, protocol)
        self.assertTrue(clean["audit_passed"])
        self.assertTrue(clean["primary_joint_gate"])
        changed = copy.deepcopy(rows)
        changed[0]["actual_value"] = 9
        changed[0]["actual_value_digest"] = AUDIT.value_digest(9)
        changed[0]["value_correct"] = False
        actual_failure = AUDIT.audit_records(changed, queries, protocol)
        self.assertTrue(actual_failure["audit_passed"])
        self.assertFalse(actual_failure["primary_joint_gate"])
        self.assertEqual(actual_failure["paired_primary_minus_exact_success_count"], -1)

    def test_wrong_provenance_and_forged_success_are_detected(self):
        rows, queries, protocol = fixture()
        rows[0]["actual_sources"].reverse()
        result = AUDIT.audit_records(rows, queries, protocol)
        self.assertFalse(result["audit_passed"])
        self.assertTrue(
            any("provenance correctness flag" in value for value in result["failures"])
        )
        self.assertFalse(result["primary_joint_gate"])

    def test_missing_rows_and_duplicate_repetitions_cannot_inflate_evidence(self):
        rows, queries, protocol = fixture()
        del rows[1]
        rows.append(copy.deepcopy(rows[0]))
        result = AUDIT.audit_records(rows, queries, protocol)
        self.assertFalse(result["audit_passed"])
        self.assertTrue(any("duplicate" in value for value in result["failures"]))
        self.assertTrue(any("incomplete" in value for value in result["failures"]))

    def test_gold_and_same_router_controls_are_bound(self):
        rows, queries, protocol = fixture()
        rows[0]["gold_operation"] = "semantic"
        rows[2]["router_digest"] = "6" * 64
        result = AUDIT.audit_records(rows, queries, protocol)
        self.assertFalse(result["audit_passed"])
        self.assertTrue(any("gold operation" in value for value in result["failures"]))
        self.assertTrue(
            any("comparator mismatch" in value for value in result["failures"])
        )

    def test_repeated_seeds_do_not_multiply_language_units(self):
        rows, queries, protocol = fixture()
        repeat = copy.deepcopy(rows)
        for row in repeat:
            row["seed"] = 2
        result = AUDIT.audit_records(rows + repeat, queries, protocol)
        self.assertTrue(result["audit_passed"])
        self.assertEqual(result["distinct_language_templates"], 2)
        self.assertEqual(
            result["family_intervals"]["parameter_actual"]["known"]["templates"], 1
        )

    def test_unsupported_downstream_failure_does_not_hide_router_mistake(self):
        rows, queries, protocol = fixture()
        for index in (1, 3):
            rows[index]["actual_operation"] = "current"
        result = AUDIT.audit_records(rows, queries, protocol)
        self.assertTrue(result["audit_passed"])
        primary = next(
            case for case in result["cases"] if case["arm"] == "parameter_actual"
        )
        self.assertEqual(primary["overall"]["unsupported_routed_despite_contract"], 1)
        self.assertEqual(primary["overall"]["false_unsupported_acceptance"], 1)
        self.assertEqual(primary["overall"]["unsupported_final_acceptance"], 0)
        self.assertFalse(result["primary_joint_gate"])

    def test_missing_whole_case_is_detected_by_frozen_plan(self):
        rows, queries, protocol = fixture()
        plan = {
            "seeds": [1, 2],
            "domains": ["test"],
            "full_arms": ["parameter_actual", "exact_same_router"],
        }
        result = AUDIT.audit_records(rows, queries, protocol, plan)
        self.assertFalse(result["audit_passed"])
        self.assertTrue(any("execution plan" in value for value in result["failures"]))

    def test_raw_value_cannot_disagree_with_recorded_digest(self):
        rows, queries, protocol = fixture()
        rows[0]["actual_value"] = 999
        result = AUDIT.audit_records(rows, queries, protocol)
        self.assertFalse(result["audit_passed"])
        self.assertTrue(
            any("raw value digest" in value for value in result["failures"])
        )


if __name__ == "__main__":
    unittest.main()
