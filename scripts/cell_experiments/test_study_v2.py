"""Join actual repository-verifier receipts to routing with fixture predictions.

Predictor outputs and token counts are test fixtures, not model-run evidence.
The semantic checker really executes the pinned A function and its controls.
"""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import data, repo_execution, repo_interaction_v2, study_v2_evidence
from .circuit_task_bindings_v2 import MODEL_ORDER
from .circuit_task_readout_v2 import routing_targets
from .test_data import record


class PredictorFixture:
    def __init__(self, identity, answer):
        self.model_digest, self.answers = identity, iter(("", answer))
        self.requests = []

    def predict(self, request):
        self.requests.append(copy.deepcopy(request))
        return {
            "answer": next(self.answers),
            "loaded_model_digest": self.model_digest,
            "input_sha256": hashlib.sha256(
                request["task"]["input"].encode()
            ).hexdigest(),
            "input_tokens": 3,
            "output_tokens": 2,
            "hit_output_limit": False,
            "elapsed_seconds": 0.0,
        }

    def close(self):
        pass


class StudyIntegrationTests(unittest.TestCase):
    def test_actual_business_receipts_keep_first_attempt_separate_from_recovery(self):
        fixture = next(
            f
            for f in repo_execution.load_catalog()["fixtures"]
            if f["fixture_id"] == "A-counter"
        )
        item = record()
        item["task"]["input"] = "Complete the counter contract test. 保留原始输入。"
        initial = [
            {"role": "user", "content": item["task"]["input"]},
            {"role": "tool", "content": '{"assertion_count":0}'},
        ]
        item["task"]["messages"] = initial
        item["task"]["verifier"] = {
            "name": "repo_patch",
            "version": "1",
            "parameters": {
                "fixture_id": fixture["fixture_id"],
                "fixture_sha256": data.digest(fixture),
            },
        }
        item["final_answer"] = data.canonical(
            {
                "edits": [
                    {
                        "path": "test_contract.py",
                        "old": "    pass",
                        "new": '    assert subject({"calls": 0}, "calls") == {"calls": 1}\n    assert subject({"calls": 7}, "calls") == {"calls": 8}',
                    }
                ]
            }
        ).decode()
        item["verified_outcome"].update(
            verifier_name="repo_patch", verifier_version="1"
        )
        models = {
            name: {"unit_test_model_slot": slot}
            for slot, name in enumerate(MODEL_ORDER)
        }
        identities = [data.digest(models[name]) for name in MODEL_ORDER]
        features = [
            {
                "task_id": item["task_id"],
                "source_id": item["source_id"],
                "project_id": item["project_id"],
                "lineage_id": item["lineage_id"],
                "observation_digest": data.digest(item["task"]["input"]),
                "feature_binding_digest": "b" * 64,
                "features": [0.25, -0.5],
            }
        ]
        reports = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, identity in zip(MODEL_ORDER, identities):
                predictor = PredictorFixture(identity, item["final_answer"])
                with patch.object(
                    repo_interaction_v2.coding_sft,
                    "load_predictor",
                    return_value=predictor,
                ):
                    report = repo_interaction_v2.evaluate(
                        models[name],
                        root,
                        [item],
                        root / "evaluation/A" / name,
                        maximum=2,
                    )
                self.assertEqual(
                    (
                        report["tasks"],
                        report["first_attempt_successes"],
                        report["successes"],
                    ),
                    (1, 0, 1),
                )
                self.assertEqual(
                    [step["executed"] for step in report["rows"][0]["steps"]],
                    [False, True],
                )
                self.assertEqual(predictor.requests[0]["task"]["messages"], initial)
                self.assertEqual(predictor.requests[1]["task"]["messages"][:2], initial)
                self.assertNotIn(
                    item["final_answer"],
                    predictor.requests[1]["task"]["messages"][-1]["content"],
                )
                self.assertEqual(
                    set(predictor.requests[1]["task"]), {"input", "messages"}
                )
                self.assertEqual(
                    study_v2_evidence.checked_evaluation(
                        root, name, "A", [item], models
                    ),
                    data._parse(data.canonical(report)),
                )
                reports.append(report)
            joined = routing_targets(
                [item],
                reports,
                identities,
                features,
                expected_panel_digest=data.digest([item]),
            )
            self.assertEqual(
                (
                    joined["rows"][0]["target"],
                    joined["receipt"]["observed_first_attempt_oracle_ceiling"],
                ),
                (2, 0.0),
            )
            self.assertEqual(
                [
                    row["cost"]["model_calls"]
                    for row in joined["receipt"]["upstream_evaluations"]
                ],
                [2, 2, 2],
            )
            forged = copy.deepcopy(reports)
            step = forged[0]["rows"][0]["steps"][0]
            step["executed"] = True
            step["receipt_sha256"] = data.digest(
                {k: v for k, v in step.items() if k != "receipt_sha256"}
            )
            with self.assertRaisesRegex(ValueError, "attempt summary differs"):
                routing_targets(
                    [item],
                    forged,
                    identities,
                    features,
                    expected_panel_digest=data.digest([item]),
                )


if __name__ == "__main__":
    unittest.main()
