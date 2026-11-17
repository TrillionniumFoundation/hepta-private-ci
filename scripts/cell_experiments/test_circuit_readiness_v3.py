"""Mechanical receipt fixtures only; these are not new learning observations."""

import copy
import unittest

from .chat_protocol import inference_messages
from .circuit_readiness_v3 import ablation_metrics, bound_panel, routing_readiness
from .data import digest
from .test_circuit_task_readout_v2 import MODELS, material


def measured_material(successes=None, *, aliases=False, failed_original=False):
    records, features, evaluations = material(successes=successes)
    if aliases:
        records[1]["lineage_id"] = records[0]["lineage_id"]
        features[1]["lineage_id"] = features[0]["lineage_id"]
    for evaluation in evaluations:
        evaluation["schema"] = "hepta.repository-evaluation.v3"
        for record, row in zip(records, evaluation["rows"]):
            row["lineage_id"] = record["lineage_id"]
            row["task_digest"] = digest(record)
            step = row["steps"][0]
            request = {
                "record_id": record["record_id"],
                "task": {
                    "input": record["task"]["input"],
                    "messages": inference_messages(
                        record["task"]["input"], record["task"].get("messages")
                    ),
                },
            }
            step["request_sha256"] = digest(request)
            verification = step["verification"]
            result = verification["result"]["result"]
            if failed_original:
                result["original_passed"] = False
                result["controls_rejected"] = 2
            calls = [] if failed_original else [{"arguments": [1], "output": 1}]
            result["observations"] = [
                {"control": "original", "passed": not failed_original, "calls": calls},
                *[
                    {
                        "control": f"control-{i}",
                        "passed": i >= result["controls_rejected"],
                        "calls": calls,
                    }
                    for i in range(result["control_count"])
                ],
            ]
            payload = {
                key: value
                for key, value in verification.items()
                if key not in ("success", "receipt_sha256")
            }
            verification["receipt_sha256"] = digest(payload)
            step["execution_summary"] = {
                "verification_receipt_sha256": verification["receipt_sha256"],
                "subject_call_count": len(calls),
                "subject_call_count_scope": "completed_original_calls",
                "subject_call_attempt_count": None,
            }
            step["receipt_sha256"] = digest(
                {key: value for key, value in step.items() if key != "receipt_sha256"}
            )
    return records, features, evaluations


def readiness(data):
    records, features, evaluations = data
    return routing_readiness(
        records, evaluations, MODELS, features, expected_panel_digest=digest(records)
    )


class CircuitReadinessTests(unittest.TestCase):
    def test_all_failure_does_not_create_a_training_label_or_block_baselines(self):
        data = measured_material([[False] * 3 for _ in MODELS], failed_original=True)
        result = readiness(data)
        self.assertEqual(result["training_rows"], [])
        receipt = result["receipt"]
        self.assertEqual(receipt["status"], "NOT_READY")
        self.assertEqual([row["target"] for row in receipt["observations"]], [None] * 3)
        self.assertTrue(receipt["single_and_fixed_measurements_allowed"])
        self.assertEqual(receipt["observed_oracle_successful_primary_clusters"], 0)

    def test_complementary_real_successes_keep_original_v3_receipt_identity(self):
        data = measured_material()
        original = copy.deepcopy(data)
        result = readiness(data)
        self.assertEqual(data, original)
        self.assertEqual(result["receipt"]["status"], "READY_FOR_ROUTING_DIAGNOSTIC")
        self.assertEqual([row["target"] for row in result["training_rows"]], [0, 1])
        self.assertEqual(result["receipt"]["observed_oracle_gain_clusters"], 1)
        for evaluation, upstream in zip(
            data[2], result["receipt"]["upstream_evaluations"]
        ):
            self.assertEqual(upstream["evaluation_digest"], digest(evaluation))
            self.assertEqual(
                upstream["validation_projection"]["changed_fields"], ["schema"]
            )
        self.assertEqual(
            result["receipt"]["independent_scientific_qualification"], "BLOCKED"
        )

    def test_alias_branches_do_not_manufacture_complementarity(self):
        result = readiness(measured_material(aliases=True))
        self.assertEqual(result["receipt"]["provenance_cluster_count"], 2)
        self.assertEqual(result["receipt"]["primary_task_ids"], ["task-0", "task-2"])
        self.assertEqual(result["receipt"]["observed_oracle_gain_clusters"], 0)
        self.assertEqual(result["receipt"]["status"], "NOT_READY")
        self.assertEqual(len(result["training_rows"]), 1)

    def test_execution_summary_cannot_disagree_with_the_original_calls(self):
        data = measured_material()
        step = data[2][0]["rows"][0]["steps"][0]
        step["execution_summary"]["subject_call_count"] = 7
        step["receipt_sha256"] = digest(
            {key: value for key, value in step.items() if key != "receipt_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "call count differs"):
            readiness(data)

    def test_same_input_with_different_initial_chat_context_is_not_same_attempt(self):
        data = measured_material()
        step = data[2][0]["rows"][0]["steps"][0]
        step["request_sha256"] = digest({"different_tool_observation": True})
        step["receipt_sha256"] = digest(
            {key: value for key, value in step.items() if key != "receipt_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "frozen chat context"):
            readiness(data)

    def test_missing_call_evidence_is_unknown_and_confirmation_is_not_training(self):
        data = measured_material()
        for evaluation in data[2]:
            for row in evaluation["rows"]:
                step = row["steps"][0]
                verification = step["verification"]
                del verification["result"]["result"]["observations"]
                verification["receipt_sha256"] = digest(
                    {
                        key: value
                        for key, value in verification.items()
                        if key not in ("success", "receipt_sha256")
                    }
                )
                del step["execution_summary"]
                step["receipt_sha256"] = digest(
                    {
                        key: value
                        for key, value in step.items()
                        if key != "receipt_sha256"
                    }
                )
        self.assertEqual(readiness(data)["receipt"]["status"], "NOT_READY")
        data[0][0]["split"] = "confirmation"
        with self.assertRaisesRegex(ValueError, "authorized A"):
            readiness(data)

    def test_business_summaries_must_agree_with_original_and_control_observations(self):
        for field in ("original", "control"):
            with self.subTest(field=field):
                data = measured_material()
                step = data[2][0]["rows"][0]["steps"][0]
                verification = step["verification"]
                observations = verification["result"]["result"]["observations"]
                observations[0 if field == "original" else 1]["passed"] = (
                    field != "original"
                )
                verification["receipt_sha256"] = digest(
                    {
                        key: value
                        for key, value in verification.items()
                        if key not in ("success", "receipt_sha256")
                    }
                )
                step["execution_summary"]["verification_receipt_sha256"] = verification[
                    "receipt_sha256"
                ]
                step["receipt_sha256"] = digest(
                    {
                        key: value
                        for key, value in step.items()
                        if key != "receipt_sha256"
                    }
                )
                with self.assertRaisesRegex(ValueError, "disagrees with observations"):
                    readiness(data)

    def test_completed_calls_cannot_be_reported_as_attempts(self):
        data = measured_material()
        step = data[2][0]["rows"][0]["steps"][0]
        step["execution_summary"]["subject_call_count_scope"] = "attempted_calls"
        step["receipt_sha256"] = digest(
            {key: value for key, value in step.items() if key != "receipt_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "relabeled"):
            readiness(data)

    def test_ablation_requires_inventory_and_measures_business_losses(self):
        records, features, evaluations = measured_material()
        bound, _, _ = bound_panel(records, evaluations, MODELS, digest(records))
        main = [bound[slot][f"task-{i}"] for i, slot in enumerate([0, 1, 0])]
        dropped = [bound[slot][f"task-{i}"] for i, slot in enumerate([1, 1, 0])]
        readout = {
            "arms": {
                "single": {
                    "main": {"rows": main},
                    "ablations": {
                        "cells": {"0": {"rows": dropped}},
                        "edges": {"0": {"rows": main}},
                    },
                }
            },
            "online_routed_execution_performed": False,
        }
        result = ablation_metrics(
            readout,
            expected_readout_digest=digest(readout),
            expected_members={"single": {"cells": ["0", "1"], "edges": ["0"]}},
        )
        self.assertFalse(result["declared_ablations_complete"])
        self.assertEqual(result["missing_ablations"], ["single/cells/1"])
        cell = result["arms"]["single"]["cells"]["0"]
        self.assertEqual(cell["tasks_lost"], ["task-0"])
        self.assertEqual(cell["success_count_change"], -1)
        self.assertEqual(cell["independent_sample_increment"], 0)

    def test_ablation_cannot_transplant_another_tasks_success_receipt(self):
        records, _, evaluations = measured_material()
        bound, _, _ = bound_panel(records, evaluations, MODELS, digest(records))
        main = list(bound[0].values())
        swapped = copy.deepcopy(main)
        other = copy.deepcopy(bound[1]["task-1"])
        for key in ("task_id", "source_id", "lineage_id", "task_digest"):
            other[key] = swapped[0][key]
        swapped[0] = other
        readout = {
            "arms": {
                "single": {
                    "main": {"rows": main},
                    "ablations": {
                        "cells": {"0": {"rows": swapped}},
                        "edges": {"0": {"rows": main}},
                    },
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "semantic task identity"):
            ablation_metrics(
                readout,
                expected_readout_digest=digest(readout),
                expected_members={"single": {"cells": ["0"], "edges": ["0"]}},
            )


if __name__ == "__main__":
    unittest.main()
