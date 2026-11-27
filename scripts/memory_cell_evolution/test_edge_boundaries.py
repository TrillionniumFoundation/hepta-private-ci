"""Source-owner and budget scheduling checks with no model imports or calls."""

from pathlib import Path
import ast
import re
import tempfile
import unittest

from edge_budget import EffectFailure, ModelBudget
from edge_model_worker import vocabulary
from edge_protocol import protocol
from edge_runtime import EdgeRuntime
from evolution_common import digest


ROOT = Path(__file__).resolve().parent.parent
BUDGET = ROOT / "memory_cell_budget"
REPO = ROOT.parent


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_source_metadata_excludes_answer_and_withdraws_monotonically(self):
        runtime = EdgeRuntime(REPO, self.output, BUDGET, protocol())
        snapshot = runtime.source_setup()
        self.assertEqual((len(snapshot["facts"]), len(snapshot["roots"])), (12, 12))
        metadata = runtime.resolver("hint", "edge_0", "hint")
        self.assertEqual(
            set(metadata), {"entity", "relation", "source_roots", "question"}
        )
        root = metadata["source_roots"][0]
        runtime.authority.revoke("edge_0_hint", 0)
        self.assertIsNone(runtime.resolver("hint", "edge_0", "hint"))
        frontier = runtime.frontier()
        self.assertIn(root, frontier["revoked"])
        self.assertNotIn(root, frontier["roots"])
        self.assertEqual(len(frontier["roots"]), 11)

    def test_successful_stub_settles_only_observed_declared_work(self):
        budget = ModelBudget(self.output, BUDGET, digest(protocol()))
        result = budget.effect(
            "source",
            {"stub": True},
            lambda: {"measured": 7},
            lambda value: {"input_tokens": value["measured"]},
            queries=1,
        )
        self.assertEqual(result, {"measured": 7})
        state = budget.ledger.snapshot()
        self.assertEqual(
            (
                state["executed_used"]["input_tokens"],
                state["executed_used"]["decoder_queries"],
            ),
            (7, 0),
        )
        self.assertEqual(sum(state["pending"].values()), 0)
        self.assertFalse(state["closed"])

    def test_incomplete_stub_consumes_reservation_and_stops_followup(self):
        budget = ModelBudget(self.output, BUDGET, digest(protocol()))

        def fail():
            raise ValueError("deliberate incomplete stub receipt")

        with self.assertRaises(EffectFailure):
            budget.effect("train", {"stub": "failure"}, fail, lambda _: {}, updates=4)
        state = budget.ledger.snapshot()
        self.assertTrue(state["closed"])
        self.assertEqual(state["events"][0]["state"], "lost")
        self.assertEqual(state["executed_used"]["decoder_updates"], 0)
        self.assertEqual(state["uncertain_work_charged"]["decoder_updates"], 4)
        self.assertEqual(state["used"]["decoder_updates"], 4)
        with self.assertRaises(EffectFailure):
            budget.effect(
                "source", {"stub": "after failure"}, lambda: None, lambda _: {}
            )

    def test_registered_token_vocabulary_preserves_each_entity_and_template_word(self):
        tokens = vocabulary(protocol())
        self.assertEqual(tokens[:3], ["[UNK]", "[BOS]", "[EOS]"])
        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertTrue(
            {"edge_0", "edge_5", "s", "cite", "sources", "Previous", "warm", "cool"}
            <= set(tokens)
        )
        module = ast.parse(
            (REPO / "scripts/memory_cell/parametric_model.py").read_bytes()
        )
        system = next(
            ast.literal_eval(n.value)
            for n in module.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "SYSTEM" for t in n.targets)
        )
        self.assertTrue(set(re.findall(r"\w+|[^\w\s]", system)) <= set(tokens))


if __name__ == "__main__":
    unittest.main()
