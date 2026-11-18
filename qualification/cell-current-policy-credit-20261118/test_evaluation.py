"""Check positive-first regressions and reject B2 opening before weight freeze."""

import copy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cell_experiments import data
from cell_experiments.coding_sft import file_hash, write_new
import evaluate


class EvaluationTests(unittest.TestCase):
    def test_positive_first_is_executed_again_and_regression_is_retained(self):
        class Predictor:
            calls = []
            model_digest = "pinned"
            generation_digest = "generation"
            device_report = {"device": "fixture"}

            def __init__(self, *args):
                pass

            def predict(self, request):
                self.calls.append(copy.deepcopy(request))
                return {"loaded_model_digest": self.model_digest,
                        "messages_sha256": data.digest(request["task"]["messages"]),
                        "answer": "pass" if len(self.calls) == 1 else "fail",
                        "input_tokens": len(self.calls), "output_tokens": 1,
                        "wall_seconds": 0.1, "hit_output_limit": False}

            def close(self):
                pass

        def require(condition, message):
            if not condition:
                raise ValueError(message)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "evaluation").mkdir()
            record = {"record_id": "r", "task_id": "t", "task": {"input": "task"}}
            write_new(root / "PARENT_MODEL.json", {})
            write_new(root / "evaluation/PANELS.json", {"A_retention": [record]})
            weights = {"frozen": True}
            write_new(root / "evaluation/FREEZE.json", {
                "panels_sha256": file_hash(root / "evaluation/PANELS.json"),
                "weights_frozen_digest": data.digest(weights),
                "evaluation_source_sha256": file_hash(Path(evaluate.__file__)),
                "models": {"NoUpdate": "pinned"}})
            args = SimpleNamespace(output=root, artifact_root=root, old_code_root=root,
                                   candidate_root=root)
            supplied = SimpleNamespace(digest=data.digest, _parse=data._parse,
                                       verify_answer=lambda row, answer: {"success": answer == "pass"})
            replacements = {"credit": SimpleNamespace(require=require, matched=SimpleNamespace(Predictor=Predictor)),
                            "data": supplied, "write_new": write_new, "file_hash": file_hash,
                            "require_prepared": lambda row: [{"role": "user", "content": row["task"]["input"]}],
                            "feedback": lambda result: json.dumps(result, sort_keys=True)}
            with patch.dict(evaluate.__dict__, replacements):
                result = evaluate.evaluate(args, "NoUpdate", weights)
            self.assertEqual(len(Predictor.calls), 2)
            self.assertEqual([row["role"] for row in Predictor.calls[1]["task"]["messages"]],
                             ["user", "assistant", "tool"])
            self.assertEqual(result["by_panel"]["A_retention"], {
                "tasks": 1, "first": 1, "last": 0, "selected": 1, "recovered": 0, "regressed": 1})
            self.assertEqual(result["cost"]["model_calls"], 2)
            self.assertTrue((root / "evaluation/NoUpdate/A_retention/0/OUTPUT-1.json").exists())

    def test_incomplete_weights_reject_before_any_b2_material_is_opened(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_new(root / "WEIGHTS_FROZEN.json", {"status": "INCOMPLETE"})
            write_new(root / "FREEZE.json", {})
            args = SimpleNamespace(old_code_root=Path(__file__).resolve().parents[2],
                candidate_root=Path(__file__).resolve().parent, output=root,
                b2_loader=root / "must-not-be-opened.py", b2_directory=root / "must-not-be-opened")
            with self.assertRaisesRegex(ValueError, "both frozen fits required"):
                evaluate.boot(args)


if __name__ == "__main__":
    unittest.main()
