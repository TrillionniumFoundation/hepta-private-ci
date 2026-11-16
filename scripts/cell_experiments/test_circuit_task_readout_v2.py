"""Mechanical receipt-binding tests, never additional experiment observations."""

import copy
import hashlib
import unittest

from .composition_core import digest as circuit_digest
from .data import digest
from .circuit_task_readout_v2 import readout, routing_targets


MODELS = [character * 64 for character in "abc"]


def material(split="train", successes=None, unicode_text=False):
    records = [
        {
            "record_id": f"record-{i}",
            "task_id": f"task-{i}",
            "source_id": f"source-{i}",
            "lineage_id": f"lineage-{i}",
            "project_id": "repo",
            "split": split,
            "authorization": {"training_allowed": split == "train"},
            "task": {
                "input": f"Create assertions for subject {i}.",
                "verifier": {
                    "name": "repo_patch",
                    "version": "1",
                    "parameters": {
                        "fixture_id": f"fixture-{i}",
                        "fixture_sha256": digest(i),
                    },
                },
            },
        }
        for i in range(3)
    ]
    if unicode_text:
        for record in records:
            record["project_id"] = "项目"
            record["task"]["input"] = "请补全函数断言：" + record["task"]["input"]
    features = [
        {
            **{
                key: record[key]
                for key in ("task_id", "source_id", "lineage_id", "project_id")
            },
            "observation_digest": digest(record["task"]["input"]),
            "features": [float(i), 0.2],
            "target": 0,
            "feature_binding_digest": "f" * 64,
        }
        for i, record in enumerate(records)
    ]
    successes = successes or [
        [True, False, False],
        [False, True, False],
        [True, False, False],
    ]
    evaluations = []
    for slot, model in enumerate(MODELS):
        rows = []
        for i, record in enumerate(records):
            success = successes[slot][i]
            input_sha = hashlib.sha256(record["task"]["input"].encode()).hexdigest()
            answer = (
                f"记录答案 🌱 {slot}/{i}"
                if unicode_text
                else f"recorded answer {slot}/{i}"
            )
            output = {
                "loaded_model_digest": model,
                "input_sha256": input_sha,
                "answer": answer,
                "input_tokens": 10,
                "output_tokens": slot + 1,
            }
            result = {
                "success": success,
                "executed": True,
                "exit_code": 0,
                "stderr": "诊断：已完成" if unicode_text else "",
                "result": {
                    "original_passed": True,
                    "control_count": 2,
                    "controls_rejected": 2 if success else 1,
                },
            }
            payload = {
                "schema": "hepta.cell-experiments.semantic-receipt.v1",
                "record_id": record["record_id"],
                "input_sha256": input_sha,
                "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                "verifier": ["repo_patch", "1"],
                "verifier_source_sha256": "d" * 64,
                "parameters_sha256": digest(record["task"]["verifier"]["parameters"]),
                "result": result,
                "student_execution_claimed": False,
                "production_eligible": False,
            }
            verification = {
                **payload,
                "success": success,
                "receipt_sha256": digest(payload),
            }
            step = {
                "number": 0,
                "output": output,
                "verification": verification,
                "executed": True,
                "feedback": "observed semantic result",
            }
            step["receipt_sha256"] = digest(step)
            rows.append(
                {
                    **{
                        key: record[key]
                        for key in ("record_id", "task_id", "source_id", "lineage_id")
                    },
                    "task_digest": digest(record),
                    "original_input_sha256": digest(record["task"]["input"]),
                    "steps": [step],
                    "first_attempt_success": success,
                    "success": success,
                }
            )
        evaluations.append(
            {
                "schema": "hepta.repository-evaluation.v2",
                "status": "COMPLETE",
                "model_digest": model,
                "rows": rows,
                "tasks": 3,
                "first_attempt_successes": sum(successes[slot]),
                "cost": {
                    "model_calls": 3,
                    "input_tokens": 30,
                    "output_tokens": 3 * (slot + 1),
                    "wall_seconds": 2.0,
                    "cpu_seconds": 1.0,
                    "complete": False,
                },
            }
        )
    return records, features, evaluations


def predictions(features, choices):
    return {
        "input_digest": circuit_digest(features),
        "classification_accuracy": 1.0,
        "rows": [
            {"task_id": row["task_id"], "prediction": choice, "correct": True}
            for row, choice in zip(features, choices)
        ],
    }


class TaskReadoutTests(unittest.TestCase):
    def test_unicode_external_receipts_and_circuit_hashes_keep_their_conventions(self):
        records, features, evaluations = material(unicode_text=True)
        self.assertNotEqual(digest(records), circuit_digest(records))
        step = evaluations[0]["rows"][0]["steps"][0]
        payload = {key: value for key, value in step.items() if key != "receipt_sha256"}
        self.assertEqual(step["receipt_sha256"], digest(payload))
        self.assertNotEqual(step["receipt_sha256"], circuit_digest(payload))
        targets = routing_targets(
            records,
            evaluations,
            MODELS,
            features,
            expected_panel_digest=digest(records),
        )
        self.assertEqual(
            targets["receipt"]["rows_digest"], circuit_digest(targets["rows"])
        )
        report = {
            "c_input_digest": circuit_digest(features),
            "arms": {"single": predictions(features, [0, 1, 2])},
        }
        evidence = []
        for model in MODELS:
            plan = {"training": {"rank": 4}, "description": "同底座专家"}
            evidence.append(
                {
                    "plan": plan,
                    "training": {
                        "status": "COMPLETE",
                        "candidate_model_digest": model,
                        "parent_model_digest": "e" * 64,
                        "plan_digest": digest(plan),
                        "trainable_parameters": 230400,
                    },
                }
            )
        result = readout(
            report,
            evaluations,
            MODELS,
            records,
            features,
            expected_panel_digest=digest(records),
            capacity_evidence=evidence,
        )
        self.assertEqual(result["routing_report_digest"], circuit_digest(report))
        self.assertEqual(
            result["arms"]["single"]["main"]["business_success_rate"], 2 / 3
        )
        self.assertIn(
            "记录答案 🌱", result["arms"]["single"]["main"]["rows"][0]["raw_answer"]
        )
        self.assertEqual(
            result["upstream_evaluations"][0]["evaluation_digest"],
            digest(evaluations[0]),
        )

    def test_a_labels_use_fixed_tie_priority_and_all_failed_fallback(self):
        records, features, evaluations = material(
            successes=[[True, False, False], [True, False, True], [False, False, True]]
        )
        result = routing_targets(
            records,
            evaluations,
            MODELS,
            features,
            expected_panel_digest=digest(records),
        )
        self.assertEqual([row["target"] for row in result["rows"]], [0, 2, 1])
        self.assertEqual(
            [row["all_failed_fallback"] for row in result["receipt"]["observations"]],
            [False, True, False],
        )
        self.assertEqual(
            result["receipt"]["observed_first_attempt_oracle_ceiling"], 2 / 3
        )
        self.assertEqual([row["target"] for row in features], [0, 0, 0])
        records[0]["split"] = "confirmation"
        with self.assertRaisesRegex(ValueError, "A training"):
            routing_targets(
                records,
                evaluations,
                MODELS,
                features,
                expected_panel_digest=digest(records),
            )

    def test_routes_and_ablations_resolve_actual_business_results(self):
        records, features, evaluations = material("confirmation")
        report = {
            "selected_arm": "learned_sparse",
            "c_input_digest": circuit_digest(features),
            "arms": {
                "learned_sparse": {
                    "main": predictions(features, [0, 1, 2]),
                    "ablations": {
                        "cells": {"0": predictions(features, [1, 0, 2])},
                        "edges": {"1": predictions(features, [2, 1, 2])},
                    },
                }
            },
        }
        result = readout(
            report,
            evaluations,
            MODELS,
            records,
            features,
            expected_panel_digest=digest(records),
        )
        arm = result["arms"]["learned_sparse"]
        self.assertEqual(arm["main"]["business_success_rate"], 2 / 3)
        self.assertEqual(arm["ablations"]["cells"]["0"]["business_success_rate"], 0)
        self.assertEqual(arm["ablations"]["edges"]["1"]["business_success_rate"], 2 / 3)
        self.assertEqual(
            arm["main"]["rows"][1]["semantic_receipt"],
            evaluations[1]["rows"][1]["steps"][0]["verification"],
        )
        self.assertEqual(result["upstream_cost"]["model_calls"], 9)
        self.assertEqual(result["cached_row_uses"], 9)
        self.assertEqual(result["unique_tasks"], 3)
        self.assertEqual(result["independent_sample_increment"], 0)
        self.assertFalse(result["selection_changed"])
        self.assertFalse(result["online_routed_execution_performed"])
        self.assertEqual(result["model_capacity"]["matched_rank4"], None)

    def test_wrong_model_prompt_panel_and_output_bindings_are_rejected(self):
        records, features, evaluations = material()
        report = {"arms": {"single": predictions(features, [0, 0, 0])}}
        with self.assertRaisesRegex(ValueError, "panel digest"):
            readout(
                report,
                evaluations,
                MODELS,
                records,
                features,
                expected_panel_digest="f" * 64,
            )
        with self.assertRaisesRegex(ValueError, "model order"):
            readout(
                report,
                evaluations[::-1],
                MODELS,
                records,
                features,
                expected_panel_digest=digest(records),
            )
        changed = copy.deepcopy(evaluations)
        step = changed[0]["rows"][0]["steps"][0]
        step["output"]["answer"] = "different answer"
        step["receipt_sha256"] = digest(
            {key: value for key, value in step.items() if key != "receipt_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "input or answer"):
            readout(
                report,
                changed,
                MODELS,
                records,
                features,
                expected_panel_digest=digest(records),
            )
        features[0]["observation_digest"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "feature provenance"):
            readout(
                report,
                evaluations,
                MODELS,
                records,
                features,
                expected_panel_digest=digest(records),
            )

    def test_claimed_success_without_business_checks_is_rejected(self):
        records, features, evaluations = material()
        step = evaluations[0]["rows"][0]["steps"][0]
        verification = step["verification"]
        verification["result"]["result"]["controls_rejected"] = 0
        verification["receipt_sha256"] = digest(
            {
                key: value
                for key, value in verification.items()
                if key not in ("receipt_sha256", "success")
            }
        )
        step["receipt_sha256"] = digest(
            {key: value for key, value in step.items() if key != "receipt_sha256"}
        )
        with self.assertRaisesRegex(ValueError, "executed business checks"):
            routing_targets(
                records,
                evaluations,
                MODELS,
                features,
                expected_panel_digest=digest(records),
            )

    def test_optional_rank_evidence_is_bound_to_actual_model_and_plan(self):
        records, features, evaluations = material()
        report = {"arms": {"single": predictions(features, [0, 0, 0])}}
        evidence = []
        for model in MODELS:
            plan = {"training": {"rank": 4}}
            evidence.append(
                {
                    "plan": plan,
                    "training": {
                        "status": "COMPLETE",
                        "candidate_model_digest": model,
                        "parent_model_digest": "e" * 64,
                        "plan_digest": digest(plan),
                        "trainable_parameters": 230400,
                    },
                }
            )
        result = readout(
            report,
            evaluations,
            MODELS,
            records,
            features,
            expected_panel_digest=digest(records),
            capacity_evidence=evidence,
        )
        self.assertTrue(result["model_capacity"]["matched_rank4"])
        evidence[1]["training"]["candidate_model_digest"] = MODELS[0]
        with self.assertRaisesRegex(ValueError, "capacity training binding"):
            readout(
                report,
                evaluations,
                MODELS,
                records,
                features,
                expected_panel_digest=digest(records),
                capacity_evidence=evidence,
            )


if __name__ == "__main__":
    unittest.main()
