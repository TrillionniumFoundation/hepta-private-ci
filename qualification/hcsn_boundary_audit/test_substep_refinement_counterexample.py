"""P1 held-out numerical negative control: smaller propagation substeps can increase error.

This is a synthetic fixed-grid, fixed-parameter diagnostic. It is neither an
exact continuum value error estimate nor a scientific qualification. We
deliberately compare the same total time, using the same source projection
and frozen physical parameters. The historical counterexample is preserved;
a future numerical repair must replace this sentinel with positive gates.
"""
import hashlib
import json
import unittest
from pathlib import Path

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator

SOURCE_SHA256 = "cb3eed1bcfbd3b10cc331a193a5d4b6a3d4309db899e0d8f821477f97b7dbdc1"
GRID = GridSpec(active_cells=16, endpoint=4.8, phase_cells=8,
                refractory=0.2, tail_rate=1.0, quadrature_order=16,
                initial_log_std=0.08)
DRIFTS = (-0.4, 0.0, 0.4)
SUBSTEPS = (2, 4, 8, 16, 32)
TOTAL_DT = 0.02


def observe(mu, operator):
    params = {name: torch.tensor(value, dtype=torch.float64) for name, value in
              {"log_boundary": 0.0, "mu": mu, "sigma": 0.35,
               "absolute_reset": 1.7332530178673953,
               "discount": 0.08}.items()}
    observations = {}
    with torch.no_grad():
        direct = operator(dt=TOTAL_DT, **params).matrix
        for n in SUBSTEPS:
            step = operator(dt=TOTAL_DT / n, **params).matrix
            composed = torch.linalg.matrix_power(step, n)
            tv = 0.5 * (composed - direct).abs().sum(-1)
            observations[n] = {
                "max_tv": float(tv.max()),
                "mean_active_tv": float(tv[:GRID.active_count].mean()),
                "active_max_tv": float(tv[:GRID.active_count].max()),
                "phase_max_tv": float(tv[GRID.active_count:].max()),
                "argmax_row": int(tv.argmax()),
                "mass_error": float((composed.sum(-1) - 1).abs().max()),
                "finite_nonnegative": bool(torch.isfinite(composed).all()
                                           and (composed >= 0).all()),
            }
    return observations


class TestHistoricalSubstepCounterexample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        actual = hashlib.sha256(
            Path("qualification/hcsn_differentiable/operator.py").read_bytes()
        ).hexdigest()
        if actual != SOURCE_SHA256:
            raise RuntimeError("pinned operator source changed; do not relabel result")
        cls.rows = {mu: observe(mu, DifferentiableDistributionOperator(GRID))
                    for mu in DRIFTS}
        print("SUBSTEP_OBSERVATIONS=" + json.dumps(cls.rows, sort_keys=True),
              flush=True)

    def test_all_composed_matrices_remain_finite_and_conservative(self):
        for mu, observations in self.rows.items():
            for n, row in observations.items():
                with self.subTest(mu=mu, n=n):
                    self.assertTrue(row["finite_nonnegative"])
                    self.assertLess(row["mass_error"], 3e-11)

    def test_smaller_substeps_do_not_automatically_improve_this_basis(self):
        for mu, rows in self.rows.items():
            with self.subTest(mu=mu):
                self.assertGreater(rows[2]["max_tv"], 0.31)
                self.assertGreater(rows[32]["max_tv"],
                                   rows[2]["max_tv"] + 0.12)

    def test_first_split_defect_is_largest_on_refractory_phase_rows(self):
        row = self.rows[0.0][2]
        self.assertGreaterEqual(row["argmax_row"], GRID.active_count)
        self.assertGreater(row["phase_max_tv"], row["active_max_tv"] + 0.2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
