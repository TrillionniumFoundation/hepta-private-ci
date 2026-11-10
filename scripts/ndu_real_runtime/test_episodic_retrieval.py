"""New-process retrieval and mechanism controls, with synthetic engineering data."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .episodic_memory import EpisodicStore, canonical_bytes
from .episodic_retrieval import read_memory, verify_read_receipt
from .test_episodic_memory import provenance


class EpisodicRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EpisodicStore(self.root / "authority.sqlite", namespace="n")
        self.gate = self.store.put("s1", "gate", "Current gate is B12", provenance=provenance())
        self.route = self.store.put("s1", "route", "Gate B12 needs a shuttle", provenance=provenance())
        self.foreign = self.store.put("s2", "gate", "Other source gate C30", provenance=provenance())

    def read(self, **kwargs):
        return read_memory(self.store, **{"session_id": "eval-1", "source_ids": ["s1"],
                                         "query": "gate B12", **kwargs})

    def test_exact_kv_and_bm25_only_read_approved_sources(self):
        exact = self.read(strategy="exact_kv", key="gate")
        self.assertEqual(exact["records"], [self.gate])
        ranked = self.read(strategy="bm25")
        self.assertEqual({r["record_id"] for r in ranked["records"]},
                         {self.gate["record_id"], self.route["record_id"]})
        self.assertTrue(verify_read_receipt(ranked))
        self.assertEqual(self.read(source_ids=["missing"])["records"], [])
        self.assertEqual(self.read(query="No matching tokens") ["records"], [])
        other = EpisodicStore(self.store.path, namespace="another", create=False)
        self.assertEqual(read_memory(other, session_id="fresh", source_ids=["s1"],
                                     query="gate")["records"], [])

    def test_modes_separate_store_read_retrieval_and_delivery(self):
        with patch.object(self.store, "view", side_effect=AssertionError("unexpected read")):
            off = self.read(mode="off")
        absent = read_memory(None, session_id="fresh", source_ids=["s1"], mode="off")
        self.assertEqual((off["context"], absent["records"]), ("", []))
        self.assertFalse(absent["receipt"]["store_read"])
        cases = {"on": (True, True, True), "retrieval_off": (True, False, False),
                 "delivery_off": (True, True, False), "association_off": (True, True, True)}
        for mode, expected in cases.items():
            with self.subTest(mode=mode):
                result = self.read(mode=mode)
                r = result["receipt"]
                self.assertEqual((r["store_read"], r["retrieval_executed"], bool(r["delivered_ids"])), expected)
                self.assertTrue(verify_read_receipt(result))
        self.assertEqual(self.read()["receipt"]["association_status"], "unavailable")

    def test_real_callback_and_its_ablation_do_not_mutate_evidence(self):
        calls = []
        def association(query, records):
            calls.append(query)
            records[0]["text"] = "Mutation attempt"
            return [r["record_id"] for r in reversed(records)]
        baseline = self.read(strategy="icl")
        associated = self.read(strategy="icl", association=association, association_id="b" * 64)
        self.assertEqual(associated["records"], list(reversed(baseline["records"])))
        self.assertEqual(calls, ["gate B12"])
        disabled = self.read(strategy="icl", mode="association_off", association=association,
                             association_id="b" * 64)
        self.assertEqual(disabled["records"], baseline["records"])
        self.assertEqual(calls, ["gate B12"])
        self.assertEqual(disabled["receipt"]["association_status"], "disabled")
        with self.assertRaises(ValueError):
            self.read(association=lambda q, rows: ["unknown"], association_id="b" * 64)

    def test_uniform_replay_and_icl_are_bounded_deterministic_baselines(self):
        first = self.read(strategy="uniform_replay", seed=7, limit=1)
        second = self.read(strategy="uniform_replay", seed=7, limit=1)
        self.assertEqual(first["records"], second["records"])
        self.assertEqual(len(first["records"]), 1)
        self.assertEqual(self.read(strategy="icl")["records"], [self.gate, self.route])
        small = self.read(strategy="icl", max_context_bytes=1)
        self.assertEqual((small["records"], small["context"]), ([], ""))
        self.assertEqual(small["receipt"]["byte_dropped_ids"],
                         [self.gate["record_id"], self.route["record_id"]])
        self.assertTrue(verify_read_receipt(small))

    def test_receipt_rejects_changed_context_records_or_audit_fields(self):
        result = self.read()
        for field in ("context", "records", "receipt"):
            changed = json.loads(canonical_bytes(result))
            if field == "context":
                changed[field] += "injected"
            elif field == "records":
                changed[field][0]["text"] = "injected"
            else:
                changed[field]["store_read"] = False
            self.assertFalse(verify_read_receipt(changed))

    def test_new_process_cli_reads_then_rejects_revoked_snapshot(self):
        root = Path(__file__).resolve().parents[2]
        snapshot = self.root / "before.json"
        self.store.export_snapshot(snapshot)
        command = [sys.executable, "-m", "scripts.ndu_real_runtime.episodic_retrieval",
                   "--store", str(self.store.path), "--namespace", "n", "--session", "new-process",
                   "--source", "s1", "--strategy", "exact_kv", "--key", "gate",
                   "--snapshot", str(snapshot)]
        def run(args):
            return json.loads(subprocess.run(args, cwd=root, text=True, capture_output=True,
                                             timeout=20, check=True).stdout)
        before = run(command)
        self.assertEqual(before["records"], [self.gate])
        self.assertTrue(verify_read_receipt(before))
        self.store.revoke("s1", "gate")
        after = run(command)
        self.assertEqual(after["records"], [])
        self.assertEqual(after["receipt"]["view_receipt"]["snapshot_rejections"], 1)
        off = run([sys.executable, "-m", "scripts.ndu_real_runtime.episodic_retrieval",
                   "--namespace", "n", "--session", "fresh-off", "--source", "s1", "--mode", "off"])
        self.assertEqual(off["records"], [])
        self.assertFalse(off["receipt"]["store_read"])


if __name__ == "__main__":
    unittest.main()
