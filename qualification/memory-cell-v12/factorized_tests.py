"""Functional checks; tiny fixtures are separate from the full corpus study."""

import unittest

import numpy as np

from factorized import FactorizedAddress
from factorized_experiment import read_sources


def records():
    return [dict(id=f"{m}-{h}", module=m, heading=h, text=f"{m} {h} {body}",
                 kind="procedure" if h == "Procedure" else "semantic", path=m + ".md",
                 source_id=m + "hash", version=1, available_phase=0)
            for m in ("memory.core", "memory.core.worker")
            for h, body in (("Contract", "reader requires current evidence"), ("Procedure", "restore checkpoint then verify owner"))]


class FactorizedTests(unittest.TestCase):
    def test_literal_address_resolution_and_ambiguous_query(self):
        engine = FactorizedAddress(records(), 0, 16)
        self.assertEqual(engine.resolve_module("Explain memory core worker rules"), "memory.core.worker")
        self.assertIsNone(engine.resolve_module("Compare memory core with memory core worker"))
        self.assertIsNone(engine.resolve_module("Describe an absent module"))

    def test_real_fit_checkpoint_and_both_two_read_paths(self):
        data = records()
        queries = [dict(id="q", text="For memory core explain the contract and restoration procedure",
                        target_ids=[data[0]["id"], data[1]["id"]])]
        engine = FactorizedAddress(data, 0, 16).fit(queries, seed=31, hidden=8, steps=80)
        restored = FactorizedAddress.from_export(engine.export(), data)
        for mode in ("learned", "single", "history", "bm25"):
            scores = engine.score([queries[0]["text"]], mode)
            np.testing.assert_array_equal(scores, restored.score([queries[0]["text"]], mode))
            chosen_a, reads_a = read_sources(engine, scores[0], 0., "top2")
            chosen_b, reads_b = read_sources(engine, scores[0], 0., "top1_twice")
            self.assertEqual(chosen_a, chosen_b)
            self.assertEqual(len(reads_a), len(reads_b))
            self.assertLessEqual(len(reads_a), 2)
            self.assertTrue(all(data[i]["module"] == "memory.core" for i in chosen_a))

    def test_latest_tombstone_never_falls_back_to_old_version(self):
        data = records()
        data.append(dict(data[0], id="new", version=2, available_phase=1, revoked=True))
        early, late = FactorizedAddress(data, 0, 16), FactorizedAddress(data, 1, 16)
        self.assertTrue(early.active[0])
        self.assertFalse(late.active[0])
        self.assertFalse(late.active[-1])
        self.assertTrue(late.active[1])


if __name__ == "__main__":
    unittest.main()
