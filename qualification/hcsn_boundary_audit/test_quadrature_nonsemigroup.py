"""P1 quadrature counterfactual: increasing quadrature does not remove the fixed-grid two-step defect.
Synthetic zero-drift finite-grid diagnostic only. Not a continuum-error or science-admission test.
"""
import unittest
import json
import torch
from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator
DT = 0.02
ORDERS = (8, 16, 32, 64)
PARAMS = {"log_boundary": 0.0, "mu": 0.0, "sigma": 0.35,
          "absolute_reset": 1.7332530178673953, "discount": 0.08}

def observation(order):
    grid = GridSpec(active_cells=16, endpoint=4.8, phase_cells=8, refractory=0.2,
                    tail_rate=1.0, quadrature_order=order, initial_log_std=0.08)
    params = {k: torch.tensor(v, dtype=torch.float64) for k, v in PARAMS.items()}
    with torch.no_grad():
        op = DifferentiableDistributionOperator(grid)
        q = op(dt=DT, **params).matrix
        qdouble = op(dt=2 * DT, **params).matrix
        composed = q @ q
        tv = 0.5 * (composed - qdouble).abs().sum(dim=-1)
        return {"order": order, "max_tv": float(tv.max()), "active_mean_tv": float(tv[:grid.active_count].mean()),
                "mass_error": float(max((composed.sum(-1) - 1).abs().max(),
                                        (q.sum(-1) - 1).abs().max(),
                                        (qdouble.sum(-1) - 1).abs().max())),
                "finite": bool(torch.isfinite(q).all() and torch.isfinite(qdouble).all() and torch.isfinite(composed).all())}

class TestQuadratureCounterfactual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.rows = {order: observation(order) for order in ORDERS}
        print("OBSERVATIONS="+json.dumps([cls.rows[o] for o in ORDERS],sort_keys=True),flush=True)

    def test_mass_finite_and_large_defect_at_all_orders(self):
        for order, row in self.rows.items():
            with self.subTest(order=order):
                self.assertTrue(row["finite"])
                self.assertLess(row["mass_error"], 1e-11)
                self.assertGreater(row["max_tv"], 0.09)

    def test_increasing_quadrature_16_to_64_does_not_cure_defect(self):
        original = self.rows[16]["max_tv"]
        high = self.rows[64]["max_tv"]
        self.assertLess(abs(high - original), 1e-6)
        self.assertGreater(high / original, 0.999)

if __name__ == "__main__":
    unittest.main(verbosity=2)
