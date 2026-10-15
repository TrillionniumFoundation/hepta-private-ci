"""Synthetic full-pool residual transfer contracts; never task-quality evidence."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import torch
from torch.nn import functional as F

import five_causal_experiments as c
import full_select_residual_transfer as transfer
import shared_gate_cosine_residual as residual
from experiments.shared_stem_cell.execution import parameters, tensor_digest


def fixture():
    qids = [c.digest("q" + str(i)) for i in range(296)]
    ekeys = [c.digest("e" + str(i)) for i in range(248)]
    qkeys = [c.digest("qf" + str(i)) for i in range(295)]
    units = [{"question_id": qids[i], "question_key": qkeys[i],
              "evidence_key": ekeys[i % len(ekeys)], "family": "f",
              "status": "available"} for i in range(295)]
    units.append({"question_id": qids[-1], "question_key": None,
                  "evidence_key": None, "family": "f",
                  "status": "unavailable_encoder_length"})
    plan = {"units": units}
    index = {"question_ids": qids, "evidence_keys": ekeys}
    features = {}
    for i, key in enumerate(qkeys + ekeys):
        value = torch.arange(1, 9, dtype=torch.float32) * (1 + (i % 17) / 20)
        value[(i + 1) % 8] += 1
        features[key] = F.normalize(value, dim=0).contiguous()
    model = residual.ResidualGate(8)
    with torch.no_grad():
        model.read.copy_(torch.arange(1, 9, dtype=torch.float32) / 8)
    model.eval().requires_grad_(False)
    return plan, index, features, model


class MatrixTests(unittest.TestCase):
    def test_vectorized_matrix_matches_pairwise_model(self):
        plan, index, features, model = fixture()
        matrix = transfer.residual_matrix(plan, index, features, model)
        units = {u["question_id"]: u for u in plan["units"]}
        for i in (0, 19, 294):
            q = features[units[index["question_ids"][i]]["question_key"]].unsqueeze(0)
            for j in (0, 7, 247):
                e = features[index["evidence_keys"][j]].unsqueeze(0)
                self.assertAlmostEqual(float(matrix[i, j]),
                                       float(model(q, e).double()[0]), places=7)
        self.assertTrue(bool(torch.isnan(matrix[-1]).all()))

    def test_target_identity_does_not_enter_score_construction(self):
        plan, index, features, model = fixture()
        before = transfer.residual_matrix(plan, index, features, model)
        changed = deepcopy(plan)
        changed["units"][0]["evidence_key"] = index["evidence_keys"][-1]
        after = transfer.residual_matrix(changed, index, features, model)
        self.assertTrue(torch.equal(torch.isnan(before), torch.isnan(after)))
        self.assertTrue(torch.equal(torch.nan_to_num(before), torch.nan_to_num(after)))

    def test_checkpoint_features_and_plan_are_immutable(self):
        plan, index, features, model = fixture()
        plan_sha = c.digest([plan, index])
        model_before = parameters(model)
        features_before = {k: tensor_digest(v) for k, v in features.items()}
        transfer.residual_matrix(plan, index, features, model)
        self.assertEqual(plan_sha, c.digest([plan, index]))
        self.assertEqual(model_before, parameters(model))
        self.assertEqual(features_before, {k: tensor_digest(v) for k, v in features.items()})

    def test_scale_grid_preserves_mask_and_exact_linear_values(self):
        plan, index, features, model = fixture()
        direction = transfer.residual_matrix(plan, index, features, model)
        cosine = torch.ones_like(direction); cosine[-1] = float("nan")
        out = transfer.scaled_matrices(cosine, direction, "head")
        self.assertEqual(set(out), {transfer.method_name("head", alpha)
                                    for alpha in transfer.ALPHAS[1:]})
        for alpha in transfer.ALPHAS[1:]:
            value = out[transfer.method_name("head", alpha)]
            self.assertTrue(torch.equal(torch.isnan(value), torch.isnan(cosine)))
            self.assertEqual(float(value[0, 0]), 1 + alpha * float(direction[0, 0]))

    def test_wrong_denominator_and_scale_rejected(self):
        plan, index, features, model = fixture()
        with self.assertRaises(c.Invalid):
            transfer.residual_matrix(plan,
                                     {**index, "question_ids": index["question_ids"][:-1]},
                                     features, model)
        for alpha in (0.0, True, 1, .03):
            with self.assertRaises(c.Invalid):
                transfer.method_name("head", alpha)

    def test_method_census_is_complete_and_unique(self):
        names = {"a", "b"}
        methods = transfer.method_census(names)
        self.assertEqual(len(methods), 2 * (len(transfer.ALPHAS) - 1))
        self.assertEqual(len(methods), len(set(methods)))


class EntrypointTests(unittest.TestCase):
    def test_help_from_foreign_directory_without_pythonpath(self):
        script = Path(transfer.__file__).with_name("full_select_residual_transfer_trial.py")
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(script), "--help"], cwd=directory,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--full-archive", run.stdout)
        self.assertIn("--v3-archive", run.stdout)
        self.assertIn("--crossed-archive", run.stdout)
        self.assertNotIn("ModuleNotFoundError", run.stderr)


if __name__ == "__main__":
    unittest.main()
