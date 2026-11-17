"""Existing producer JSON with scripted models/optimizer fixtures; no GPU evidence."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

TORCH_WAS_IMPORTED = "torch" in sys.modules
try:
    from .reporting_v4 import aggregate, digest
except ImportError:
    from reporting_v4 import aggregate, digest
REPORTING_IMPORTED_TORCH = not TORCH_WAS_IMPORTED and "torch" in sys.modules

ROOT = Path(__file__).resolve().parent.parent
if (ROOT / "onpolicy/checktree/scripts").is_dir():
    sys.path[:0] = [str(ROOT / "onpolicy/checktree/scripts"),
                   "/workspace/scratch/0c078af77c37/cell_experiments_v3_20261116/scripts"]
import cell_experiments.online_v4 as package
if (ROOT / "onpolicy/source-01").is_dir():
    package.__path__[:0] = [str(ROOT / "onpolicy/source-01"), str(ROOT / "circuit/source02/online_v4")]
from cell_experiments import data, repo_execution
from cell_experiments.coding_sft import write_new
from cell_experiments.online_v4.test_onpolicy_flow import FixtureBackend, prepared
from cell_experiments.online_v4.onpolicy_loop import make_freeze, run
from cell_experiments.online_v4.circuit_contract import Budget, Graph
from cell_experiments.online_v4.circuit_router import RouterPlan, fit_router
from cell_experiments.online_v4.circuit_study import evaluate_suite
from cell_experiments.online_v4.test_circuit_runtime import ScriptedCells, cells, task


class StructuredTrainingFixture(FixtureBackend):
    def fit(self, records, current, plan, output):
        candidate, item = super().fit(records, current, plan, output)
        item.update(schema="hepta.current-policy-sft-training.v1", independent_sample_increment=0,
                    optimizer_initialization="fresh_AdamW_each_round",
                    previous_parameter_after=current["parameter_after"],
                    cost={"input_tokens_consumed": 192, "supervised_tokens": 64,
                          "padded_training_token_positions": 98304})
        write_new(Path(output) / "TRAINING.json", item)
        return candidate, item


class ReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="reporting-producer-fixtures-"))
        repo_execution.load_catalog("open")
        context = {"records": [prepared(i) for i in range(1, 7)]}
        initial = {"generation": 0, "parameter_after": digest({"protocol_fixture_round": 0})}
        cls.e2 = {}
        read = lambda path: json.loads(path.read_text())
        for mode in ("teacher", "shadow", "controlled"):
            backend, output = StructuredTrainingFixture(), cls.root / mode
            freeze = make_freeze(context, initial, backend, operation_id="report-test-" + mode, mode=mode)
            run(context, initial, output, freeze, backend)
            cls.e2[mode] = {"freeze": read(output / "FREEZE.json"), "result": read(output / "RESULT.json"),
                            "training": [read(output / f"round-{i:03d}/model/TRAINING.json") for i in range(2)]}
        registry, budget = cells(), Budget(max_output_tokens_per_call=1024)
        a, b = task(1, "blue " * 10 + "Check counter."), task(2, "red " * 10 + "Check counter.")
        b["split"] = "selection"
        graphs = [Graph("blue", ("first", "first")), Graph("red", ("second", "second"))]
        router, _ = fit_router([a], graphs, registry, budget, ScriptedCells(registry, mode="context"),
                              data.verify_answer, cls.root / "search", plan=RouterPlan("e" * 64))
        cls.search, cls.search_plan = read(cls.root / "search/SEARCH.json"), read(cls.root / "search/PLAN.json")
        cls.studies, cls.plans = {}, {}
        for panel, record in (("A", a), ("B", b)):
            evaluate_suite([record], registry, budget, ScriptedCells(registry, mode="context"),
                           data.verify_answer, cls.root / panel, router=router, single_cell="first",
                           fixed_graph=Graph("fixed", ("first", "second")), random_seed=1729,
                           execution_binding_digest="e" * 64)
            cls.studies[panel], cls.plans[panel] = read(cls.root / panel / "STUDY.json"), read(cls.root / panel / "PLAN.json")
        print("Retained CPU producer/structured optimizer fixtures:", cls.root, flush=True)

    def call(self, **changes):
        args = copy.deepcopy({"e2": self.e2, "search": self.search, "studies": self.studies,
                              "search_plan": self.search_plan, "study_plans": self.plans})
        args.update(changes)
        return aggregate(**args)

    def test_existing_producer_json_counts_search_and_ablations_once(self):
        report = self.call()
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["input_validation"], "CONSISTENT")
        expected = sum(v["result"]["model_calls"] for v in self.e2.values()) + self.search["search_model_calls"]
        expected += sum(v["all_actual_execution_cost"]["model_calls"] for v in self.studies.values())
        self.assertEqual(report["reported_scope_totals"]["model_calls"], expected)
        self.assertEqual(report["training_totals"]["input_tokens_consumed"], 1152)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertIsNone(report["all_verifier_calls"])
        self.assertFalse(report["scientific_qualification"])
        self.assertEqual(report["independent_sample_increment"], 0)
        self.assertFalse(REPORTING_IMPORTED_TORCH)

    def test_same_initial_context_A_steps_and_fresh_optimizer_are_required(self):
        for key, value in (("initial_model_digest", "a" * 64), ("context_digest", "a" * 64),
                           ("A_records_digest", "a" * 64), ("rounds", 1), ("steps_per_round", 32),
                           ("optimizer_initialization", "resumed"), ("maximum_attempts", 3)):
            e2 = copy.deepcopy(self.e2)
            e2["shadow"]["freeze"][key] = value
            e2["shadow"]["result"]["freeze_digest"] = digest(e2["shadow"]["freeze"])
            with self.subTest(key=key):
                self.assertEqual(self.call(e2=e2)["input_validation"], "INCOMPLETE")

    def test_failed_or_missing_receipts_never_become_zero(self):
        e2 = copy.deepcopy(self.e2)
        e2["controlled"]["result"] = {"status": "FAILED_PRESERVED", "call_totals_complete": False}
        report = self.call(e2=e2)
        self.assertIsNone(report["reported_scope_totals"]["model_calls"])
        self.assertGreater(report["known_measured_subtotals"]["model_calls"], 0)
        self.assertEqual(report["status"], "INCOMPLETE")
        studies = copy.deepcopy(self.studies)
        del studies["A"]["arms"]["single"][0]["cost"]["input_tokens"]
        self.assertIsNone(self.call(studies=studies)["reported_scope_totals"]["input_tokens"])

    def test_plans_bind_budget_and_missing_plan_is_unknown(self):
        plans, studies = copy.deepcopy(self.plans), copy.deepcopy(self.studies)
        plans["B"]["budget"]["max_output_tokens_per_call"] = 512
        studies["B"]["plan_digest"] = digest(plans["B"])
        self.assertIsNone(self.call(study_plans=plans, studies=studies)["bound_E4_budget"])
        self.assertIsNone(self.call(search_plan=None)["bound_E4_budget"])

    def test_duplicate_execution_and_incomplete_ablation_are_rejected(self):
        studies = copy.deepcopy(self.studies)
        studies["B"]["arms"]["single"][0]["result_digest"] = studies["A"]["arms"]["single"][0]["result_digest"]
        self.assertIsNone(self.call(studies=studies)["reported_scope_totals"]["model_calls"])
        del studies["A"]["interventions"]["edge-feedback"]
        self.assertEqual(self.call(studies=studies)["input_validation"], "INCOMPLETE")

    def test_training_digest_and_nonboolean_counts_are_required(self):
        e2 = copy.deepcopy(self.e2)
        e2["teacher"]["training"][0]["steps"] = 32
        self.assertIsNone(self.call(e2=e2)["training_totals"]["input_tokens_consumed"])
        e2 = copy.deepcopy(self.e2)
        e2["teacher"]["result"]["input_tokens"] = False
        self.assertIsNone(self.call(e2=e2)["reported_scope_totals"]["input_tokens"])


if __name__ == "__main__":
    unittest.main()
