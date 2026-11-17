"""Real SQLite behavior with explicitly scripted predictors, never model evidence."""

import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from . import data, sqlite_agent_probe_v3 as probe


class ScriptedPredictor:
    """Test action source; token usage is unknown and no model is loaded."""

    model_digest = "a" * 64

    def __init__(self, answers, wrong_digest=False):
        self.answers = {key: iter(values) for key, values in answers.items()}
        self.requests = []
        self.wrong_digest = wrong_digest

    def predict(self, request):
        self.requests.append(copy.deepcopy(request))
        return {
            "answer": next(self.answers[request["record_id"]]),
            "loaded_model_digest": "b" * 64 if self.wrong_digest else self.model_digest,
            "input_sha256": hashlib.sha256(
                request["task"]["input"].encode()
            ).hexdigest(),
            "messages_sha256": data.digest(request["task"]["messages"]),
            "input_tokens": None,
            "output_tokens": None,
            "actor_kind": "scripted",
            "hit_output_limit": False,
        }


class SQLiteAgentProbeV3Tests(unittest.TestCase):
    def test_format_and_unstaged_apply_recover_through_real_feedback(self):
        task_id = "dev-sqlite-lost-reply-01"
        answers = [
            "inspect",
            '"inspect"',
            '"apply"',
            '"stage"',
            '"apply"',
            '"inspect"',
            '"stop"',
        ]
        predictor = ScriptedPredictor({task_id: answers})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            result = probe.run_task(
                predictor, task_id, directory, actor_kind="scripted"
            )
            self.assertEqual(
                result["recovery"],
                {
                    "format_error_then_success": True,
                    "observed_unstaged_apply_then_success": True,
                    "actor_kind": "scripted",
                    "automatic_repair": False,
                },
            )
            self.assertTrue(result["success"])
            self.assertEqual(
                [step["output"]["answer"] for step in result["steps"]], answers
            )
            self.assertEqual(result["steps"][0]["parse_error"], "invalid_json")
            self.assertFalse(
                result["steps"][0]["sqlite_receipt"]["execution_performed"]
            )
            self.assertEqual(
                result["steps"][2]["sqlite_receipt"]["execution_summary"][
                    "applied_effects_delta"
                ],
                0,
            )
            for index, request in enumerate(predictor.requests):
                self.assertEqual(set(request), {"record_id", "task"})
                self.assertEqual(set(request["task"]), {"input", "messages"})
                retained = json.loads((directory / f"request-{index}.json").read_text())
                self.assertEqual(retained, request)
                raw = json.loads((directory / f"output-{index}.json").read_text())
                self.assertEqual(raw, result["steps"][index]["output"])
                if index:
                    previous = predictor.requests[index - 1]["task"]["messages"]
                    self.assertEqual(
                        request["task"]["messages"],
                        previous
                        + [
                            {"role": "assistant", "content": answers[index - 1]},
                            {
                                "role": "tool",
                                "content": result["steps"][index - 1]["feedback"],
                            },
                        ],
                    )
            with sqlite3.connect(directory / "destination/destination.db") as database:
                rows = list(database.execute("SELECT value,revision FROM items"))
                effects = list(database.execute("SELECT key FROM effects"))
            self.assertEqual(
                (rows, effects), ([("v3-development-receipt-0", 1)], [("0",)])
            )
            self.assertEqual(result["cost"]["sqlite_primitive_calls"], 5)
            self.assertEqual(result["cost"]["scripted_predictor_calls"], 7)
            self.assertEqual(result["cost"]["model_calls_attempted"], 0)
            self.assertIsNone(result["cost"]["input_tokens"])
            self.assertIsNone(result["cost"]["monetary_cost"])

    def test_twelve_bad_decisions_do_not_execute_or_get_repaired(self):
        task_id = "dev-sqlite-lost-reply-01"
        malformed = [
            '{"action":"inspect"}',
            '```json\n"apply"\n```',
            '"stage" "apply"',
            '"ensure"',
        ] * 3
        predictor = ScriptedPredictor({task_id: malformed})
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            result = probe.run_task(
                predictor, task_id, directory, actor_kind="scripted"
            )
            self.assertEqual(
                (result["decisions"], result["terminal_reason"], result["success"]),
                (12, "decision_budget_exhausted", False),
            )
            self.assertEqual(result["cost"]["sqlite_primitive_calls"], 0)
            self.assertEqual(
                [step["output"]["answer"] for step in result["steps"]], malformed
            )
            self.assertTrue(all(step["parse_error"] for step in result["steps"]))
            self.assertFalse(
                any(
                    step["sqlite_receipt"]["execution_performed"]
                    for step in result["steps"]
                )
            )
            with sqlite3.connect(directory / "destination/destination.db") as database:
                self.assertEqual(
                    list(database.execute("SELECT value,revision FROM items")),
                    [("old", 0)],
                )
            with self.assertRaises(ValueError):
                probe.run_task(
                    predictor,
                    task_id,
                    Path(temporary) / "over-budget",
                    actor_kind="scripted",
                    maximum=13,
                )

    def test_mismatched_model_return_is_retained_without_effect(self):
        task_id = "dev-sqlite-lost-reply-01"
        predictor = ScriptedPredictor({task_id: ['"stage"']}, wrong_digest=True)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            result = probe.run_task(
                predictor, task_id, directory, actor_kind="scripted"
            )
            raw = json.loads((directory / "output-0.json").read_text())
            self.assertEqual(raw["loaded_model_digest"], "b" * 64)
            self.assertEqual(
                result["steps"][0]["predictor_contract_error"],
                "loaded_model_digest_mismatch",
            )
            self.assertFalse(result["model_binding_valid"])
            self.assertFalse(result["success"])
            self.assertEqual(result["cost"]["sqlite_primitive_calls"], 0)
            self.assertEqual(result["cost"]["predictor_calls_returned"], 1)
            self.assertEqual(
                result["sqlite_result"]["business_result"]["write_transactions"], 0
            )

    def test_panel_uses_three_real_destinations_with_one_source_lineage(self):
        scripted = {
            "dev-sqlite-lost-reply-01": [
                "inspect",
                "stage",
                "apply",
                "apply",
                "inspect",
                "stop",
            ],
            "dev-sqlite-prestaged-01": [
                "inspect",
                "apply",
                "inspect",
                "stage",
                "apply",
                "apply",
                "inspect",
                "stop",
            ],
            "dev-sqlite-partial-01": ["inspect", "stage", "apply", "inspect", "stop"],
        }
        predictor = ScriptedPredictor(
            {
                key: [json.dumps(action) for action in actions]
                for key, actions in scripted.items()
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "panel"
            result = probe.run_panel(predictor, directory, actor_kind="scripted")
            self.assertEqual(
                (
                    result["tasks"],
                    result["successes"],
                    result["new_independent_sources"],
                ),
                (3, 3, 0),
            )
            self.assertEqual(len({row["lineage_id"] for row in result["rows"]}), 1)
            self.assertTrue(
                all(row["cost"]["model_calls_attempted"] == 0 for row in result["rows"])
            )
            self.assertTrue(
                all(
                    row["sqlite_result"]["business_result"]["duplicate_effects"] == 0
                    for row in result["rows"]
                )
            )
            self.assertTrue(all(row["errors"] == [] for row in result["rows"]))
            with sqlite3.connect(
                directory / "dev-sqlite-partial-01/destination/destination.db"
            ) as database:
                self.assertEqual(
                    list(
                        database.execute(
                            "SELECT item_key,revision FROM items ORDER BY item_key"
                        )
                    ),
                    [("0", 0), ("1", 1)],
                )


if __name__ == "__main__":
    unittest.main()
