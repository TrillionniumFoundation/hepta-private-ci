"""Real repository fixture execution tests; scripted Cells are not model evidence."""

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from .. import data, repo_execution
from ..test_data import record as sample_record
from .circuit_contract import Budget, CellSpec, Graph, digest
from .circuit_runtime import run_graph


def patch(assertions):
    return json.dumps(
        {"edits": [{"path": "test_contract.py", "old": "    pass", "new": assertions}]}
    )


WEAK = patch('    assert subject({"calls": 0}, "calls") is not None')
WRONG = patch('    assert subject({"calls": 0}, "calls") == {"calls": 9}')
STRONG = patch(
    '    assert subject({"calls": 0}, "calls") == {"calls": 1}\n'
    '    assert subject({"calls": 7}, "calls") == {"calls": 8}'
)


def task(number=1, prompt="Check counter behavior."):
    repo_execution.load_catalog()
    row = sample_record(number)
    row.pop("verified_outcome", None)
    for key in ("lineage_id", "source_id", "project_id", "family_id"):
        row[key] = "shared-scripted-circuit-engineering-fixture"
    row["task"] = {
        "input": prompt,
        "verifier": {
            "name": "repo_patch",
            "version": "1",
            "parameters": {
                "fixture_id": "A-counter",
                "fixture_sha256": data.digest(repo_execution._CATALOG["A-counter"]),
            },
        },
    }
    row["final_answer"] = STRONG
    return row


def cells():
    return {
        name: CellSpec(name, digest(name), "b" * 64, "c" * 64, "d" * 64)
        for name in ("first", "second")
    }


class ScriptedCells:
    def __init__(self, registry, mode="relay"):
        self.cells, self.mode, self.requests = registry, mode, []

    def __call__(self, cell_id, request, call_dir):
        tick = time.perf_counter()
        self.requests.append((cell_id, copy.deepcopy(request)))
        messages = request["task"]["messages"]
        payload = json.loads(messages[-1]["content"]) if len(messages) > 1 else {}
        if self.mode == "context":
            match = (cell_id == "first") == ("blue" in request["task"]["input"])
            answer = STRONG if match else WRONG
        elif cell_id == "first":
            answer = WEAK
        else:
            observed = payload.get("feedback", {})
            answer = (
                STRONG
                if (
                    payload.get("answer") == WEAK
                    and observed.get("success") is False
                    and observed.get("controls_rejected") == 0
                )
                else WRONG
            )
        return {
            "answer": answer,
            "loaded_model_digest": self.cells[cell_id].model_digest,
            "input_tokens": len(data.canonical(messages)),
            "output_tokens": len(answer),
            "elapsed_seconds": time.perf_counter() - tick,
            "input_sha256": hashlib.sha256(
                request["task"]["input"].encode()
            ).hexdigest(),
            "messages_sha256": data.digest(messages),
            "provider_kind": "scripted_business_fixture",
            "token_unit": "UTF8 bytes for CPU protocol test only",
        }


class CircuitRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cells, self.record = cells(), task()
        self.graph = Graph("relay", ("first", "second"))
        self.budget = Budget(
            max_input_tokens_per_call=4096, max_output_tokens_per_call=1024
        )

    def run_case(self, name, **kwargs):
        generate = ScriptedCells(self.cells)
        result = run_graph(
            self.record,
            self.graph,
            self.cells,
            self.budget,
            generate,
            data.verify_answer,
            self.root / name,
            **kwargs,
        )
        return generate, result

    def test_fresh_business_execution_uses_both_messages_and_excludes_gold(self):
        generated, result = self.run_case("main")
        self.assertFalse(result["first_success"])
        self.assertTrue(result["success"])
        self.assertEqual(result["cost"]["business_executions"], 2)
        self.assertEqual(result["nodes"][-1]["business"]["controls_rejected"], 2)
        for _, request in generated.requests:
            self.assertEqual(set(request), {"record_id", "task"})
            self.assertEqual(set(request["task"]), {"input", "messages"})
            self.assertNotIn(STRONG, data.canonical(request).decode())
        self.assertEqual(result["nodes"][-1]["incoming_edges"], ["answer", "feedback"])
        self.assertTrue((self.root / "main/node-1/VERIFICATION.json").is_file())

    def test_each_edge_is_removed_from_actual_model_input(self):
        for edge in ("answer", "feedback"):
            with self.subTest(edge=edge):
                generated, result = self.run_case("remove-" + edge, drop_edge=edge)
                payload = json.loads(
                    generated.requests[-1][1]["task"]["messages"][-1]["content"]
                )
                self.assertNotIn(edge, payload)
                self.assertFalse(result["success"])
                self.assertEqual(result["cost"]["model_calls"], 2)
                if edge == "answer":
                    self.assertNotIn("subject", json.dumps(payload))

    def test_first_business_success_survives_later_failure_and_both_calls_are_paid(
        self,
    ):
        generated = ScriptedCells(self.cells, mode="context")
        result = run_graph(
            task(prompt="blue counter task"),
            self.graph,
            self.cells,
            self.budget,
            generated,
            data.verify_answer,
            self.root / "retain-first",
        )
        self.assertEqual(
            [node["business"]["business_success"] for node in result["nodes"]],
            [True, False],
        )
        self.assertEqual(
            (result["success"], result["final_slot"], result["last_executed_slot"]),
            (True, 0, 1),
        )
        self.assertEqual(
            result["final_answer_sha256"], hashlib.sha256(STRONG.encode()).hexdigest()
        )
        self.assertEqual(
            (
                len(generated.requests),
                result["cost"]["model_calls"],
                result["cost"]["verifier_calls"],
                result["cost"]["business_executions"],
            ),
            (2, 2, 2, 2),
        )
        self.assertEqual(
            result["output_selection"], "earliest_business_success_else_last_surviving"
        )

    def test_each_cell_is_really_skipped_and_unused_budget_is_not_cost(self):
        for cell_id in self.cells:
            with self.subTest(cell=cell_id):
                generated, result = self.run_case(
                    "remove-" + cell_id, drop_cell=cell_id
                )
                self.assertNotIn(cell_id, [item[0] for item in generated.requests])
                self.assertEqual(
                    (
                        result["cost"]["model_calls"],
                        result["cost"]["verifier_calls"],
                        result["cost"]["unused_model_call_opportunities"],
                    ),
                    (1, 1, 1),
                )
                self.assertFalse(result["success"])
        generated = ScriptedCells(self.cells)
        result = run_graph(
            self.record,
            Graph("one-cell", ("first", "first")),
            self.cells,
            self.budget,
            generated,
            data.verify_answer,
            self.root / "remove-only",
            drop_cell="first",
        )
        self.assertEqual(
            (
                generated.requests,
                result["success"],
                result["final_slot"],
                result["cost"]["model_calls"],
                result["cost"]["verifier_calls"],
            ),
            ([], False, None, 0, 0),
        )

    def test_compatibility_and_model_identity_fail_closed_with_original_output(self):
        changed = dict(self.cells)
        changed["second"] = replace(changed["second"], bundle_digest="f" * 64)
        generated = ScriptedCells(changed)
        with self.assertRaisesRegex(ValueError, "bundle"):
            run_graph(
                self.record,
                self.graph,
                changed,
                self.budget,
                generated,
                data.verify_answer,
                self.root / "bad-bundle",
            )
        self.assertEqual(generated.requests, [])
        generated = ScriptedCells(self.cells)

        def wrong(cell_id, request, directory):
            return {
                **generated(cell_id, request, directory),
                "loaded_model_digest": "e" * 64,
            }

        with self.assertRaisesRegex(ValueError, "loaded model"):
            run_graph(
                self.record,
                self.graph,
                self.cells,
                self.budget,
                wrong,
                data.verify_answer,
                self.root / "wrong-model",
            )
        failure = json.loads((self.root / "wrong-model/FAILED.json").read_text())
        self.assertEqual(
            (failure["model_calls_dispatched"], failure["verifier_calls_dispatched"]),
            (1, 0),
        )
        self.assertTrue((self.root / "wrong-model/node-0/OUTPUT.json").is_file())

    def test_verifier_parameters_and_feedback_implementation_are_bound(self):
        generated = ScriptedCells(self.cells)

        def wrong(record, answer):
            value = data.verify_answer(record, answer)
            value["parameters_sha256"] = "e" * 64
            body = {
                key: item
                for key, item in value.items()
                if key not in ("success", "receipt_sha256")
            }
            value["receipt_sha256"] = data.digest(body)
            return value

        with self.assertRaisesRegex(ValueError, "task identity"):
            run_graph(
                self.record,
                self.graph,
                self.cells,
                self.budget,
                generated,
                wrong,
                self.root / "wrong-verifier",
            )
        self.assertTrue(
            (self.root / "wrong-verifier/node-0/VERIFICATION.json").is_file()
        )
        with self.assertRaisesRegex(ValueError, "bound stable feedback"):
            self.run_case(
                "unsafe-feedback", feedback_fn=lambda value: json.dumps(value)
            )


if __name__ == "__main__":
    unittest.main()
