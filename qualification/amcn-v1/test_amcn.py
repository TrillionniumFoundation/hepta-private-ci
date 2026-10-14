"""Fail-closed hermetic AMCN mechanics tests; no simulated model success claim."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from copy import deepcopy
import importlib.util
import sys
import tempfile
import types
import unittest

import torch

from amcn_core import (Evidence, Edge, FrozenGraph, Refused, bm25, bounded_route,
                       freeze_reader_quartets, shadow_disposition, RELATIONS)
from amcn_learning import (Row, FeatureMatrix, train_semantic, train_relation_router,
                           candidate_fission_and_consolidation)


def s(text):
    return sha256(text.encode("utf-8")).hexdigest()


def item(key, text="trigger warning", scope="lab", generation="g1"):
    return Evidence(key, "root-"+key, scope, 1, text, s(text), generation)


def graph():
    a = item("a", "database deadlock circular locks")
    b = item("b", "deadlock recovery transaction retry")
    c = item("c", "connection exhausted unrelated")
    return FrozenGraph([a, b, c], [
        Edge("a", "b", "supports", s("witness-ab")),
        Edge("a", "c", "temporal", s("witness-ac")),
        Edge("c", "b", "contradicts", s("witness-cb")),
    ], scope="lab", generation="g1")


def quartets(case="q1", family="fresh-family", split="future_a"):
    base = dict(case_id=case, family=family, split=split,
                reader_sha256=s("reader"), prompt_sha256=s("prompt"),
                question_sha256=s(case), max_input_tokens=1024,
                max_new_tokens=64, source_frontier_sha256=s("source frontier"))
    out = []
    for arm in ("no_evidence", "ordinary_retrieval", "human_sufficient", "critical_premise_removed"):
        ids = {"no_evidence": [], "ordinary_retrieval": ["e1"],
               "human_sufficient": ["e1", "e2"], "critical_premise_removed": ["e1"]}[arm]
        out.append(dict(base, arm=arm, evidence_ids=ids,
                        review_receipt_sha256=s("independent upstream receipt") if "evidence" not in arm
                        and arm in ("human_sufficient", "critical_premise_removed") else None))
    return out


def matrix():
    rows, data, labels = [], [], {}
    for i in range(8):
        rid = f"train-{i}"
        rows.append(Row(rid, f"source-train-{i}", "train-family",
                        "train", "lab", "g1", s(rid)))
        data.append([1.0 if i % 2 else -1.0, i / 10.0, float(i % 3), 0.0])
        labels[rid] = i % 2
    for split in ("future_a", "future_b", "retention"):
        rid = f"{split}-1"
        rows.append(Row(rid, f"root-{rid}", split+"-family", split,
                        "lab", "g1", s(rid)))
        data.append([0.5, 0.2, 0.0, 1.0])
    return FeatureMatrix(rows, torch.tensor(data, dtype=torch.float32),
                         encoder_sha256=s("fixture-frozen-encoder"), scope="lab",
                         generation="g1", backend_profile="mechanics_fixture"), labels


class ContractTests(unittest.TestCase):
    def test_source_checksum_and_tombstone(self):
        with self.assertRaises(Refused):
            Evidence("id", "root", "lab", 1, "content", s("tampered"), "g1")
        g = graph()
        self.assertEqual(g.candidates(["a"], maximum_hops=1), ["a", "b", "c"])
        self.assertTrue(g.revalidate(g.sources, scope="lab", generation="g1"))
        poisoned = dict(g.sources)
        poisoned["a"] = Evidence("a", "root-a", "lab", 1,
                                 "database deadlock circular locks",
                                 s("database deadlock circular locks"), "g1", revoked=True)
        with self.assertRaises(Refused):
            g.revalidate(poisoned, scope="lab", generation="g1")
        with self.assertRaises(Refused):
            g.revalidate(g.sources, scope="other", generation="g1")

    def test_graph_structure_and_control(self):
        g = graph()
        self.assertEqual(bounded_route(g, ["a"], mode="independent"), ["a"])
        self.assertEqual(bounded_route(g, ["a"], mode="fixed_graph"), ["a", "b", "c"])
        learned = bounded_route(g, ["a"], mode="learned_router",
                                edge_weights={r: 0.2 for r in RELATIONS})
        self.assertEqual(set(learned), {"a", "b", "c"})
        with self.assertRaises(Refused):
            bounded_route(g, ["a"], mode="learned_router", edge_weights={"supports": 1.0})
        with self.assertRaises(Refused):
            FrozenGraph(list(g.sources.values()), [Edge("a", "missing", "supports", s("w"))],
                        scope="lab", generation="g1")
        self.assertEqual(bm25("circular deadlock", list(g.sources.values()),
                              scope="lab", generation="g1")[0][0], "a")

    def test_reader_4_arms_and_leakage(self):
        receipt = freeze_reader_quartets(quartets())
        self.assertEqual((receipt["cases"], receipt["arms"]), (1, 4))
        self.assertFalse(receipt["reader_capability_qualified"])
        for field in ("max_new_tokens", "prompt_sha256", "reader_sha256"):
            broken = deepcopy(quartets())
            broken[2][field] = 129 if field == "max_new_tokens" else s("changed")
            with self.assertRaises(Refused):
                freeze_reader_quartets(broken)
        missing = quartets()[:-1]
        with self.assertRaises(Refused):
            freeze_reader_quartets(missing)
        removed = quartets()
        removed[3]["evidence_ids"] = ["e1", "e2"]
        with self.assertRaises(Refused):
            freeze_reader_quartets(removed)
        no_review = quartets()
        no_review[2]["review_receipt_sha256"] = None
        with self.assertRaises(Refused):
            freeze_reader_quartets(no_review)
        overlapping = quartets() + quartets("q2", "fresh-family", "train")
        with self.assertRaises(Refused):
            freeze_reader_quartets(overlapping)

    def test_negative_authority_is_permanent(self):
        report = shadow_disposition(loss=0.0)
        self.assertFalse(report["production_accepted"])
        self.assertIsNone(report["independent_semantic_citation_precision"])


class ActualTorchMechanicsTests(unittest.TestCase):
    def test_shared_head_training_without_future_labels(self):
        data, labels = matrix()
        record = train_semantic(data, labels, steps=12)
        self.assertNotEqual(record["receipt"]["metrics"]["frozen"]["sha256"],
                            record["receipt"]["metrics"]["trained"]["sha256"])
        self.assertEqual(len(record["predictions"]), len(data.rows))
        self.assertFalse(record["receipt"]["production_accepted"])
        leaked = dict(labels)
        leaked["future_a-1"] = 1
        with self.assertRaises(Refused):
            train_semantic(data, leaked)
        with self.assertRaises(Refused):
            FeatureMatrix(data.rows, data.x, encoder_sha256=s("x"),
                          scope="lab", generation="g1",
                          backend_profile="local_hf_snapshot_checked_unreviewed")

    def test_real_relation_learning_and_no_topology_change(self):
        g = graph()
        pairs = [{"relation": r, "label": label, "family": f"train-{i}",
                  "split": "train"}
                 for i, (r, label) in enumerate([
                     ("supports", 1), ("temporal", 0), ("supports", 1),
                     ("temporal", 0), ("supports", 1), ("temporal", 0)])]
        weights, receipt = train_relation_router(g, pairs, steps=10)
        self.assertGreater(weights["supports"], weights["temporal"])
        self.assertFalse(receipt["metrics"]["topology_mutation"])
        self.assertEqual(g.snapshot_digest, receipt["metrics"]["graph_sha256"])
        wrong = deepcopy(pairs)
        wrong[0]["split"] = "future_a"
        with self.assertRaises(Refused):
            train_relation_router(g, wrong)

    def test_child_split_and_consolidation_are_candidate_only(self):
        data, labels = matrix()
        parent = train_semantic(data, labels, steps=12)["trained"]
        partition = {f"train-{i}": i % 2 for i in range(8)}
        result = candidate_fission_and_consolidation(parent, data, labels,
                                                     partition, steps=8)
        receipt = result["receipt"]
        self.assertLessEqual(receipt["metrics"]["initialization_max_abs_error"], 2e-5)
        self.assertEqual(len(result["predictions"]), len(data.rows))
        self.assertFalse(receipt["metrics"]["equal_parameter_budget_control_completed"])
        self.assertFalse(receipt["metrics"]["independent_old_task_retention"])
        self.assertFalse(receipt["production_accepted"])
        poisoned = dict(partition)
        poisoned["future_a-1"] = 1
        with self.assertRaises(Refused):
            candidate_fission_and_consolidation(parent, data, labels, poisoned, steps=1)


class LongMemEvalBridgeTests(unittest.TestCase):
    def _load_bridge(self):
        # Standalone import compatibility fixture for exact published Memory API.
        pkg = types.ModuleType("memory_modules")
        pkg.__path__ = []
        mem = types.ModuleType("memory_modules.memory")

        class Memory:
            def __init__(self, memory_params):
                self.memory_params = dict(memory_params)

        mem.Memory = Memory
        mem.MemoryContextItem = dict
        mem.require = lambda ok, why: None if ok else (_ for _ in ()).throw(RuntimeError(why))
        mem.register_memory = lambda cls: cls
        sys.modules["memory_modules"] = pkg
        sys.modules["memory_modules.memory"] = mem
        path = Path(__file__).with_name("lme_v2_bridge.py")
        spec = importlib.util.spec_from_file_location("_amcn_lme_bridge_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.AMCNShadowMemory

    def test_official_memory_insert_query_save_load_and_tamper(self):
        Backend = self._load_bridge()
        backend = Backend({"top_k": 2})
        backend.insert({"id": "trajectory-1", "goal": "Debug a UI flow",
                        "states": [{"url": "https://example.invalid/console",
                                    "text": "Deadlock on route creation due to lock inversion",
                                    "action": "inspect logs"},
                                   {"url": "https://example.invalid/console",
                                    "text": "Retry restored the request after backoff",
                                    "action": "retry"}]})
        answer = backend.query("deadlock route")
        self.assertGreaterEqual(len(answer), 1)
        self.assertIn("trajectory-1:state:", answer[0]["value"])
        self.assertEqual(backend.post_query_hook(query="deadlock route", query_image=None,
                memory_context=answer)["trained_neural_cell"], False)
        with self.assertRaises(RuntimeError):
            backend.insert({"id": "trajectory-1", "states": [{"url": "x", "text": "x"}]})
        with tempfile.TemporaryDirectory() as root:
            out = Path(root)
            backend._save_backend(out)
            loaded = Backend({"top_k": 2})
            loaded._load_backend(out)
            self.assertEqual(loaded.query("deadlock route"), answer)
            path = out / "amcn-shadow.json"
            obj = __import__("json").loads(path.read_text())
            obj["rows"][0]["text"] = "forged"
            path.write_text(__import__("json").dumps(obj), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                Backend({})._load_backend(out)


if __name__ == "__main__":
    unittest.main()
