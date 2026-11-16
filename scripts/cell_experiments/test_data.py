"""Integrity tests use explicitly authored development records, not real users."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from cell_experiments import data


def record(number=1, split="train"):
    item = {
        "schema": data.SCHEMA,
        "record_id": f"test-{number}",
        "task_id": f"task-{number}",
        "lineage_id": f"lineage-{number}",
        "family_id": f"family-{number}",
        "project_id": f"project-{number}",
        "source_id": f"source-{number}",
        "teacher_id": None,
        "observed_at": number * 100,
        "available_at": number * 100 + 1,
        "split": split,
        "origin_kind": "curated_development",
        "exposure": "development",
        "authorization": {
            "training_allowed": True,
            "evaluation_allowed": True,
            "rights_basis": "authored unit-test fixture",
            "scope": "integrity test",
        },
        "source": {
            "repository": "fixture",
            "revision": None,
            "path": f"fixture/{number}",
            "sha256": data.digest({"unit_test": number}),
        },
        "task": {
            "input": f"Return JSON value {number}.\nPreserve this input exactly.",
            "verifier": {
                "name": "json_artifact",
                "version": "1",
                "parameters": {"expected": {"value": number}},
            },
        },
        "final_answer": json.dumps({"value": number}),
        "trajectory": [
            {
                "index": 0,
                "actor": "environment",
                "kind": "observation",
                "content": "read fixture",
                "executed": False,
                "receipt_sha256": None,
            },
            {
                "index": 1,
                "actor": "curator",
                "kind": "action",
                "content": "construct JSON artifact",
                "executed": False,
                "receipt_sha256": None,
            },
        ],
    }
    receipt = data.verify_answer(item, item["final_answer"])
    item["verified_outcome"] = {
        "success": receipt["success"],
        "receipt_sha256": receipt["receipt_sha256"],
        "verifier_name": "json_artifact",
        "verifier_version": "1",
    }
    return item


class DataIntegrityTests(unittest.TestCase):
    def test_exact_sft_input_and_observation_mask(self):
        item = record()
        before = copy.deepcopy(item)
        final = data.build_sft_examples([item])[0]
        trace = data.build_sft_examples([item], "trajectory")[0]
        self.assertEqual(item, before)
        self.assertEqual((final["input"], trace["input"]), (item["task"]["input"],) * 2)
        self.assertEqual(final["target_text"], item["final_answer"])
        self.assertEqual([s["train"] for s in trace["segments"]], [False, True, True])

    def test_eval_data_and_unauthorized_or_failed_data_cannot_train(self):
        for case in ("selection", "confirmation", "unauthorized", "failed"):
            item = record()
            if case in data.SPLITS:
                item["split"] = case
            elif case == "unauthorized":
                item["authorization"]["training_allowed"] = False
            else:
                item["verified_outcome"]["success"] = False
            with self.subTest(case=case), self.assertRaises(ValueError):
                data.build_sft_examples([item])

    def test_related_families_sources_inputs_never_cross_split(self):
        for field in (
            "family_id",
            "lineage_id",
            "source_id",
            "task_id",
            "bytes",
            "input",
        ):
            left, right = record(1), record(2, "selection")
            if field == "bytes":
                right["source"]["sha256"] = left["source"]["sha256"]
            elif field == "input":
                right["task"]["input"] = left["task"]["input"]
            else:
                right[field] = left[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                data.validate_records([left, right])

    def test_curated_records_cannot_be_promoted_to_confirmation_evidence(self):
        rows = [record(1), record(2, "selection"), record(3, "confirmation")]
        self.assertTrue(data.validate_records(rows)["time_ordered"])
        with self.assertRaises(ValueError):
            data.validate_records(rows, independent=True)
        rows[-1]["exposure"] = "unexposed"
        with self.assertRaises(ValueError):
            data.validate_records(rows)

    def test_teacher_replay_is_not_student_execution(self):
        item = record()
        event = item["trajectory"][1]
        event.update(
            actor="student",
            executed=True,
            receipt_sha256="a" * 64,
            policy_sha256="b" * 64,
            receipt_actor="teacher",
        )
        with self.assertRaisesRegex(ValueError, "teacher receipt"):
            data.validate_record(item)
        event.update(actor="teacher", executed=False)
        with self.assertRaisesRegex(ValueError, "teacher identity"):
            data.validate_record(item)

    def test_semantic_verifier_checks_actual_output_not_syntax_only(self):
        item = record()
        self.assertTrue(data.verify_answer(item, ' { "value" : 1 } ')["success"])
        for answer in (
            '{"value": 2}',
            '{"value":true}',
            '{"value":1,"value":2}',
            "NaN",
            "1e999",
        ):
            with self.subTest(answer=answer):
                self.assertFalse(data.verify_answer(item, answer)["success"])
        item["task"]["verifier"]["name"] = "unregistered"
        with self.assertRaisesRegex(ValueError, "unregistered"):
            data.verify_answer(item, "{}")

    def test_time_assignment_is_explicit_and_preserves_original(self):
        rows = [record(1), record(2), record(3)]
        assigned = data.assign_splits(rows, train_before=150, selection_before=250)
        self.assertEqual([r["split"] for r in assigned], list(data.SPLITS))
        self.assertEqual([r["split"] for r in rows], ["train"] * 3)
        rows[2]["family_id"] = rows[0]["family_id"]
        with self.assertRaises(ValueError):
            data.assign_splits(rows, train_before=150, selection_before=250)

    def test_jsonl_ingestion_rejects_duplicate_keys_and_postaction_features(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "records.jsonl"
            path.write_bytes(data.canonical(record()) + b"\n")
            self.assertEqual(data.load_records(path), [record()])
            path.write_text('{"schema":"one","schema":"two"}\n')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                data.load_records(path)
        item = record()
        item["features"] = {
            "values": [1.0],
            "binding": "a" * 64,
            "available_at": 200,
            "preaction_at": 100,
        }
        with self.assertRaisesRegex(ValueError, "post-action"):
            data.validate_record(item)


if __name__ == "__main__":
    unittest.main()
