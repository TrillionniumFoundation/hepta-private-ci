"""No-model protocol tests: no claim of language memory, Reader or graph learning."""
from dataclasses import replace
import hashlib
import unittest

from memory_graph_lesion import (
    Edge, Node, ResearchGraph, experiment, fixture
)


class MemoryGraphLesionTests(unittest.TestCase):
    def setUp(self):
        self.graph, self.questions = fixture()

    def test_controlled_four_arm_lesion(self):
        result = experiment()
        self.assertEqual(result["arms"], {
            "no_graph": {"hits": 0, "questions": 4},
            "graph": {"hits": 4, "questions": 4},
            "shuffled": {"hits": 0, "questions": 4},
            "premise_deleted": {"hits": 0, "questions": 4},
        })
        self.assertEqual(result["fixture_family_count_effective"], 1)
        self.assertFalse(result["independent_evaluation"])
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["trained_model_executed"])

    def test_scope_generation_and_revoked_roots(self):
        packet = self.graph.recall("n0", "scope:a", 1)
        self.assertNotIn("secret", packet["nodes"])
        self.assertNotIn("stale", packet["nodes"])
        self.assertEqual(packet["paths"]["n2"], ("n0", "n1", "n2"))
        self.assertNotIn(
            "n2", self.graph.recall("n0", "scope:a", 1, revoked={"r1"})["nodes"]
        )
        with self.assertRaisesRegex(ValueError, "seed denied"):
            self.graph.recall("n0", "scope:a", 1, revoked={"r0"})
        with self.assertRaisesRegex(ValueError, "seed denied"):
            self.graph.recall("secret", "scope:a", 1)

    def test_resource_budgets_and_abstain(self):
        limited = self.graph.recall("n0", "scope:a", 1, max_hops=1, max_nodes=2)
        self.assertEqual(limited["nodes"], ("n0", "n1"))
        self.assertFalse(limited["evidence_verified"])
        with self.assertRaises(ValueError):
            self.graph.recall("n0", "scope:a", 1, max_nodes=1024)
        with self.assertRaises(ValueError):
            self.graph.recall("n0", "scope:a", 1, mode="unregistered")
        with self.assertRaisesRegex(ValueError, "premise identity"):
            self.graph.recall("n0", "scope:a", 1, mode="premise_deleted")

    def test_unbound_duplicate_or_unknown_edges_rejected(self):
        a = Node("a", "scope:a", "ra", 1, hashlib.sha256(b"a").hexdigest())
        b = Node("b", "scope:a", "rb", 1, hashlib.sha256(b"b").hexdigest())
        edge = Edge("a", "b", "requires", ("ra", "rb"))
        ResearchGraph((a, b), (edge,))
        for edges in (
            (edge, edge),
            (replace(edge, support_roots=("fabricated",)),),
            (replace(edge, kind="executes"),),
        ):
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                ResearchGraph((a, b), edges)
        with self.assertRaises(ValueError):
            ResearchGraph((a, a), ())


if __name__ == "__main__":
    unittest.main()
