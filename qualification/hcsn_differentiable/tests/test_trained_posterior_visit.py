"""Post-update posterior and drift-stress *mechanism* checks.

This tiny synthetic 6/3-grid fixture visits posterior states after actual
optimizer updates. It is intentionally NOT a high-precision continuum
reference, a full-domain certification, or adequate training evidence.
"""
import math
import unittest

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork
from qualification.hcsn_differentiable.regenerative import first_hit_regime


class TrainedPosteriorVisitTests(unittest.TestCase):
    def test_post_update_posterior_ad_fd_and_signed_drift_stress(self):
        torch.manual_seed(20261110)
        grid = GridSpec(active_cells=6, phase_cells=3, quadrature_order=8)
        model = ContinuousSpikingNetwork(
            3, content_dim=3, output_dim=1, layer_count=1, grid=grid
        ).double()
        features = torch.tensor([
            [[0.2, -0.1, 0.6], [0.5, 0.3, -0.2], [0.0, 0.4, 0.3], [-0.3, 0.8, 0.2]],
            [[0.1, 0.5, -0.4], [-0.2, 0.2, 0.8], [0.3, -0.6, 0.4], [0.6, 0.1, 0.2]],
        ], dtype=torch.float64)
        # Zero, short, unaligned and maximal supported gaps, without clipping.
        dt = torch.tensor([[0.0, 0.03, 0.08, 0.1],
                           [0.02, 0.1, 0.02, 0.07]], dtype=torch.float64)
        observed = torch.ones((2, 4), dtype=torch.bool)
        target = torch.tensor([0.25, -0.15], dtype=torch.float64)

        def forward_with_fresh_state(*, observed_mask=observed):
            state = model.initial_state(2, absolute_initial=math.exp(0.18))
            return model(features, dt, state=state, observed=observed_mask,
                         return_trace=True)

        def objective():
            prediction = forward_with_fresh_state().predictions[:, -1, 0]
            return (prediction - target).square().mean()

        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        for _ in range(2):
            optimizer.zero_grad(set_to_none=True)
            objective().backward()
            optimizer.step()
        fitted = forward_with_fresh_state()
        unobserved = forward_with_fresh_state(observed_mask=torch.zeros_like(observed))
        learned_delta = float((fitted.state.layers[0].probability
                               - unobserved.state.layers[0].probability).abs().max())
        self.assertGreater(learned_delta, 1e-7)
        self.assertTrue(bool(torch.isfinite(fitted.predictions).all()))
        self.assertTrue(bool(torch.isfinite(fitted.expected_events).all()))
        self.assertGreaterEqual(float(fitted.expected_events.min()), -1e-12)
        for row in fitted.trace:
            p = row[0]["probability"]
            torch.testing.assert_close(p.sum(-1), torch.ones(2, dtype=torch.float64),
                                       rtol=0, atol=model.mass_tolerance)
            self.assertGreaterEqual(float(p.min()), -model.mass_tolerance)

        raw_mu = model.layers[0].physics.raw_mu
        derivative, = torch.autograd.grad(objective(), raw_mu)
        ad = float(derivative)
        original = raw_mu.detach().clone()
        h = 2e-5
        try:
            with torch.no_grad():
                raw_mu.copy_(original + h)
                plus = float(objective())
                raw_mu.copy_(original - h)
                minus = float(objective())
        finally:
            with torch.no_grad():
                raw_mu.copy_(original)
        fd = (plus - minus) / (2 * h)
        self.assertTrue(math.isfinite(ad) and math.isfinite(fd))
        self.assertLess(abs(ad-fd), 1e-4 * max(1.0, abs(ad), abs(fd)))

        fitted_physics = model.layers[0].physics()
        visited = {"mu": float(fitted_physics.mu.detach()),
                   "sigma": float(fitted_physics.sigma.detach()),
                   "log_boundary": float(fitted_physics.log_boundary.detach()),
                   "absolute_reset": float(fitted_physics.absolute_reset.detach())}
        per_regime = []
        for mu in (-0.25, 0.0, 0.25):
            # A declared signed-drift *stress*, not another trained checkpoint.
            with torch.no_grad():
                raw_mu.fill_(math.atanh(mu / 0.8))
            result = forward_with_fresh_state()
            for row in result.trace:
                p = row[0]["probability"]
                self.assertLessEqual(float((p.sum(-1)-1.0).abs().max()), model.mass_tolerance)
            diagnostic = first_hit_regime(0.18, model.layers[0].physics(), refractory=grid.refractory)
            per_regime.append({"mu": mu, "regime": diagnostic.drift_regime,
                               "unconditional_mean_hit_time": diagnostic.mean_first_hit_time,
                               "long_run_event_rate": diagnostic.long_run_event_rate,
                               "max_mass_error": result.diagnostics["maximum_mass_residual"]})
        with torch.no_grad():
            raw_mu.copy_(original)
        self.assertEqual([item["regime"] for item in per_regime],
                         ["negative", "zero", "positive"])
        self.measurements = {
            "scope": "two synthetic optimizer updates; 6-active/3-phase FP64 only",
            "training_updates": 2,
            "trained_physics_visited": visited,
            "post_update_conditioning_delta": learned_delta,
            "post_update_mu_gradient": {"ad": ad, "central_fd": fd, "step": h},
            "declared_signed_drift_stress_not_training": per_regime,
            "full_posterior_continuum_qualification": False,
            "independent_real_task_effect": False,
        }
