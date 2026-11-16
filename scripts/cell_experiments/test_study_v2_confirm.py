"""Mechanical coordinator checks, never additional model-training observations."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import coding_sft, data, repo_execution, repo_interaction_v2, repo_tasks
from . import study_v2_confirm as coordinator, study_v2_evidence as evidence
from .test_circuit_task_readout_v2 import material, MODELS


class StudyCoordinatorTests(unittest.TestCase):
    def test_wrong_external_selection_hash_never_opens_c(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coding_sft.write_new(root / "B_SELECTION.json", {"status": "COMPLETE"})
            with patch.object(repo_execution, "unlock_confirmation") as unlock:
                with self.assertRaisesRegex(ValueError, "changed"):
                    coordinator.confirm(root, "0" * 64)
                unlock.assert_not_called()

    def test_changed_pre_c_material_never_opens_c(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = {"source": "mechanical-fixture"}
            path = root / "model.bin"
            path.write_bytes(b"before")
            selection = {
                "status": "COMPLETE",
                "freeze_digest": data.digest(frozen),
                "bindings": {"model.bin": coding_sft.file_hash(path)},
            }
            coding_sft.write_new(root / "B_SELECTION.json", selection)
            pin = coding_sft.file_hash(root / "B_SELECTION.json")
            path.write_bytes(b"changed")
            with (
                patch.object(coordinator.study, "guard", return_value=frozen),
                patch.object(repo_execution, "unlock_confirmation") as unlock,
            ):
                with self.assertRaisesRegex(ValueError, "changed"):
                    coordinator.confirm(root, pin)
                unlock.assert_not_called()

    def test_adoption_uses_source_macro_and_strictly_beats_both_baselines(self):
        def rows(arm, values):
            return [
                {"arm": arm, "source_id": source, "success": value}
                for source, value in values
            ]

        parent = rows("parent", [("x", True), ("y", False)])
        retrieval = rows("retrieval", [("x", False), ("y", True)])
        candidate = rows("candidate", [("x", True)] * 3 + [("y", False)])
        result = evidence.choose_e6({"rows": parent + retrieval + candidate}, True)
        self.assertEqual(
            result["scores"], {"parent": 0.5, "retrieval": 0.5, "candidate": 0.5}
        )
        self.assertEqual(result["decision"], "NO_UPDATE")
        candidate[-1]["success"] = True
        self.assertEqual(
            evidence.choose_e6({"rows": parent + retrieval + candidate}, True)[
                "decision"
            ],
            "ADOPTED",
        )
        retrieval[0]["success"] = True
        self.assertEqual(
            evidence.choose_e6({"rows": parent + retrieval + candidate}, True)[
                "decision"
            ],
            "NO_UPDATE",
        )

    def test_heldout_all_failed_targets_are_fallback_not_task_success(self):
        records, features, evaluations = material(
            "selection", successes=[[False] * 3 for _ in range(3)]
        )
        original = copy.deepcopy(features)
        labelled = evidence.heldout_targets(records, evaluations, MODELS, features)
        self.assertEqual([row["target"] for row in labelled], [2, 2, 2])
        self.assertEqual(features, original)
        self.assertEqual(
            sum(
                row["first_attempt_success"]
                for report in evaluations
                for row in report["rows"]
            ),
            0,
        )

    def test_actual_semantic_receipts_and_saved_history_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_tasks.build("open", root / "data")
            record = next(
                r
                for r in data.load_records(root / "data/records.jsonl")
                if r["record_id"] == "B-stable-frame"
            )
            model = {"scope": "mechanical fixture, not actual model inference"}
            identity = data.digest(model)
            first = json.loads(record["trajectory"][0]["content"])
            outputs = [json.dumps(first), record["final_answer"]]
            messages = copy.deepcopy(record["task"]["messages"])
            directory = root / "evaluation/B/example/0"
            steps = []
            for number, answer in enumerate(outputs):
                request = {
                    "record_id": record["record_id"],
                    "task": {
                        "input": record["task"]["input"],
                        "messages": copy.deepcopy(messages),
                    },
                }
                output = {
                    "answer": answer,
                    "loaded_model_digest": identity,
                    "input_sha256": hashlib.sha256(
                        record["task"]["input"].encode()
                    ).hexdigest(),
                    "input_tokens": 10,
                    "output_tokens": 12,
                }
                verification = data.verify_answer(record, answer)
                feedback = repo_interaction_v2.feedback(verification)
                step = {
                    "number": number,
                    "output": output,
                    "verification": verification,
                    "feedback": feedback,
                    "executed": verification["result"]["executed"],
                }
                step["receipt_sha256"] = data.digest(step)
                for prefix, item in (
                    ("request", request),
                    ("output", output),
                    ("step", step),
                ):
                    coding_sft.write_new(directory / f"{prefix}-{number}.json", item)
                steps.append(step)
                messages.extend(
                    [
                        {"role": "assistant", "content": answer},
                        {"role": "tool", "content": feedback},
                    ]
                )
            row = {
                **{
                    k: record[k]
                    for k in ("record_id", "task_id", "source_id", "lineage_id")
                },
                "task_digest": data.digest(record),
                "original_input_sha256": data.digest(record["task"]["input"]),
                "steps": steps,
                "first_attempt_success": False,
                "success": True,
            }
            report = {
                "schema": "hepta.repository-evaluation.v2",
                "status": "COMPLETE",
                "model_digest": identity,
                "tasks": 1,
                "rows": [row],
                "maximum_attempts": 2,
                "successes": 1,
                "first_attempt_successes": 0,
                "cost": {"model_calls": 2, "input_tokens": 20, "output_tokens": 24},
            }
            coding_sft.write_new(directory.parent / "EVALUATION.json", report)
            checked = evidence.checked_evaluation(
                root, "example", "B", [record], {"example": model}
            )
            self.assertEqual(checked, json.loads(data.canonical(report)))
            wrong = evidence.study.read(directory / "request-1.json")
            wrong["task"]["messages"] = wrong["task"]["messages"][:2]
            (directory / "request-1.json").write_text(json.dumps(wrong))
            with self.assertRaisesRegex(ValueError, "request"):
                evidence.checked_evaluation(
                    root, "example", "B", [record], {"example": model}
                )


if __name__ == "__main__":
    unittest.main()
