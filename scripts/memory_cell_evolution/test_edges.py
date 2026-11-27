"""Dispatch and information-boundary tests; callbacks here are explicit stubs."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest

from edge_execution import GraphExecutor
from edge_observations import observe_source
from edge_policy import EdgePolicy, source_utilities, state_text
from edge_runner import bounded_run
from evolution_common import digest


class FakeTopology:
    def __init__(self, policy):
        self.roots = [digest("hint"), digest("color-a"), digest("color-b")]
        self.view = dict(scope="stub", epoch=1, roots=self.roots, revoked=[])
        self.graph = dict(
            generation=1,
            edge_policy=policy.binding,
            edges=[]
            if policy.recipe == "no-edges"
            else [["hint", "color-a"], ["hint", "color-b"]],
            cells={
                name: dict(support_roots=[root], roots=[root])
                for name, root in zip(["hint", "color-a", "color-b"], self.roots)
            },
        )

    def graph_snapshot(self):
        return deepcopy(self.graph), deepcopy(self.view)

    def invoke(self, cell_id, query_roots, callback):
        if not set(query_roots) <= set(
            self.graph["cells"][cell_id]["support_roots"]
        ) or not set(query_roots) <= set(self.view["roots"]):
            raise ValueError("fixture support rejection")
        return callback(SimpleNamespace(cell_id=cell_id))


class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name)
        self.task = dict(task_id="task_0", entity="edge_0", entry_cell="hint")

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, recipe="fixed"):
        policy = EdgePolicy(recipe, ["color-a", "color-b"])
        topo = FakeTopology(policy)
        calls = []

        def resolver(cell, entity, relation):
            root = topo.roots[0] if relation == "hint" else topo.roots[1]
            return dict(
                entity=entity,
                relation=relation,
                source_roots=[root],
                question=f"What is the {relation} for {entity}?",
            )

        def reader(active, prompt):
            calls.append((active.cell_id, prompt))
            return dict(
                question=prompt,
                text="warm" if active.cell_id == "hint" else "red",
                input_tokens=9,
                generated_tokens=1,
                token_ids=[5],
                answer_postprocessed=False,
            )

        return policy, topo, resolver, reader, calls

    def test_live_second_callback_contains_first_raw_output(self):
        policy, topo, resolver, reader, calls = self.fixture()
        result = GraphExecutor(topo, resolver, reader).run(
            self.task, policy, receipt_path=self.output / "run.json"
        )
        self.assertEqual(
            (result["status"], result["answer"], result["actual_callbacks"]),
            ("generated", "red", 2),
        )
        self.assertEqual(
            calls,
            [
                ("hint", "What is the hint for edge_0?"),
                (
                    "color-a",
                    'What is the color for edge_0? Previous cell output: "warm"',
                ),
            ],
        )

    def test_no_edge_has_one_call_and_no_second_answer_substitution(self):
        policy, topo, resolver, reader, calls = self.fixture("no-edges")
        result = GraphExecutor(topo, resolver, reader).run(
            self.task, policy, receipt_path=self.output / "none.json"
        )
        self.assertEqual(
            (result["status"], result["answer"], result["actual_callbacks"]),
            ("stopped", "warm", 1),
        )
        self.assertEqual(len(calls), 1)

    def test_next_decision_is_persisted_before_the_second_callback(self):
        policy, topo, resolver, reader, calls = self.fixture()
        receipt = self.output / "ordered.json"

        def checked(active, prompt):
            if active.cell_id != "hint":
                decision = json.loads(receipt.with_suffix(".decision.json").read_text())
                self.assertEqual(decision["decision"]["next_cell"], active.cell_id)
                self.assertEqual(decision["decision"]["state"]["raw_text"], "warm")
            return reader(active, prompt)

        result = GraphExecutor(topo, resolver, checked).run(
            self.task, policy, receipt_path=receipt
        )
        self.assertEqual(result["actual_callbacks"], 2)

    def test_withdrawal_between_cells_suppresses_answer_and_next_callback(self):
        policy, topo, resolver, reader, calls = self.fixture()

        def revoke_then_choose(state, eligible):
            topo.view = topo.view | dict(
                epoch=2, roots=topo.roots[1:], revoked=topo.roots[:1]
            )
            return "color-a"

        policy.choose = revoke_then_choose
        result = GraphExecutor(topo, resolver, reader).run(
            self.task, policy, receipt_path=self.output / "withdraw.json"
        )
        self.assertEqual(
            (result["status"], result["answer"], result["actual_callbacks"]),
            ("indeterminate", None, 1),
        )
        self.assertEqual(len(calls), 1)

    def test_model_failure_has_unknown_work_not_zero_token_claim(self):
        policy, topo, resolver, reader, calls = self.fixture()

        def failed(active, prompt):
            raise ValueError("simulated incomplete raw model output")

        result = GraphExecutor(topo, resolver, failed).run(
            self.task, policy, receipt_path=self.output / "failure.json"
        )
        self.assertEqual(
            (
                result["actual_callbacks"],
                result["callbacks_without_complete_raw_row"],
                result["token_counts_are_lower_bound"],
            ),
            (1, 1, True),
        )

    def test_metadata_cannot_inject_an_answer(self):
        policy, topo, resolver, reader, calls = self.fixture()

        def leaked(*args):
            return resolver(*args) | {"answer": "red"}

        result = GraphExecutor(topo, leaked, reader).run(
            self.task, policy, receipt_path=self.output / "leak.json"
        )
        self.assertEqual(
            (result["status"], result["actual_callbacks"], calls), ("denied", 0, [])
        )

    def test_source_targets_use_actual_outcomes_and_reject_final_rows(self):
        state = dict(
            question="What is the hint for edge_0?", cell_id="hint", raw_text="warm"
        )
        outcome = lambda text: dict(
            status="generated",
            raw_text=text,
            receipt_sha256=digest(text),
            actual_callbacks=1,
        )
        source = dict(
            case_id="source_0",
            phase="source",
            state=state,
            target_value="red",
            candidate_outputs={"a": outcome("red"), "b": outcome("blue")},
            source_roots=[digest("fact")],
        )
        observations, ancestry = source_utilities([source], ["a", "b"])
        self.assertEqual(
            observations,
            [dict(question=state_text(state), utilities=[1.0, 0.0], reject=False)],
        )
        changed = deepcopy(source)
        changed["candidate_outputs"]["a"] = outcome("wrong")
        self.assertEqual(
            source_utilities([changed], ["a", "b"])[0][0]["utilities"], [0.0, 0.0]
        )
        self.assertTrue(source_utilities([changed], ["a", "b"])[0][0]["reject"])
        changed["phase"] = "final"
        with self.assertRaisesRegex(ValueError, "source-only"):
            source_utilities([changed], ["a", "b"])

    def test_partial_source_panel_inherits_unqueried_decoder_ancestors(self):
        policy, topo, resolver, reader, calls = self.fixture()
        ancestor = digest("unqueried decoder training ancestor")
        topo.view["roots"].append(ancestor)
        topo.graph["cells"]["hint"]["roots"].append(ancestor)
        observed = observe_source(
            GraphExecutor(topo, resolver, reader),
            self.task,
            policy.targets,
            "red",
            output=self.output / "partial",
        )
        utilities, ancestry = source_utilities([observed], policy.targets)
        self.assertIn(ancestor, ancestry)
        self.assertEqual(set(ancestry), set(topo.view["roots"]))
        self.assertEqual(utilities[0]["utilities"], [1.0, 0.0])
        self.assertEqual(len(calls), 2)

    @unittest.skipUnless(sys.platform == "linux", "Linux execution boundary")
    def test_whole_event_deadline_retains_timeout_and_exit(self):
        script = [
            sys.executable,
            "-B",
            "-c",
            "import time; print('started', flush=True); time.sleep(10)",
        ]
        receipt = bounded_run(script, self.output / "timeout.log", seconds=0.15)
        self.assertTrue(receipt["timed_out"])
        self.assertEqual(receipt["returncode"], -9)
        self.assertIn("started", (self.output / "timeout.log").read_text())


if __name__ == "__main__":
    unittest.main()
