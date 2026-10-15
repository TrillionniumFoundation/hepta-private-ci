"""Original #1777 Torch router integration (needs complete repo owner modules)."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import unittest

from amcn_causal_task_audit import digest, Refused
from amcn_causal_graph_training import physical_relation_packet, independent_sgd
from test_amcn_causal_route_plan import setup


@unittest.skipUnless(importlib.util.find_spec("amcn_core") and
                     importlib.util.find_spec("amcn_learning"),
                     "must be executed in full original repository; no local fake owner")
class OriginalGraphPhysicalOwner(unittest.TestCase):
    def setUp(self):
        from amcn_core import Edge, Evidence, FrozenGraph

        self.packet, _, _, _, self.graphs, _ = setup()
        self.case = self.packet["cases"][0]
        self.edges = self.graphs[self.case["question_id"]]["edges"]
        sources = [Evidence(
            evidence_id=s["source_id"], source_root=s["source_root"],
            scope=s["scope"], generation=s["generation"],
            revision=s["revision"], text=s["text"],
            content_sha256=s["content_sha256"], revoked=s["revoked"])
            for s in self.case["eligible_sources"]]
        edges = [Edge(e["source_id"], e["target_id"],
                      e["relation"], e["support_sha256"])
                 for e in self.edges]
        self.original = FrozenGraph(
            sources, edges, scope=self.case["scope"],
            generation=self.case["generation"])
        self.train = [
            {"split": "train", "relation": "temporal", "label": 1,
             "family": "training-1"},
            {"split": "train", "relation": "associative", "label": 0,
             "family": "training-2"},
            {"split": "train", "relation": "temporal", "label": 0,
             "family": "training-3"},
            {"split": "train", "relation": "associative", "label": 1,
             "family": "training-4"},
            {"split": "train", "relation": "temporal", "label": 1,
             "family": "training-5"},
            {"split": "train", "relation": "associative", "label": 0,
             "family": "training-6"},
        ]
        self.opts = dict(
            expected_train_sha256=digest(self.train),
            expected_graph_sha256=self.original.snapshot_digest,
            forbidden_future_families={"family-0", "family-2"},
            lesion_edge=[self.edges[0]["source_id"],
                         self.edges[0]["target_id"],
                         self.edges[0]["relation"]],
            steps=25,
        )

    def test_actual_original_torch_optimizer_and_independent_sgd(self):
        produced = physical_relation_packet(
            self.case, self.edges, self.train, **self.opts)
        self.assertEqual(produced["question_id"], self.case["question_id"])
        self.assertEqual(produced["training_receipt"]["optimizer_steps"], 25)
        observed = produced["trained_relation_weights"]
        witness = independent_sgd(self.train, steps=25)
        self.assertTrue(all(abs(observed[r] - witness[r]) < 2e-5 for r in observed))
        self.assertNotEqual(observed["temporal"], 0.0)
        self.assertFalse(any("production_accepted" in r for r in [
            produced["training_receipt"]]))

    def test_original_graph_scope_tamper_denied_before_training(self):
        bad = deepcopy(self.case)
        bad["eligible_sources"][0]["revision"] += 1
        with self.assertRaisesRegex(Refused, "snapshot identity changed"):
            physical_relation_packet(bad, self.edges, self.train, **self.opts)

    def test_train_label_leakage_denied_before_optimizer(self):
        bad = deepcopy(self.train)
        bad[0]["family"] = "family-2"
        with self.assertRaisesRegex(Refused, "pinned original"):
            physical_relation_packet(self.case, self.edges, bad, **self.opts)

    def test_adversarial_lesion_identity_rejected(self):
        bad = dict(self.opts, lesion_edge=["fabricated", "edge", "supports"])
        with self.assertRaisesRegex(Refused, "lesion"):
            physical_relation_packet(self.case, self.edges, self.train, **bad)


if __name__ == "__main__":
    unittest.main()
