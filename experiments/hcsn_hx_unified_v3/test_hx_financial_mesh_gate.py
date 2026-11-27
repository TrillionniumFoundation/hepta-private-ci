"""A disagreement is an explicit blocker, never a green release signal."""
import unittest
from .hx import HX, boundary
from .hx_financial_mesh_gate import financial_obstacle_mesh_gate, _within_one_local_cell

class MeshGateTests(unittest.TestCase):
    def test_hazard_counterexample_refuses_coarse_method_disagreement(self):
        p=HX(sale_fraction=.2)
        gate=financial_obstacle_mesh_gate(p,boundary(p))
        self.assertEqual(gate.status,'NUMERICAL_DISAGREEMENT_NO_GO')
        self.assertFalse(gate.comparisons[0].exact_decision_agreement)
        self.assertTrue(all(v.exact_decision_agreement for v in gate.comparisons[1:]))
        self.assertFalse(gate.scientific_gate_closed)
        self.assertFalse(gate.production_activation)

    def test_nominal_all_agree_still_deny_production(self):
        p=HX()
        gate=financial_obstacle_mesh_gate(p,boundary(p))
        self.assertEqual(gate.status,'MESH_AGREEMENT_NOT_GLOBAL_PROOF')
        self.assertTrue(all(v.endpoint_within_one_cell for v in gate.comparisons))
        self.assertFalse(gate.scientific_gate_closed)
        self.assertFalse(gate.production_activation)

    def test_endpoint_tolerance_uses_local_cell_not_far_field(self):
        self.assertTrue(_within_one_local_cell(None,None,101,3.6))
        self.assertFalse(_within_one_local_cell(None,103.,101,3.6))
        self.assertTrue(_within_one_local_cell(103.,104.,101,3.6))
        # Old right-edge-derived tolerance was huge and falsely accepted this.
        self.assertFalse(_within_one_local_cell(103.,200.,101,3.6))

    def test_invalid_mesh_plan_refused(self):
        p=HX()
        with self.assertRaises(ValueError):
            financial_obstacle_mesh_gate(p,boundary(p),meshes=((101,250),(101,500)))
        with self.assertRaises(ValueError):
            financial_obstacle_mesh_gate(p,boundary(p),meshes=((101,250),))

if __name__=='__main__':unittest.main()
