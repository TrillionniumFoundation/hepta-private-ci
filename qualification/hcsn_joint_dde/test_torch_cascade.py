"""Native complete-output/gradient checks against the separate SciPy DDE."""

from fractions import Fraction
import json
import math
import unittest

import numpy as np
import torch

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_joint_dde.torch_cascade import FIELDS, cascade_flow, flatten


def fixture():
    theta = torch.tensor([.01, -.12, .5, math.exp(.54), .21, .15], dtype=torch.float64)
    active = torch.tensor([0., .1, .08, .06, .09, .07, .08, .07], dtype=torch.float64)
    content = torch.tensor([[0., 0.], [.1, -.2], [-.1, .04], [.3, -.01], [-.2, .3],
                            [.01, -.05], [.07, -.11], [-.12, .05]], dtype=torch.float64)
    phase = ((.035, .113, torch.tensor([.2, -.31, .27], dtype=torch.float64)),
             (.071, .071, torch.tensor([.15, .23, -.13], dtype=torch.float64)))
    return theta, active, content, phase


class CascadeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_all_fields_against_independent_dde(self):
        theta, active, content, phase = fixture()
        times = [0., .13, .29, .53]
        cases = (("active", active, content, ()),
                 ("phase", active*0, content*0, phase),
                 ("mixed", active, content, phase))
        evidence = []
        for name, p, c, packets in cases:
            model = JointModel(KilledSpatialGenerator(len(p)-1, 2., -.12, .5), .53, .21, .15)
            exact_phase = tuple(Packet(str(i), Fraction(str(a)), Fraction(str(b)),
                Fraction(str(float(v[0]))), tuple(Fraction(str(float(x))) for x in v[1:]))
                for i, (a, b, v) in enumerate(packets))
            reference = model.solve(times, p.numpy(), c.numpy(), exact_phase,
                                    rtol=2e-11, atol=2e-13, max_step=.01)
            rows = cascade_flow(theta, times, p, c, packets)
            errors = {}
            for candidate, old in zip(rows, reference["rows"]):
                for field in FIELDS:
                    actual = candidate[field].detach().numpy()
                    np.testing.assert_allclose(actual, old[field], atol=3e-9, rtol=3e-8)
                    errors[field] = max(errors.get(field, 0.), float(np.max(abs(actual-old[field]))))
                total = candidate["active"].sum(0)+candidate["upper"]+candidate["refractory"]
                original = torch.cat((p.sum().reshape(1), c.sum(0)))
                original = original + sum((v for _, _, v in packets), torch.zeros_like(original))
                torch.testing.assert_close(total, original, atol=3e-12, rtol=3e-12)
            evidence.append(dict(case=name, fields=errors))
        print("INDEPENDENT_DDE", json.dumps(evidence, sort_keys=True), flush=True)

    def test_all_six_physical_parameters_full_output_gradcheck(self):
        theta, active, content, phase = fixture()
        theta.requires_grad_()
        self.assertTrue(torch.autograd.gradcheck(
            lambda p: flatten(cascade_flow(p, [.53], active, content, phase)),
            (theta,), eps=2e-5, atol=2e-7, rtol=3e-5, fast_mode=False))
        value = flatten(cascade_flow(theta, [.53], active, content, phase))
        weights = torch.linspace(-.7, 1.3, len(value), dtype=torch.float64)
        gradient = torch.autograd.grad(value@weights, theta)[0]
        self.assertTrue(bool(torch.isfinite(gradient).all() and (gradient.abs()>1e-9).all()))
        print("PHYSICAL_GRADIENT", json.dumps(gradient.tolist()), flush=True)

    def test_learnable_initial_probability_content_phase_and_support(self):
        theta, active, content, phase = fixture()
        logits = torch.linspace(-.4, .5, len(active)-1, dtype=torch.float64, requires_grad=True)
        marked = content[1:].clone().requires_grad_()
        values = torch.stack([v for _, _, v in phase]).requires_grad_()
        support = torch.tensor([.035, .113, .071], dtype=torch.float64, requires_grad=True)

        def flow(prior, marks, vectors, endpoints):
            probability = torch.cat((prior.new_zeros(1), .65*torch.softmax(prior, dim=0)))
            transported = torch.cat((marks.new_zeros((1, 2)), marks), dim=0)
            atom = endpoints[2]
            packets = ((endpoints[0], endpoints[1], vectors[0]), (atom, atom, vectors[1]))
            return flatten(cascade_flow(theta, [.29, .53], probability, transported, packets))

        self.assertTrue(torch.autograd.gradcheck(flow, (logits, marked, values, support),
            eps=1e-5, atol=2e-7, rtol=3e-5, fast_mode=True))
        output = flow(logits, marked, values, support)
        gradients = torch.autograd.grad(output@torch.linspace(-.8, 1.2, len(output), dtype=torch.float64),
                                        (logits, marked, values, support))
        self.assertTrue(all(bool(torch.isfinite(g).all() and g.abs().max()>1e-9) for g in gradients))
        print("INITIAL_GRADIENTS", json.dumps([g.detach().tolist() for g in gradients]), flush=True)

    def test_absolute_prior_boundary_chain_rule_is_preserved(self):
        theta, _, content, phase = fixture()
        theta.requires_grad_()
        nodes = torch.linspace(0, 2., len(content), dtype=torch.float64)[1:]

        def flow(p):
            # The same absolute Gaussian prior changes its relative weights when
            # B changes. This verifies both the prior and reset derivative paths.
            scores = -((nodes+p[0]-.8)/.4).square()/2
            probability = torch.cat((p.new_zeros(1), .65*torch.softmax(scores, 0)))
            return flatten(cascade_flow(p, [.53], probability, content, phase))

        self.assertTrue(torch.autograd.gradcheck(flow, (theta,), eps=1e-5,
                                               atol=2e-7, rtol=3e-5, fast_mode=True))

    def test_queries_do_not_rebin_or_change_the_flow(self):
        theta, active, content, phase = fixture()
        direct = flatten(cascade_flow(theta, [.53], active, content, phase))
        split = cascade_flow(theta, [.03, .13, .29, .53], active, content, phase)
        torch.testing.assert_close(direct, flatten(split[-1:]), rtol=0, atol=0)

    def test_undefined_derivatives_and_resource_overflow_are_rejected(self):
        theta, active, content, phase = fixture()
        for position, value in ((2, 0.), (2, 1e200), (3, math.exp(.01+2/7*2)), (4, 0.), (5, 0.)):
            changed = theta.clone()
            changed[position] = value
            with self.assertRaises(ValueError):
                cascade_flow(changed, [.53], active, content, phase)
        for times in ([.21], [.071], [8.], [.2, .1]):
            with self.assertRaises(ValueError):
                cascade_flow(theta, times, active, content, phase)
        lower = active.clone()
        lower[0] = .01
        with self.assertRaises(ValueError):
            cascade_flow(theta, [.53], lower, content, phase)
        front = torch.tensor(0., dtype=torch.float64, requires_grad=True)
        for packet in ((front, front, phase[0][2]), (front, .1, phase[0][2])):
            with self.assertRaises(ValueError):
                cascade_flow(theta, [0., .53], active, content, (packet,))


if __name__ == "__main__":
    unittest.main()
