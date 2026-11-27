"""Actual shared-generator U/F backward, phase-age identity and F!=M."""

from fractions import Fraction
import json
import math
import unittest

import torch

from qualification.hcsn_reset_aligned.torch_first_hit import first_hit_readout
from qualification.hcsn_reset_aligned.torch_flow import aligned_flow
from qualification.hcsn_reset_aligned.torch_perpetual import perpetual_readout


GEOMETRY = dict(left_intervals=4, right_intervals=4, endpoint=2., grading=1., delay=.2)
OPTIONS = dict(rtol=2e-11, atol=2e-13, max_step=.02)


class NativeReadouts(unittest.TestCase):
    records = []

    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        print("NATIVE_UF_EVIDENCE", json.dumps(cls.records, sort_keys=True))

    def setUp(self):
        self.theta = torch.tensor([.01, -.12, .5, math.exp(.51), .15],
                                   dtype=torch.float64, requires_grad=True)
        p = torch.arange(1., 9., dtype=torch.float64)/36
        self.law = torch.stack((p, -.4*p), -1).requires_grad_()

    def test_joint_uf_physical_and_law_gradcheck(self):
        def both(theta, law):
            states = aligned_flow(theta, law, [.1, .6], geometry=GEOMETRY, **OPTIONS)
            return torch.cat((perpetual_readout(theta, states, geometry=GEOMETRY),
                              first_hit_readout(theta, law, [.1, .6], geometry=GEOMETRY)), -1)
        torch.manual_seed(922)
        passed = torch.autograd.gradcheck(both, (self.theta, self.law),
            eps=1e-4, atol=1e-5, rtol=6e-4, fast_mode=True)
        self.assertTrue(passed)
        self.records.append(dict(case="joint_U_F_gradcheck", passed=True,
                                 fixed_initial_active_law=True))

    def test_u_uses_remaining_age_and_full_history_in_backward(self):
        phase = torch.tensor([[.3, -.12]], dtype=torch.float64)
        law = torch.cat((.7*self.law.detach(), phase)).requires_grad_()
        times = torch.tensor([0., .1, .4, .6], dtype=torch.float64)
        states = aligned_flow(self.theta, law, times.tolist(), geometry=GEOMETRY,
            phase_supports=((Fraction(1,20), Fraction(3,20)),), **OPTIONS)
        u = perpetual_readout(self.theta, states, geometry=GEOMETRY)
        total = .4*states[:, 11]+states[:, 10]+torch.exp(-self.theta[4]*times)[:, None]*u
        residual = total-total[0]
        gp, gl = torch.autograd.grad(residual[-1].sum(), (self.theta, law))
        self.assertLess(float(residual.detach().abs().max()), 4e-8)
        self.assertLess(float(gp.abs().max()), 8e-8)
        self.assertLess(float(gl.abs().max()), 8e-8)
        self.records.append(dict(case="U_dynamic_identity_with_phase", primal=float(residual.detach().abs().max()),
            physical_gradient=float(gp.abs().max()), law_gradient=float(gl.abs().max())))

    def test_first_hit_is_not_renewal_count_and_rejects_phase(self):
        first = first_hit_readout(self.theta, self.law, [.6], geometry=GEOMETRY)
        states = aligned_flow(self.theta, self.law, [.6], geometry=GEOMETRY, **OPTIONS)
        self.assertGreater(float((states[0, 9, 0]-first[0, 0]).detach()), 1e-4)
        gp = torch.autograd.grad(first[0, 0], self.theta)[0]
        self.assertEqual(float(gp[4]), 0.)
        with self.assertRaisesRegex(ValueError, "phase is unsupported"):
            first_hit_readout(self.theta, torch.cat((self.law, self.law[:1])), [.6], geometry=GEOMETRY)
        self.records.append(dict(case="F_not_M", F=float(first[0,0].detach()), M=float(states[0,9,0].detach()),
                                 discount_gradient=float(gp[4]), phase_supported=False))


if __name__ == "__main__":
    unittest.main()
