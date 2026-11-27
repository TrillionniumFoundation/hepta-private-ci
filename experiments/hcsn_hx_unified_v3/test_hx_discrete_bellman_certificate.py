"""Prove a finite rational Bellman *grid*, without claiming continuum HX."""
from dataclasses import replace
import unittest
from .hx import HX, boundary
from .hx_joint_pde_obstacle import audit_fixed_barrier_from_bond_pde
from .hx_discrete_bellman_certificate import (
    certify_quantized_financial_grid, UnresolvedDiscreteCertificate)


class ExactFiniteCertificateTests(unittest.TestCase):
    def test_bounded_finite_grid_certifies_nominal_continue(self):
        p=HX(); b=boundary(p)
        out=audit_fixed_barrier_from_bond_pde(p,b,nodes=401,bond_time_steps=1000)
        proof=certify_quantized_financial_grid(p,out)
        self.assertEqual(len(proof.guaranteed_continue),399)
        self.assertEqual(proof.guaranteed_stop,())
        self.assertEqual(proof.ambiguous,())
        self.assertLess(float(proof.sup_value_error_bound),1e-6)
        self.assertFalse(proof.scientific_gate_closed)
        self.assertFalse(proof.production_activation)

    def test_high_liquidity_fine_grid_certifies_two_stop_nodes(self):
        p=HX(sale_fraction=.2); b=boundary(p)
        out=audit_fixed_barrier_from_bond_pde(p,b,nodes=401,bond_time_steps=1000)
        proof=certify_quantized_financial_grid(p,out)
        self.assertEqual(proof.guaranteed_stop,(2,3))
        self.assertEqual(len(proof.guaranteed_continue),397)
        self.assertEqual(proof.ambiguous,())
        self.assertLess(float(proof.sup_value_error_bound),1e-5)

    def test_coarse_grid_can_be_certified_and_still_wrong_as_financial_model(self):
        p=HX(sale_fraction=.2); b=boundary(p)
        out=audit_fixed_barrier_from_bond_pde(p,b,nodes=101,bond_time_steps=250)
        proof=certify_quantized_financial_grid(p,out)
        # Exact arithmetic proves the finite grid's result, NOT the continuum.
        self.assertEqual(len(proof.guaranteed_continue),99)
        self.assertFalse(proof.guaranteed_stop)
        self.assertFalse(proof.ambiguous)
        self.assertFalse(proof.scientific_gate_closed)

    def test_unresolved_candidate_does_not_grant_certified_policy(self):
        p=HX(); b=boundary(p)
        out=audit_fixed_barrier_from_bond_pde(p,b,nodes=101,bond_time_steps=250)
        values=list(out.equity_values)
        values[50]+=10.0
        changed=replace(out,equity_values=tuple(values))
        proof=certify_quantized_financial_grid(p,changed)
        self.assertGreater(float(proof.sup_value_error_bound),1.0)
        self.assertTrue(proof.ambiguous)

    def test_invalid_inputs_refused(self):
        p=HX(); b=boundary(p)
        out=audit_fixed_barrier_from_bond_pde(p,b,nodes=101,bond_time_steps=250)
        with self.assertRaises(UnresolvedDiscreteCertificate):
            certify_quantized_financial_grid(p,replace(out,equity_values=(1.,)))
        with self.assertRaises(UnresolvedDiscreteCertificate):
            certify_quantized_financial_grid(p,replace(out,candidate_barrier=-1.))

if __name__=='__main__':unittest.main()
