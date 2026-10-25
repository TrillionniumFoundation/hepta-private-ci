"""Privileged finite diagnostics cannot be mistaken for online selection."""

import unittest

import torch

from .control import PLANS, PLAN_INDEX
from .evaluation import offline_primary_oracles, projected_rows, select_public_paths


class StopPolicy:
    def choose(self, features, remaining):
        return torch.zeros(len(features), dtype=torch.long)


class EvaluationTests(unittest.TestCase):
    def test_labels_only_change_offline_oracle_not_public_controls(self):
        features = torch.zeros(3, 5, 673)
        public = {"features": features}
        bundle = {"static": {"plan_index": 2}, "feedback": StopPolicy()}
        chosen, work = select_public_paths(None, public, bundle, extended=False, training_seed=17)
        self.assertEqual(chosen["feedback"].tolist(), [0, 0, 0])
        self.assertEqual(chosen["fixed"].tolist(), [PLAN_INDEX[("refine_image", "refine_text")]] * 3)
        self.assertEqual(work, {})
        labels = torch.zeros(3, 21)
        labels[:, 8] = 1
        data = {"features": features, "metrics": {"primary": {"utility": labels}},
                "cases": [608, 609, 610], "views": ["clean"] * 3,
                "scenarios": [0] * 3, "source_ids": [("a", "b"), ("c", "d"), ("e", "f")]}
        oracle = offline_primary_oracles(data)
        self.assertEqual(oracle["oracle_primary"].tolist(), [8, 8, 8])
        self.assertEqual(oracle["oracle_primary_allocation"].tolist(), [0, 0, 0])
        after, _ = select_public_paths(None, data, bundle, extended=False, training_seed=17)
        for key in chosen:
            self.assertTrue(torch.equal(after[key], chosen[key]))
        rows = list(projected_rows(data, oracle, seed=17, arm="output_ndu", tree_directory="tree"))
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({tuple(row["source_ids"]) for row in rows}), 3)
        self.assertTrue(all(row["selection_is_privileged_offline_oracle"] for row in rows))
        self.assertAlmostEqual(rows[0]["observers"]["primary"]["net_utility"], .996)


if __name__ == "__main__":
    unittest.main()
