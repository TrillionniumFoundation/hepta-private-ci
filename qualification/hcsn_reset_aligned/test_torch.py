"""Native Torch checks and a declared synthetic physics-fit adequacy target."""

from fractions import Fraction
import json
import math
import time
import unittest

import numpy as np
import torch

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_reset_aligned.mesh import aligned_model
from qualification.hcsn_reset_aligned.torch_flow import aligned_flow


OPTIONS = dict(rtol=2e-10, atol=2e-12, max_step=.02)
GEOMETRY = dict(left_intervals=4, right_intervals=4, endpoint=2., grading=1., delay=.2)


class NativeAlignedVjp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.records = []

    @classmethod
    def tearDownClass(cls):
        print("NATIVE_ALIGNED_EVIDENCE", json.dumps(dict(records=cls.records,
            first_order_cpu_fp64=True, fixed_moving_nodal_prior=True,
            full_network_training=False, independent_source_benefit=False), sort_keys=True))

    def test_joint_physical_initial_law_gradcheck_at_former_reset_knot(self):
        theta = torch.tensor([.01, -.12, .5, math.exp(.51), .15],
                              dtype=torch.float64, requires_grad=True)
        p = torch.arange(1., 10., dtype=torch.float64)/45
        law = torch.stack((p, -2*p), -1).requires_grad_()
        supports = ((Fraction(1,20), Fraction(3,20)),)
        torch.manual_seed(419)
        passed = torch.autograd.gradcheck(lambda t, x: aligned_flow(t, x, [0., .2, .6],
            geometry=GEOMETRY, phase_supports=supports, **OPTIONS), (theta, law),
            eps=1e-4, atol=6e-6, rtol=7e-4, fast_mode=True)
        self.assertTrue(passed)
        self.records.append(dict(case="joint_gradcheck", passed=True,
                                 former_uniform_reset_node=.5))

    def test_learns_known_reset_and_signed_mark_with_adequacy_goal(self):
        started = time.perf_counter()
        target_theta = np.array([.01, -.12, .5, math.exp(.66), .15])
        teacher = aligned_model(target_theta, **GEOMETRY)[0]
        phase = (Packet("teacher", Fraction(0), Fraction(0), Fraction(1), (Fraction(2),)),)
        rows = teacher.solve([.3, .6], np.zeros(9), np.zeros((9, 1)), phase, **OPTIONS)["rows"]
        target = torch.tensor([[row["events"].tolist(), row["discounted_active_time"].tolist()]
                               for row in rows], dtype=torch.float64)
        raw_reset = torch.nn.Parameter(torch.tensor(math.log(.22/.78), dtype=torch.float64))
        mark = torch.nn.Parameter(torch.tensor(.5, dtype=torch.float64))
        optimizer = torch.optim.Adam([raw_reset, mark], lr=.04)
        records = []
        # This target and budget are fixed in source before running the fit.
        target_relative_mse, maximum_updates = 2e-4, 120
        normalizer = target.square().mean()
        for step in range(maximum_updates+1):
            optimizer.zero_grad(set_to_none=True)
            reset = .2+torch.sigmoid(raw_reset)
            theta = torch.stack((reset*0+.01, reset*0-.12, reset*0+.5,
                                 torch.exp(reset+.01), reset*0+.15))
            nodal = torch.zeros((8, 2), dtype=torch.float64)
            law = torch.cat((nodal, torch.stack((mark*0+1, mark))[None]))
            output = aligned_flow(theta, law, [.3, .6], geometry=GEOMETRY,
                                  phase_supports=((Fraction(0), Fraction(0)),), **OPTIONS)
            prediction = output[:, [9, 11]]
            loss = (prediction-target).square().mean()/normalizer
            loss.backward()
            gradients = [float(raw_reset.grad), float(mark.grad)]
            self.assertTrue(all(math.isfinite(g) for g in gradients))
            records.append(dict(step=step, relative_mse=float(loss.detach()),
                reset=float(reset.detach()), mark=float(mark.detach()), gradients=gradients))
            if step == maximum_updates:
                break
            optimizer.step()
        self.assertLess(records[-1]["relative_mse"], target_relative_mse)
        self.assertGreater(records[0]["relative_mse"] / records[-1]["relative_mse"], 100)
        self.assertLess(records[0]["reset"], .5)
        self.assertGreater(records[-1]["reset"], .5)
        self.records.append(dict(case="synthetic_known_physics_fit", records=records,
            actual_optimizer_updates=maximum_updates, loss_goal=target_relative_mse,
            goal_met=True, crossing_old_node=.5, teacher_reset=.65, teacher_mark=2.,
            wall_seconds=time.perf_counter()-started,
            scope="two scalar parameters on a same-model synthetic diagnostic, no task-generalization claim"))


if __name__ == "__main__":
    unittest.main()
