"""Conditional route learning and complete intervention execution on real fixtures."""

import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from .. import data
from .circuit_contract import Budget, Graph, digest
from .circuit_router import FrozenRouter, RouterPlan, fit_router
from .circuit_runtime import run_graph
from .circuit_study import evaluate_suite
from .test_circuit_runtime import ScriptedCells, cells, task


class CircuitRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cells = cells()
        self.budget = Budget(
            max_input_tokens_per_call=4096, max_output_tokens_per_call=1024
        )
        self.records = [
            task(1, "blue " * 10 + "Check counter."),
            task(2, "red " * 10 + "Check counter."),
        ]
        self.graphs = [
            Graph("blue-route", ("first", "first")),
            Graph("red-route", ("second", "second")),
        ]
        self.plan = RouterPlan(execution_binding_digest="e" * 64, ridge=0.1)

    def fit(self):
        generated = ScriptedCells(self.cells, mode="context")
        router, report = fit_router(
            self.records,
            self.graphs,
            self.cells,
            self.budget,
            generated,
            data.verify_answer,
            self.root / "search",
            plan=self.plan,
        )
        return generated, router, report

    def test_fitted_router_is_conditional_and_never_reads_hidden_labels(self):
        generated, router, report = self.fit()
        chosen = [router.route(row)[0].graph_id for row in self.records]
        self.assertEqual(chosen, ["blue-route", "red-route"])
        self.assertEqual(
            (report["search_model_calls"], report["search_verifier_calls"]), (8, 8)
        )
        self.assertEqual(len(generated.requests), 8)
        self.assertGreater(report["router_parameter_l2"], 0)
        self.assertEqual(report["router_parameters"], 34)
        altered = copy.deepcopy(self.records[0])
        altered.update(
            final_answer="withheld different answer",
            trajectory=[],
            verified_outcome={"success": False},
            source_id="different hidden ID",
        )
        self.assertEqual(router.route(altered)[0], router.route(self.records[0])[0])

    def test_frozen_coefficients_and_A_only_search_are_enforced(self):
        _, router, _ = self.fit()
        changed = copy.deepcopy(router.record)
        changed["weights"][0][0] += 1
        with self.assertRaisesRegex(ValueError, "identity"):
            FrozenRouter(changed, router.expected_digest)
        router.record["weights"][0][0] += 1
        with self.assertRaisesRegex(ValueError, "changed after freeze"):
            router.route(self.records[0])
        bad = copy.deepcopy(self.records)
        bad[0]["split"] = "selection"
        generated = ScriptedCells(self.cells)
        with self.assertRaisesRegex(ValueError, "authorized A"):
            fit_router(
                bad,
                self.graphs,
                self.cells,
                self.budget,
                generated,
                data.verify_answer,
                self.root / "bad-search",
                plan=self.plan,
            )
        self.assertEqual(generated.requests, [])

    def test_four_arms_and_every_intervention_execute_fresh_business_checks(self):
        _, router, _ = self.fit()
        records = copy.deepcopy(self.records)
        for row in records:
            row["split"] = "selection"
        generated = ScriptedCells(self.cells, mode="context")
        changed = dict(self.cells)
        changed["first"] = replace(changed["first"], model_digest="f" * 64)
        with self.assertRaisesRegex(ValueError, "differs from frozen router"):
            evaluate_suite(
                records,
                changed,
                self.budget,
                generated,
                data.verify_answer,
                self.root / "changed-candidate",
                router=router,
                single_cell="first",
                fixed_graph=Graph("fixed", ("first", "second")),
                random_seed=1729,
                execution_binding_digest=self.plan.execution_binding_digest,
            )
        self.assertEqual(generated.requests, [])
        report = evaluate_suite(
            records,
            self.cells,
            self.budget,
            generated,
            data.verify_answer,
            self.root / "suite",
            router=router,
            single_cell="first",
            fixed_graph=Graph("fixed", ("first", "second")),
            random_seed=1729,
            execution_binding_digest=self.plan.execution_binding_digest,
            panel_scope="exposed_diagnostic",
        )
        self.assertEqual(
            set(report["arms"]), {"single", "fixed", "random_sparse", "learned_sparse"}
        )
        self.assertEqual(
            set(report["interventions"]),
            {"edge-answer", "edge-feedback", "cell-first", "cell-second"},
        )
        self.assertEqual(
            [report["summary"][arm]["model_calls"] for arm in report["arms"]], [4] * 4
        )
        self.assertEqual(report["summary"]["learned_sparse"]["successes"], 2)
        self.assertEqual(
            report["all_actual_execution_cost"]["model_calls"], len(generated.requests)
        )
        self.assertEqual(report["all_actual_execution_cost"]["business_executions"], 28)
        for name, rows in report["interventions"].items():
            self.assertEqual(len(rows), 2)
            for row in rows:
                raw = json.loads(Path(row["result_path"]).read_text())
                self.assertEqual(digest(raw), row["result_digest"])
            if name.startswith("cell-"):
                self.assertEqual(
                    sorted(row["saved_model_calls"] for row in report["paired"][name]),
                    [0, 2],
                )
        self.assertFalse(report["matched_actual_cost_claim"])
        self.assertFalse(report["scientific_qualification"])
        self.assertTrue(report["evaluation_admission"]["diagnostic_only"])
        self.assertTrue(report["evaluation_admission"]["selection_on_this_panel"])

    def test_token_overrun_keeps_raw_output_and_records_incomplete_cost(self):
        base = ScriptedCells(self.cells)

        def overrun(cell_id, request, directory):
            return {**base(cell_id, request, directory), "output_tokens": 1025}

        with self.assertRaisesRegex(ValueError, "token count"):
            run_graph(
                self.records[0],
                self.graphs[0],
                self.cells,
                self.budget,
                overrun,
                data.verify_answer,
                self.root / "overrun",
            )
        failure = json.loads((self.root / "overrun/FAILED.json").read_text())
        self.assertFalse(failure["cost_complete"])
        self.assertEqual(failure["model_calls_dispatched"], 1)
        self.assertEqual(failure["verifier_calls_dispatched"], 0)
        self.assertTrue((self.root / "overrun/node-0/OUTPUT.json").is_file())


if __name__ == "__main__":
    unittest.main()
