"""Synthetic rank-fusion contracts; never independent task-quality evidence."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import torch

import five_causal_experiments as c
import full_select_rank_fusion as f


def plan():
    keys = [c.digest("e0"), c.digest("e1"), c.digest("e2")]
    qids = [c.digest("q0"), c.digest("q1"), c.digest("q2")]
    evidence = [{"evidence_key": key, "family": "a" if i < 2 else "b",
                 "question_ids": [qids[min(i, 1)]], "status": "available"}
                for i, key in enumerate(keys)]
    units = [
        {"question_id": qids[0], "family": "a", "evidence_key": keys[0], "status": "available"},
        {"question_id": qids[1], "family": "a", "evidence_key": keys[1], "status": "available"},
        {"question_id": qids[2], "family": "b", "evidence_key": keys[2], "status": "over_cap"},
    ]
    return {"units": units, "evidence_candidates": evidence}, {
        "question_ids": qids, "evidence_keys": keys,
        "methods": ["cosine", "lexical_jaccard"]}


def bases():
    cosine = torch.tensor([[3., 2., 1.], [1., 3., 2.], [float("nan")]*3], dtype=torch.float64)
    lexical = torch.tensor([[1., 3., 2.], [2., 1., 3.], [float("nan")]*3], dtype=torch.float64)
    return cosine, lexical


class RankTests(unittest.TestCase):
    def test_fixed_key_tie_break(self):
        keys = sorted([c.digest("b"), c.digest("a"), c.digest("c")])
        rank = f.deterministic_ranks(torch.tensor([1., 1., 0.], dtype=torch.float64), keys)
        self.assertEqual(rank[keys[0]], 1)
        self.assertEqual(rank[keys[1]], 2)
        self.assertEqual(rank[keys[2]], 3)

    def test_nonfinite_duplicate_and_wrong_dtype_rejected(self):
        keys = [c.digest("a"), c.digest("b")]
        for values, supplied in ((torch.tensor([1., float("nan")], dtype=torch.float64), keys),
                                 (torch.tensor([1., 2.]), keys),
                                 (torch.tensor([1., 2.], dtype=torch.float64), [keys[0], keys[0]])):
            with self.assertRaises(c.Invalid):
                f.deterministic_ranks(values, supplied)


class FusionTests(unittest.TestCase):
    def test_exact_formulas_and_unavailable_row(self):
        p, index = plan(); cosine, lexical = bases()
        out = f.fuse(p, index, cosine, lexical)
        keys = index["evidence_keys"]
        rc = f.deterministic_ranks(cosine[0], keys)
        rl = f.deterministic_ranks(lexical[0], keys)
        j = keys.index(keys[0])
        self.assertEqual(float(out["equal_reciprocal_rank"][0, j]), 1/rc[keys[0]] + 1/rl[keys[0]])
        self.assertEqual(float(out["rrf_k60"][0, j]), 1/(60+rc[keys[0]]) + 1/(60+rl[keys[0]]))
        self.assertEqual(float(out["mean_rank"][0, j]), -.5*(rc[keys[0]]+rl[keys[0]]))
        self.assertEqual(float(out["rank_product"][0, j]), 1/(rc[keys[0]]*rl[keys[0]]))
        self.assertTrue(all(bool(torch.isnan(matrix[2]).all()) for matrix in out.values()))

    def test_scores_do_not_use_own_target(self):
        p, index = plan(); cosine, lexical = bases()
        before = f.fuse(p, index, cosine, lexical)
        changed = deepcopy(p)
        changed["units"][0]["evidence_key"] = index["evidence_keys"][2]
        after = f.fuse(changed, index, cosine, lexical)
        for name in f.FUSION_METHODS:
            self.assertTrue(torch.equal(torch.isnan(before[name]), torch.isnan(after[name])))
            self.assertTrue(torch.equal(torch.nan_to_num(before[name]),
                                        torch.nan_to_num(after[name])))

    def test_inputs_not_mutated_and_controls_differ(self):
        p, index = plan(); cosine, lexical = bases()
        digest = c.digest([p, index])
        cosine_before, lexical_before = cosine.clone(), lexical.clone()
        out = f.fuse(p, index, cosine, lexical)
        self.assertEqual(digest, c.digest([p, index]))
        self.assertTrue(torch.equal(torch.isnan(cosine_before), torch.isnan(cosine)))
        self.assertTrue(torch.equal(torch.nan_to_num(cosine_before), torch.nan_to_num(cosine)))
        self.assertTrue(torch.equal(torch.isnan(lexical_before), torch.isnan(lexical)))
        self.assertTrue(torch.equal(torch.nan_to_num(lexical_before), torch.nan_to_num(lexical)))
        self.assertFalse(torch.equal(out["equal_reciprocal_rank"][:2],
                                     out["anti_cosine_control"][:2]))
        self.assertFalse(torch.equal(out["equal_reciprocal_rank"][:2],
                                     out["cyclic_cosine_control"][:2]))

    def test_matrix_rows_preserves_missing_and_rejects_imputation(self):
        p, index = plan(); cosine, _ = bases()
        rows = f.matrix_rows(p, index, cosine)
        self.assertEqual(rows[2]["status"], "over_cap")
        self.assertIsNone(rows[2]["scores"])
        bad = cosine.clone(); bad[2, 0] = 0
        with self.assertRaises(c.Invalid):
            f.matrix_rows(p, index, bad)

    def test_summary_integration(self):
        p, index = plan(); cosine, lexical = bases()
        fused, summaries, comparisons = f.analyze(p, index, {"cosine": cosine, "lexical_jaccard": lexical})
        self.assertEqual(set(fused), set(f.FUSION_METHODS))
        self.assertEqual(summaries["equal_reciprocal_rank"]["planned_questions"], 3)
        self.assertEqual(summaries["equal_reciprocal_rank"]["scored_questions"], 2)
        self.assertEqual(comparisons["equal_reciprocal_rank"]["questions"], 2)


class EntrypointTests(unittest.TestCase):
    def test_help_from_foreign_directory_without_pythonpath(self):
        script = Path(f.__file__).with_name("full_select_rank_fusion_trial.py")
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(script), "--help"], cwd=directory,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--archive", run.stdout)
        self.assertNotIn("ModuleNotFoundError", run.stderr)


if __name__ == "__main__":
    unittest.main()
