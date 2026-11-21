"""Mathematical and continuation checks; no historical experiment is executed."""

from dataclasses import replace
import unittest

import torch

from .batched_flow import BatchedFlow, FlowConfig, FlowState


class BatchedFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def model(self, dtype=torch.float64, **kwargs):
        torch.manual_seed(178)
        return BatchedFlow(FlowConfig(input_size=2, content_size=2, **kwargs)).to(dtype=dtype)

    def test_mass_content_and_risk_under_changing_inputs_and_boundaries(self):
        for dtype, tolerance in ((torch.float64, 2e-11), (torch.float32, 2e-5)):
            model, state = self.model(dtype), None
            rng = torch.Generator().manual_seed(71)
            for _ in range(20):
                inputs = torch.randn(3, 2, generator=rng, dtype=dtype)
                boundary = .25*torch.randn(3, generator=rng, dtype=dtype)
                out, state, diag = model.step(inputs, state, boundary_override=boundary)
                self.assertLess(diag["mass_error"].abs().max().item(), tolerance)
                self.assertLess(diag["content_balance_error"].abs().max().item(), tolerance)
                self.assertLess(diag["generator_row_error"].max().item(), tolerance)
                self.assertGreaterEqual(out[:, 3].min().item(), -tolerance)
                self.assertLessEqual(out[:, 3].max().item(), 1+tolerance)
                self.assertLessEqual(out[:, 5].max().item(), 1+tolerance)
                self.assertTrue(bool((state.density[:, 1:].abs() <= state.density[:, :1]+tolerance).all()))

    def test_batch_dynamics_equal_independent_runs(self):
        model = self.model()
        sequence = torch.tensor([[[1., -.4], [-.2, .9]], [[.5, .8], [-1., .1]]], dtype=torch.float64)
        together, full_state = model(sequence)
        separate = [model(sequence[:, i:i+1]) for i in range(2)]
        torch.testing.assert_close(together, torch.cat([s[0] for s in separate], 1), rtol=2e-11, atol=2e-12)
        torch.testing.assert_close(full_state.density, torch.cat([s[1].density for s in separate]), rtol=2e-11, atol=2e-12)

    def test_input_changes_probability_even_with_zero_content_writer(self):
        model = self.model()
        with torch.no_grad():
            model.drive.weight.fill_(.5)
            model.drive.bias.zero_()
            model.writer.weight.zero_()
            model.writer.bias.zero_()
        inputs = torch.tensor([[2., 2.], [-2., -2.]], dtype=torch.float64)
        state = None
        for _ in range(3):
            output, state, diag = model.step(inputs, state)
        self.assertGreater((state.density[0, 0]-state.density[1, 0]).abs().max().item(), .01)
        self.assertGreater(abs((diag["drift"][0]-diag["drift"][1]).item()), 1.)
        self.assertEqual(output[:, 1:3].abs().max().item(), 0.)

    def test_boundary_projection_accounts_for_instant_hits_and_escape(self):
        model = self.model(bins=4)
        state = model.initial_state(1)
        density = torch.zeros_like(state.density)
        density[0, 0, 0], density[0, 1, 0] = 1., .3
        state = replace(state, density=density)
        moved, alive, jump, _ = model._remap(state, state.boundary+.25)
        torch.testing.assert_close(jump, torch.tensor([[.5, .15, 0.]], dtype=torch.float64))
        torch.testing.assert_close(moved.sum(-1), state.density.sum(-1))
        self.assertEqual(alive.sum().item(), .5)
        escaped, _, jump, _ = model._remap(state, state.boundary-2.)
        torch.testing.assert_close(escaped[..., -1], state.density.sum(-1))
        self.assertEqual(jump.abs().max().item(), 0.)

    def test_frozen_no_write_semigroup_and_event_integral(self):
        model = self.model(write_fraction=0.0)
        x = torch.zeros(2, 2, dtype=torch.float64)
        initial = model.initial_state(2)
        first, mid, _ = model.step(x, initial, dt=.1, drift_override=-.3)
        second, end, _ = model.step(x, mid, dt=.1, drift_override=-.3)
        whole, direct, _ = model.step(x, initial, dt=.2, drift_override=-.3)
        torch.testing.assert_close(end.density, direct.density, rtol=2e-11, atol=2e-12)
        torch.testing.assert_close(first[:, 0]+second[:, 0], whole[:, 0], rtol=2e-11, atol=2e-12)
        torch.testing.assert_close((first[:, 5]+second[:, 5])/2, whole[:, 5], rtol=2e-11, atol=2e-12)
        self.assertEqual(end.time_micros, direct.time_micros)

    def test_drift_and_moving_boundary_autograd_matches_finite_difference(self):
        model = self.model(bins=4)
        x = torch.tensor([[.3, -.1]], dtype=torch.float64)
        state = model.initial_state(1)
        control = torch.tensor([.23, .071], dtype=torch.float64, requires_grad=True)
        weights = torch.tensor([[.3, -.2, .1, .5, -.7, .4, .2]], dtype=torch.float64)

        def loss(z):
            features, _, _ = model.step(x, state, drift_override=z[:1], boundary_override=z[1:])
            return (features*weights).sum()

        derivative = torch.autograd.grad(loss(control), control)[0]
        finite = []
        for i in range(2):
            offset = torch.zeros_like(control)
            offset[i] = 1e-6
            finite.append((loss(control.detach()+offset)-loss(control.detach()-offset))/(2e-6))
        torch.testing.assert_close(derivative, torch.stack(finite), rtol=2e-5, atol=2e-7)
        self.assertGreater(derivative.abs().min().item(), 1e-4)

    def test_cold_snapshot_continuation_and_no_alias(self):
        model = self.model()
        sequence = torch.randn(7, 2, 2, dtype=torch.float64)
        whole, final = model(sequence)
        left, prefix = model(sequence[:3])
        record = prefix.to_record()
        restored = FlowState.from_record(record)
        record["density"].zero_()
        right, resumed = model(sequence[3:], restored)
        self.assertTrue(torch.equal(whole, torch.cat((left, right))))
        self.assertTrue(torch.equal(final.density, resumed.density))
        self.assertEqual(final.time_micros, resumed.time_micros)
        self.assertFalse(restored.density.requires_grad)

    def test_channel_ablation_does_not_change_state_or_other_channels(self):
        model = self.model()
        x = torch.ones(2, 2, dtype=torch.float64)
        whole, original, _ = model.step(x)
        mask = torch.ones(len(model.feature_names), dtype=torch.float64)
        mask[-1] = 0
        ablated, state, _ = model.step(x, feature_mask=mask)
        self.assertTrue(torch.equal(original.density, state.density))
        self.assertTrue(torch.equal(whole[:, :-1], ablated[:, :-1]))
        self.assertEqual(ablated[:, -1].abs().max().item(), 0.)

    def test_streaming_state_has_constant_storage_and_bounded_marks(self):
        for dtype in (torch.float64, torch.float32):
            model = self.model(dtype, bins=4, stages=2)
            state = model.initial_state(2)
            byte_count = state.tensor_bytes()
            x = torch.tensor([[.2, -.4], [-.2, .4]], dtype=dtype)
            with torch.no_grad():
                for _ in range(512):
                    _, state, _ = model.step(x, state)
                    self.assertEqual(state.tensor_bytes(), byte_count)
            self.assertEqual(state.time_micros, 51_200_000)
            self.assertFalse(state.density.requires_grad)
            self.assertLessEqual(state.density[:, 1:].abs().max().item(), 1.00003)

    def test_reflecting_generator_returns_upper_exit_without_changing_lower_or_phase(self):
        absorbing = self.model(bins=4)
        reflecting = self.model(bins=4, upper_mode="reflecting")
        a = torch.tensor([-.2, .8], dtype=torch.float64)
        ga, ea, _ = absorbing._generator(a)
        gr, er, spatial = reflecting._generator(a)
        self.assertTrue(torch.equal(ea, er))
        self.assertTrue(torch.equal(ga[:, 4:], gr[:, 4:]))
        torch.testing.assert_close(gr.sum(-1), torch.zeros_like(gr.sum(-1)), rtol=0, atol=2e-14)
        torch.testing.assert_close(gr[:, 3, 3]-ga[:, 3, 3], ga[:, 3, -1])
        self.assertEqual(spatial[:, :4, -1].abs().max().item(), 0.)

    def test_reflecting_projection_is_explicit_lumping_with_signed_content(self):
        model = self.model(bins=4, upper_mode="reflecting")
        state = model.initial_state(1)
        density = torch.zeros_like(state.density)
        density[0, 0, 3], density[0, 1, 3] = 1., -.4
        state = replace(state, density=density)
        moved, _, _, projected = model._remap(state, state.boundary-.25)
        torch.testing.assert_close(projected, torch.tensor([[.5, -.2, 0.]], dtype=torch.float64))
        torch.testing.assert_close(moved[..., 3], state.density.sum(-1))
        self.assertEqual(moved[..., -1].abs().max().item(), 0.)
        _, _, diagnostics = model.step(torch.zeros(1, 2, dtype=torch.float64), state,
                                        dt=.001, boundary_override=-.25)
        self.assertEqual(diagnostics["upper_projection_destination"], "last_cell")
        self.assertEqual(diagnostics["upper_projection_mass"].item(), .5)

    def test_reflecting_long_flow_retains_active_population_and_existing_phases(self):
        end_states = {}
        for mode in ("absorbing", "reflecting"):
            model = self.model(bins=4, stages=2, upper_mode=mode)
            state = model.initial_state(1)
            density = state.density*.6
            density[:, 0, 4] = .4
            state = replace(state, density=density)
            with torch.no_grad():
                for _ in range(200):
                    _, state, _ = model.step(torch.zeros(1, 2, dtype=torch.float64), state, drift_override=.8)
            end_states[mode] = state
        self.assertGreater(end_states["absorbing"].density[0, 0, -1].item(), .2)
        self.assertEqual(end_states["reflecting"].density[0, 0, -1].item(), 0.)
        self.assertGreater(end_states["reflecting"].density[0, 0, :4].sum().item(), .001)

    def test_mode_switch_and_unrepresented_escape_cannot_reuse_state(self):
        absorbing, reflecting = self.model(), self.model(upper_mode="reflecting")
        inputs = torch.zeros(1, 2, dtype=torch.float64)
        with self.assertRaises(ValueError):
            reflecting.step(inputs, absorbing.initial_state(1))
        state = reflecting.initial_state(1)
        density = torch.zeros_like(state.density)
        density[:, 0, -1] = 1
        with self.assertRaises(ValueError):
            reflecting.step(inputs, replace(state, density=density))

    def test_mixed_precision_is_explicit_and_gradients_reach_fp32_parameters(self):
        model = self.model(torch.float32)
        x = torch.tensor([[.2, -.1], [.5, .3]], dtype=torch.float32)
        output, state, diagnostics = model.step(x)
        self.assertEqual(state.config.transport_precision, "float64")
        self.assertEqual(state.density.dtype, torch.float64)
        self.assertEqual(model.edges.dtype, torch.float64)
        self.assertEqual(output.dtype, torch.float32)
        self.assertEqual(diagnostics["transport_dtype"], "torch.float64")
        output.square().sum().backward()
        for p in model.parameters():
            self.assertEqual(p.dtype, torch.float32)
            self.assertTrue(bool(torch.isfinite(p.grad).all()))
        native = self.model(torch.float32, transport_precision="native")
        _, state, diagnostics = native.step(x)
        self.assertEqual(state.density.dtype, torch.float32)
        self.assertEqual(diagnostics["transport_dtype"], "torch.float32")


if __name__ == "__main__":
    unittest.main()
