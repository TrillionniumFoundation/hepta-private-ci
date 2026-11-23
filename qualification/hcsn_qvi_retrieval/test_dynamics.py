import unittest

import torch

from qualification.hcsn_adaptive.flow_semantics import FlowSemantics
from qualification.hcsn_differentiable.neural_control import optimal_boundary

from .dynamics import RetrievalFlow, _AbsoluteResetInterval, _batched_boundary


class RetrievalFlowTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(44)
        self.x = torch.tensor([
            [[.2, -.3], [.4, .8], [-.6, .7]],
            [[-.2, .4], [.7, -.5], [.5, .1]],
        ], dtype=torch.float64)
        self.dt = torch.tensor([[.15, .25, .4], [.2, .2, .4]], dtype=torch.float64)

    def test_batched_solver_matches_scalar_reference_and_all_eight_gradients(self):
        model = RetrievalFlow(2)
        torch.testing.assert_close(model.nominal_boundary, model.task.new_tensor(.546649206678534))
        tasks = torch.stack((model.task, model.task.new_tensor(
            [-.4, .6, .35, 1.2, .4, .7, .3, .5]
        )), dim=1).requires_grad_()
        batched = _batched_boundary(tasks)
        scalar = torch.stack([optimal_boundary(p) for p in tasks.T])
        torch.testing.assert_close(batched, scalar, atol=2e-13, rtol=2e-13)
        torch.testing.assert_close(
            torch.autograd.grad(batched.sum(), tasks)[0],
            torch.autograd.grad(scalar.sum(), tasks)[0], atol=2e-11, rtol=2e-11,
        )

    def test_nominal_parity_with_original_physical_step_and_frozen_policies(self):
        model = RetrievalFlow(2, mode="fixed")
        x, dt = self.x[:1], self.dt[:1]
        with torch.no_grad():
            model.flow.drive.weight.zero_()
            model.flow.drive.bias.zero_()
            state = model.flow.initial_state(1, boundary=model.nominal_boundary)
            reference = []
            for t in range(x.shape[1]):
                channels, state, _ = model.flow.step_physical(
                    x[:, t], state, semantics=FlowSemantics("event_mask"),
                    dt=float(dt[0, t]), write_mask=[1],
                )
                reference.append(channels)
            expected = torch.stack(reference, 1)
            for mode in ("fixed", "learned", "qvi"):
                candidate = RetrievalFlow(2, mode=mode)
                candidate.flow.load_state_dict(model.flow.state_dict())
                torch.testing.assert_close(candidate(x, dt), expected, atol=2e-12, rtol=2e-12)

    def test_absolute_reset_matches_first_moment_and_generator_invariants(self):
        model = RetrievalFlow(2)
        b = model.task.new_tensor([.5, .64])
        held = _AbsoluteResetInterval(model.flow, b, model.task[3])
        generator, event, _ = held._generator(model.task.new_tensor([-.2, -.05]))
        cfg = model.flow.config
        row = cfg.bins + cfg.stages - 1
        weights = generator[:, row, :cfg.bins] * (cfg.refractory / cfg.stages)
        torch.testing.assert_close((weights * (model.flow.centers + b[:, None])).sum(-1),
                                   model.task[3].expand_as(b), atol=1e-13, rtol=0)
        torch.testing.assert_close(generator.sum(-1), torch.zeros_like(event), atol=2e-14, rtol=0)
        self.assertTrue(bool((weights >= 0).all()))

    def test_forward_edit_autograd_finite_differences_and_causality(self):
        for mode in ("fixed", "learned", "qvi"):
            with self.subTest(mode=mode):
                torch.manual_seed(44)
                model = RetrievalFlow(2, content_size=2, mode=mode)
                theta = torch.full_like(model.initial_edit_vector(), .17).requires_grad_()
                self.assertTrue(torch.autograd.gradcheck(
                    lambda v: model.features_with_edit(v, self.x, self.dt),
                    (theta,), eps=1e-5, atol=2e-6, rtol=2e-4, fast_mode=True,
                ))
                out = model(self.x, self.dt)
                torch.testing.assert_close(out, model.features_with_edit(
                    model.initial_edit_vector(), self.x, self.dt
                ))
                risk = out[:, :, model.feature_names.index("first_event_probability")]
                count = out[:, :, model.feature_names.index("expected_event_count")]
                self.assertTrue(bool(((risk >= -1e-12) & (risk <= 1+1e-12) & (count >= risk-1e-12)).all()))
                torch.testing.assert_close(out[:, :2], model(self.x[:, :2], self.dt[:, :2]))
                separate = torch.cat([model(a[None], d[None]) for a, d in zip(self.x, self.dt)])
                torch.testing.assert_close(out, separate, atol=2e-12, rtol=2e-12)

    def test_invalid_clock_and_cost(self):
        with self.assertRaises(ValueError):
            RetrievalFlow(2, spike_cost=-.01)
        with self.assertRaises(ValueError):
            RetrievalFlow(2)(self.x, self.dt + .0000003)


if __name__ == "__main__":
    unittest.main()
