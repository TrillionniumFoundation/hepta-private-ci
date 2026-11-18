"""Real verifier fixtures for added controls; scripted calls are not model evidence."""

import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from .. import data
from .circuit_contract import Budget, CellSpec, Graph, digest
from .circuit_controls_v4 import (
    evaluate_controls,
    run_extended_circuit,
    select_static,
    task_random_graph,
)
from .circuit_router import FrozenRouter, RouterPlan
from .test_circuit_runtime import STRONG, WEAK, WRONG, task


class CircuitControlTests(unittest.TestCase):
    def test_explicit_pool_source_mismatch_fails_before_any_generation(self):
        instances = []

        class PoolFixture:
            def __init__(self, manifests, root):
                self.closed = False
                instances.append(self)

            def snapshot(self):
                return {"inventory": {"source_sha256": "a" * 64}}

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "candidate"
            with self.assertRaisesRegex(ValueError, "frozen pool source differs"):
                run_extended_circuit(
                    {},
                    {
                        mode: {}
                        for mode in (
                            "final_answer",
                            "trajectory",
                            "controlled_correction",
                        )
                    },
                    Path(temp),
                    {"E4": {}, "comparison_digest": "b" * 64},
                    directory,
                    "c" * 64,
                    pool_type=PoolFixture,
                    expected_pool_source_sha256="d" * 64,
                )
            self.assertEqual(len(instances), 1)
            self.assertTrue(instances[0].closed)
            self.assertEqual(
                json.loads((directory / "POOL_BINDING.json").read_text())[
                    "source_sha256"
                ],
                "a" * 64,
            )

    def run_fixture(self, first, last, selected="tf", mismatch_route=False):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name) / "controls"
        cells = {
            cell: CellSpec(cell, digest(cell), "b" * 64, "c" * 64, "d" * 64)
            for cell in ("F", "T", "C")
        }
        budget = Budget(max_input_tokens_per_call=4096, max_output_tokens_per_call=1024)
        graphs = [Graph("ff", ("F", "F")), Graph("tf", ("T", "F"))]
        if selected == "tf_none":
            graphs.append(Graph("tf_none", ("T", "F"), ()))
        record = {
            "schema": "hepta.prompt-graph-router.v4",
            "graphs": [asdict(graph) for graph in graphs],
            "cell_registry_digest": digest(
                {key: asdict(value) for key, value in sorted(cells.items())}
            ),
            "budget_digest": digest(asdict(budget)),
            "plan": asdict(RouterPlan("e" * 64)),
            "weights": [
                [0.0] * 16 + [float(graph.graph_id == selected)] for graph in graphs
            ],
        }
        router = FrozenRouter(record, digest(record))
        row = task()
        requests = []
        self.requests = requests
        route = router.route(row)[1]
        if mismatch_route:
            route["features_digest"] = "a" * 64

        def generate(cell, request, call_dir):
            self.assertTrue((directory / "PLAN.json").is_file())
            requests.append((cell, copy.deepcopy(request)))
            messages = request["task"]["messages"]
            answer = first if len(messages) == 1 else last
            return {
                "answer": answer,
                "loaded_model_digest": cells[cell].model_digest,
                "input_tokens": len(data.canonical(messages)),
                "output_tokens": len(answer),
                "elapsed_seconds": 0.0,
                "messages_sha256": data.digest(messages),
                "provider_kind": "scripted verifier fixture, not a model",
            }

        result = evaluate_controls(
            [row],
            cells,
            budget,
            generate,
            data.verify_answer,
            directory,
            router=router,
            static_graph=graphs[0],
            original_routes=[route],
            random_seed=1729,
            comparison_digest="e" * 64,
            protocol_digest="f" * 64,
        )
        return result, requests, json.loads((directory / "PLAN.json").read_text())

    def test_singles_and_identity_replacement_keep_two_feedback_calls(self):
        result, requests, plan = self.run_fixture(WEAK, STRONG)
        self.assertEqual([cell for cell, _ in requests[:4]], ["T", "T", "C", "C"])
        self.assertEqual([cell for cell, _ in requests[-2:]], ["F", "F"])
        self.assertEqual(plan["all_single_controls_to_report"], ["F", "T", "C"])
        self.assertFalse(plan["selections"][0]["identity_replacement_noop"])
        for offset in range(0, 10, 2):
            first, second = requests[offset][1], requests[offset + 1][1]
            self.assertEqual(first["task"]["input"], second["task"]["input"])
            payload = json.loads(second["task"]["messages"][-1]["content"])
            self.assertEqual(payload["answer"], WEAK)
            self.assertFalse(payload["feedback"]["success"])
            self.assertNotIn(STRONG, data.canonical(second).decode())
        for rows in result["arms"].values():
            self.assertTrue(rows[0]["behavior"]["recovery_0_to_1"])
            for key in ("model_calls", "verifier_calls", "business_executions"):
                self.assertEqual(rows[0]["cost"][key], 2)
        self.assertEqual(result["all_actual_execution_cost"]["model_calls"], 10)

    def test_first_success_retention_preserves_regression_and_paid_noop(self):
        result, requests, plan = self.run_fixture(STRONG, WRONG, selected="ff")
        self.assertEqual(len(requests), 10)
        self.assertTrue(plan["selections"][0]["identity_replacement_noop"])
        for rows in result["arms"].values():
            observed = rows[0]["behavior"]
            self.assertTrue(observed["selected_success"])
            self.assertTrue(observed["first_success"])
            self.assertFalse(observed["last_success"])
            self.assertTrue(observed["regression_1_to_0"])

    def test_static_selector_requires_exact_A_pairs_and_stable_ties(self):
        graphs = [Graph("z", ("T", "F")), Graph("a", ("F", "F"))]
        search = {
            "status": "COMPLETE",
            "router_digest": "e" * 64,
            "observations": [
                {"task_id": "A", "graph_id": graph.graph_id, "utility": 1}
                for graph in graphs
            ],
        }
        graph, receipt = select_static(search, graphs, ["A"], "e" * 64)
        self.assertEqual(graph.graph_id, "a")
        self.assertFalse(receipt["selection_uses_B"])
        invalid = copy.deepcopy(search)
        invalid["observations"][0]["task_id"] = "B"
        with self.assertRaisesRegex(ValueError, "A task/graph pairs"):
            select_static(invalid, graphs, ["A"], "e" * 64)

    def test_identity_replacement_preserves_absent_edges_and_verifier_opportunities(
        self,
    ):
        result, requests, plan = self.run_fixture(WEAK, STRONG, selected="tf_none")
        graph = plan["selections"][0]["graphs"]["replace_non_F"]
        self.assertEqual(graph["edges"], [])
        self.assertEqual(graph["path"], ["F", "F"])
        self.assertEqual(
            [len(request["task"]["messages"]) for _, request in requests[-2:]], [1, 1]
        )
        self.assertEqual(
            result["arms"]["replace_non_F"][0]["cost"]["verifier_calls"], 2
        )

    def test_random_control_is_task_bound_and_uses_shared_candidates(self):
        graphs = [Graph("ff", ("F", "F")), Graph("tf", ("T", "F"))]
        draws = [task_random_graph(graphs, 1729, "task-" + str(i)) for i in range(16)]
        self.assertEqual(
            draws,
            [task_random_graph(graphs, 1729, "task-" + str(i)) for i in range(16)],
        )
        self.assertEqual(
            len({receipt["seed_material_digest"] for _, receipt in draws}), 16
        )
        self.assertEqual({graph.graph_id for graph, _ in draws}, {"ff", "tf"})

    def test_misbound_route_is_rejected_before_any_model_call(self):
        with self.assertRaisesRegex(ValueError, "task's visible input"):
            self.run_fixture(WEAK, STRONG, mismatch_route=True)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
