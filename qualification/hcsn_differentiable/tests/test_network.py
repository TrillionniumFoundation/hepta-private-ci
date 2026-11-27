"""Small CPU mechanism fixtures, not the frozen S81 fidelity or task study.

Every finite-difference check records its actual AD/FD values in the runner's
JSON through ``measurements``. The coarse 6/3 basis here establishes graph and
state semantics only; it does not inherit a 64/16 physical-fidelity result.
"""

import io
import copy
import math
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import torch

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork, IrregularHCSNEncoder
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator


def mechanism_grid():
    return GridSpec(active_cells=6, phase_cells=3, quadrature_order=8)


def make_network():
    torch.manual_seed(1027)
    return ContinuousSpikingNetwork(3, content_dim=3, output_dim=1,
                                    layer_count=2, grid=mechanism_grid()).double()


def example():
    values = torch.tensor([
        [[.4, -.2, .7], [.1, .6, -.1], [-.3, .2, .5], [.8, -.1, .1], [.2, .9, -.4], [.6, .1, .2]],
        [[-.2, .5, .1], [.7, -.3, .4], [.2, .6, -.5], [.4, .3, .2], [-.1, .5, .8], [.9, -.2, .3]],
    ], dtype=torch.float64)
    dt = torch.tensor([[.04, .08, .035, .07, .06, .08],
                       [.03, .05, .075, .04, .065, .09]], dtype=torch.float64)
    return values, dt


def fresh_state(model, batch):
    # A short-distance initial prior exercises hits, refractory mass and release
    # within this bounded fixture; it is not the default network initial prior.
    return model.initial_state(batch, absolute_initial=math.exp(.18))


def task_loss(result):
    target = result.predictions.new_full((result.predictions.shape[0],), .3)
    return ((result.predictions[:, -1, 0] - target).square().mean()
            + .05 * result.predictions[:, -2, 0].square().mean())


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.measurements = {"scope": "coarse 6-active/3-phase mechanism fixture; no high-resolution fidelity credit"}
        self.model = make_network()
        self.features, self.dt = example()

    def assert_states_close(self, left, right, atol=2e-12, *, compare_position=True):
        self.assertEqual(len(left.layers), len(right.layers))
        if compare_position:
            self.assertEqual(left.sequence_position, right.sequence_position)
        self.assertEqual(left.truncate_every, right.truncate_every)
        self.assertEqual(left.configuration_snapshot, right.configuration_snapshot)
        torch.testing.assert_close(left.elapsed, right.elapsed, rtol=0, atol=atol)
        torch.testing.assert_close(left.steps, right.steps, rtol=0, atol=0)
        for lhs, rhs in zip(left.layers, right.layers):
            torch.testing.assert_close(lhs.probability, rhs.probability, rtol=0, atol=atol)
            torch.testing.assert_close(lhs.content_mass, rhs.content_mass, rtol=0, atol=atol)

    def objective(self):
        return task_loss(self.model(self.features, self.dt, state=fresh_state(self.model, 2)))

    def finite_difference(self, parameter, index=(), step=2e-5):
        original = parameter.detach().clone()
        try:
            with torch.no_grad():
                parameter[index] = original[index] + step
                plus = float(self.objective())
                parameter[index] = original[index] - step
                minus = float(self.objective())
            return (plus - minus) / (2 * step)
        finally:
            with torch.no_grad():
                parameter.copy_(original)

    def test_two_layers_all_four_physical_parameters_have_task_fd_gradients(self):
        self.objective().backward()
        rows = []
        self.measurements["physical_finite_differences"] = rows
        names = ("raw_mu", "raw_sigma", "raw_log_boundary", "raw_absolute_reset")
        for depth, layer in enumerate(self.model.layers):
            for name in names:
                parameter = getattr(layer.physics, name)
                ad = float(parameter.grad)
                fd = self.finite_difference(parameter)
                relative = abs(ad - fd) / max(abs(ad), abs(fd), 1e-12)
                rows.append(dict(layer=depth, parameter=name, raw_parameter_step=2e-5,
                                 autograd=ad, finite_difference=fd, absolute_error=abs(ad-fd),
                                 relative_error=relative))
                with self.subTest(layer=depth, parameter=name):
                    self.assertTrue(math.isfinite(ad) and math.isfinite(fd))
                    self.assertGreater(abs(ad), 1e-10)
                    self.assertGreater(abs(fd), 1e-10)
                    self.assertLess(relative, 3e-3)
                    self.assertLess(abs(ad - fd), 3e-7)

    def test_first_layer_content_parameter_reaches_final_task_loss(self):
        self.objective().backward()
        parameter = self.model.layers[0].content_proposal.weight
        ad = float(parameter.grad[0, 0])
        fd = self.finite_difference(parameter, (0, 0))
        relative = abs(ad - fd) / max(abs(ad), abs(fd), 1e-12)
        self.measurements["cross_layer_fd"] = dict(autograd=ad, finite_difference=fd,
                                                    relative_error=relative, raw_parameter_step=2e-5)
        self.assertGreater(abs(ad), 1e-8)
        self.assertLess(relative, 3e-3)

    def test_actual_dt_batched_mass_and_exactly_one_advance_per_layer_step(self):
        with ExitStack() as stack:
            calls = [stack.enter_context(patch.object(layer.operator, "advance", wraps=layer.operator.advance))
                     for layer in self.model.layers]
            result = self.model(self.features, self.dt, state=fresh_state(self.model, 2), return_trace=True)
        self.assertEqual([call.call_count for call in calls], [self.features.shape[1]] * 2)
        torch.testing.assert_close(result.state.elapsed, self.dt.sum(1), rtol=0, atol=1e-15)
        self.assertTrue(bool((result.expected_events >= -1e-12).all()))
        for row in result.trace:
            for layer in row:
                torch.testing.assert_close(layer["probability"].sum(-1), torch.ones(2, dtype=torch.float64),
                                           rtol=0, atol=self.model.mass_tolerance)
                self.assertGreaterEqual(float(layer["probability"].min()), -1e-12)
        separate = []
        for sample in range(2):
            one = self.model(self.features[sample:sample+1], self.dt[sample:sample+1],
                             state=fresh_state(self.model, 1))
            separate.append(one.predictions)
        torch.testing.assert_close(result.predictions, torch.cat(separate), rtol=1e-10, atol=1e-11)
        uniform = self.model(self.features, torch.full_like(self.dt, .06), state=fresh_state(self.model, 2))
        difference = float((result.predictions - uniform.predictions).abs().max())
        self.assertGreater(difference, 1e-7)
        self.measurements.update(result.diagnostics, irregular_vs_uniform_prediction_max_difference=difference,
                                 elapsed_seconds=result.state.elapsed.detach().tolist(),
                                 expected_events_by_layer=result.expected_events.detach().sum((0, 1)).tolist())

    def test_chunk_continuation_preserves_full_layer_content_and_clocks(self):
        whole = self.model(self.features, self.dt, state=fresh_state(self.model, 2))
        first = self.model(self.features[:, :3], self.dt[:, :3], state=fresh_state(self.model, 2))
        second = self.model(self.features[:, 3:], self.dt[:, 3:], state=first.state)
        torch.testing.assert_close(torch.cat((first.predictions, second.predictions), 1), whole.predictions,
                                   rtol=0, atol=2e-12)
        self.assert_states_close(second.state, whole.state)
        self.assertTrue(all(float(layer.content_mass.abs().sum()) > 0 for layer in second.state.layers))
        self.measurements["chunk_prediction_max_error"] = float((second.predictions-whole.predictions[:, 3:]).abs().max())

    def test_explicit_tbptt_cuts_early_inputs_without_changing_forward_values(self):
        full_input = self.features.clone().requires_grad_(True)
        full = self.model(full_input, self.dt, state=fresh_state(self.model, 2))
        full_grad, = torch.autograd.grad(full.predictions[:, -1].sum(), full_input)
        cut_input = self.features.clone().requires_grad_(True)
        truncated = self.model(cut_input, self.dt, state=fresh_state(self.model, 2), truncate_every=2)
        cut_grad, = torch.autograd.grad(truncated.predictions[:, -1].sum(), cut_input)
        torch.testing.assert_close(full.predictions, truncated.predictions, rtol=0, atol=0)
        self.assertGreater(float(full_grad[:, 0].abs().sum()), 1e-9)
        self.assertEqual(float(cut_grad[:, :4].abs().sum()), 0.)
        self.assertGreater(float(cut_grad[:, -1].abs().sum()), 1e-9)
        self.measurements["bptt"] = dict(full_first_input_l1=float(full_grad[:, 0].abs().sum()),
                                         truncated_early_input_l1=float(cut_grad[:, :4].abs().sum()),
                                         truncated_last_input_l1=float(cut_grad[:, -1].abs().sum()))

    def test_tbptt_phase_survives_one_position_chunks(self):
        inputs = self.features.clone().requires_grad_(True)
        state = fresh_state(self.model, 2)
        predictions = []
        for index in range(inputs.shape[1]):
            part = self.model(inputs[:, index:index+1], self.dt[:, index:index+1], state=state,
                              truncate_every=2 if index == 0 else None)
            state = part.state
            predictions.append(part.predictions)
        joined = torch.cat(predictions, 1)
        gradient, = torch.autograd.grad(joined[:, -1].sum(), inputs)
        full_chunk = self.model(self.features, self.dt, state=fresh_state(self.model, 2), truncate_every=2)
        torch.testing.assert_close(joined, full_chunk.predictions, rtol=0, atol=2e-12)
        self.assert_states_close(state, full_chunk.state)
        self.assertEqual(float(gradient[:, :4].abs().sum()), 0.)
        self.assertGreater(float(gradient[:, -1].abs().sum()), 1e-9)
        self.measurements["cross_call_bptt"] = dict(sequence_position=state.sequence_position,
                                                   early_gradient_l1=float(gradient[:, :4].abs().sum()),
                                                   last_gradient_l1=float(gradient[:, -1].abs().sum()))

    def test_missing_observation_advances_but_padding_preserves_state(self):
        first = self.model(self.features[:, :2], self.dt[:, :2], state=fresh_state(self.model, 2))
        missing = torch.zeros(2, 1, dtype=torch.bool)
        no_data = self.model(self.features[:, 2:3] * 100., self.dt[:, 2:3],
                             state=first.state, observed=missing)
        other = self.model(self.features[:, 2:3] * -100., self.dt[:, 2:3],
                           state=first.state, observed=missing)
        self.assert_states_close(no_data.state, other.state)
        self.assertTrue(bool((no_data.state.elapsed > first.state.elapsed).all()))
        padding = self.model(self.features[:, 2:3], torch.zeros_like(self.dt[:, 2:3]), state=first.state,
                             observed=missing, valid_mask=missing)
        self.assert_states_close(padding.state, first.state, compare_position=False)
        self.assertEqual(padding.state.sequence_position, first.state.sequence_position + 1)
        self.assertEqual(float(padding.predictions.abs().sum()), 0.)

    def test_operator_grid_ownership_cannot_differ_at_equal_state_count(self):
        grid = mechanism_grid()
        same_size_wrong_partition = GridSpec(active_cells=5, phase_cells=4, quadrature_order=8)
        self.assertEqual(grid.state_count, same_size_wrong_partition.state_count)
        with self.assertRaisesRegex(ValueError, "operator.grid must equal"):
            ContinuousSpikingNetwork(3, grid=grid, operators=[
                DifferentiableDistributionOperator(same_size_wrong_partition),
                DifferentiableDistributionOperator(grid)])

    def test_parameter_update_requires_explicit_new_episode(self):
        result = self.model(self.features[:, :2], self.dt[:, :2], state=fresh_state(self.model, 2))
        with torch.no_grad():
            self.model.layers[0].physics.raw_mu.add_(.01)
        with self.assertRaisesRegex(ValueError, "parameters changed"):
            self.model(self.features[:, 2:3], self.dt[:, 2:3], state=result.state)
        self.model(self.features[:, 2:3], self.dt[:, 2:3], state=fresh_state(self.model, 2))

    def test_semantic_hyperparameter_and_buffer_changes_reject_continuation(self):
        state = fresh_state(self.model, 2)
        self.model.layers[0].operator.hit_reward += .1
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            self.model(self.features, self.dt, state=state)
        self.model.layers[0].operator.hit_reward -= .1
        state = fresh_state(self.model, 2)
        with torch.no_grad():
            self.model.layers[0].physics.discount.add_(.01)
        with self.assertRaisesRegex(ValueError, "parameters changed"):
            self.model(self.features, self.dt, state=state)
        sensor = IrregularHCSNEncoder(3, grid=mechanism_grid())
        sensor_state = sensor.initial_state(2)
        sensor.encoder.time_scale *= 2
        with self.assertRaisesRegex(ValueError, "encoder configuration changed"):
            sensor(self.features, self.dt.cumsum(1), state=sensor_state)

    def test_checkpoint_consumed_next_step_and_adam_match_detached_reference(self):
        optimizer = torch.optim.Adam(self.model.parameters(), lr=2e-3)
        self.objective().backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        first = self.model(self.features[:, :3], self.dt[:, :3], state=fresh_state(self.model, 2))
        archive = io.BytesIO()
        torch.save(self.model.checkpoint(first.state, optimizer), archive)
        archive.seek(0)
        payload = torch.load(archive, weights_only=True)
        recovered = make_network()
        recovered_optimizer = torch.optim.Adam(recovered.parameters(), lr=2e-3)
        recovered_state = recovered.restore_checkpoint(payload, recovered_optimizer)
        self.assert_states_close(recovered_state, first.state)
        # Serialization does not persist an autograd tape. Both sides start a
        # new graph segment from the same full retained numerical state.
        expected = self.model(self.features[:, 3:], self.dt[:, 3:], state=first.state.detached())
        observed = recovered(self.features[:, 3:], self.dt[:, 3:], state=recovered_state)
        torch.testing.assert_close(observed.predictions, expected.predictions, rtol=0, atol=2e-12)
        self.assert_states_close(observed.state, expected.state)
        task_loss(expected).backward()
        task_loss(observed).backward()
        optimizer.step()
        recovered_optimizer.step()
        maximum = 0.
        for name, parameter in self.model.state_dict().items():
            difference = float((parameter - recovered.state_dict()[name]).abs().max())
            maximum = max(maximum, difference)
            torch.testing.assert_close(parameter, recovered.state_dict()[name], rtol=0, atol=3e-12)
        self.measurements["recovery"] = dict(archive_bytes=len(archive.getbuffer()),
                                              next_prediction_max_error=float((observed.predictions-expected.predictions).abs().max()),
                                              next_optimizer_parameter_max_error=maximum,
                                              autograd_tape_restored=False)

    def test_sensor_encoder_streaming_and_checkpoint_use_actual_clock(self):
        torch.manual_seed(343)
        model = IrregularHCSNEncoder(3, embedding_dim=3, content_dim=3, grid=mechanism_grid()).double()
        times = self.dt.cumsum(1) + 1000.
        observed = torch.ones_like(self.features, dtype=torch.bool)
        observed[0, 1] = False
        initial = model.initial_state(2, start_time=1000., absolute_initial=math.exp(.18))
        whole, whole_state = model(self.features, times, observed, state=initial)
        first, first_state = model(self.features[:, :3], times[:, :3], observed[:, :3], state=initial)
        payload = model.checkpoint(first_state)
        clone = IrregularHCSNEncoder(3, embedding_dim=3, content_dim=3, grid=mechanism_grid()).double()
        restored = clone.restore_checkpoint(payload)
        second, last_state = clone(self.features[:, 3:], times[:, 3:], observed[:, 3:], state=restored)
        torch.testing.assert_close(torch.cat((first.predictions, second.predictions), 1), whole.predictions,
                                   rtol=0, atol=3e-12)
        self.assert_states_close(last_state.network, whole_state.network)
        torch.testing.assert_close(last_state.last_timestamp, times[:, -1], rtol=0, atol=0)
        task_loss(whole).backward()
        encoder_grad = sum(float(parameter.grad.abs().sum()) for parameter in model.encoder.parameters())
        self.assertGreater(encoder_grad, 1e-8)
        self.measurements["sensor_encoder_gradient_l1"] = encoder_grad

    def test_failed_restoration_preserves_all_model_optimizer_and_rng_values(self):
        optimizer = torch.optim.Adam(self.model.parameters(), lr=.002)
        self.objective().backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        first = self.model(self.features[:, :2], self.dt[:, :2], state=fresh_state(self.model, 2))
        payload = self.model.checkpoint(first.state, optimizer)
        with torch.no_grad():
            self.model.readout.bias.add_(.23)
            for values in optimizer.state.values():
                values["exp_avg"].add_(.011)
        optimizer.param_groups[0]["lr"] = .0037
        before = copy.deepcopy(self.model.state_dict())
        before_optimizer = copy.deepcopy(optimizer.state_dict())
        before_rng = torch.random.get_rng_state().clone()
        corruptions = []
        bad_clock = copy.deepcopy(payload)
        bad_clock["elapsed"] = torch.zeros(3, dtype=torch.float64)
        corruptions.append(bad_clock)
        bad_position = copy.deepcopy(payload)
        bad_position["sequence_position"] = 0
        corruptions.append(bad_position)
        bad_zero_clock = copy.deepcopy(payload)
        bad_zero_clock["sequence_position"] = 0
        bad_zero_clock["steps"].zero_()
        corruptions.append(bad_zero_clock)
        bad_optimizer = copy.deepcopy(payload)
        bad_optimizer["optimizer"]["state"]["param_groups"] = []
        corruptions.append(bad_optimizer)
        bad_moment_shape = copy.deepcopy(payload)
        first_id = next(iter(bad_moment_shape["optimizer"]["state"]["state"]))
        first_moment = bad_moment_shape["optimizer"]["state"]["state"][first_id]["exp_avg"]
        bad_moment_shape["optimizer"]["state"]["state"][first_id]["exp_avg"] = first_moment.unsqueeze(0)
        corruptions.append(bad_moment_shape)
        bad_moment_nan = copy.deepcopy(payload)
        bad_moment_nan["optimizer"]["state"]["state"][first_id]["exp_avg_sq"].fill_(float("nan"))
        corruptions.append(bad_moment_nan)
        bad_rng = copy.deepcopy(payload)
        bad_rng["torch_rng"] = torch.zeros(3, dtype=torch.uint8)
        corruptions.append(bad_rng)
        for corrupted in corruptions:
            with self.assertRaises((ValueError, RuntimeError)):
                self.model.restore_checkpoint(corrupted, optimizer)
            for name, value in before.items():
                torch.testing.assert_close(self.model.state_dict()[name], value, rtol=0, atol=0)
            torch.testing.assert_close(optimizer.state_dict(), before_optimizer, rtol=0, atol=0)
            torch.testing.assert_close(torch.random.get_rng_state(), before_rng, rtol=0, atol=0)
        # Two physical parameters have the same scalar shape. Numeric optimizer
        # IDs/counts alone cannot detect their order being exchanged at restore.
        parameters = list(self.model.parameters())
        mu = self.model.layers[0].physics.raw_mu
        sigma = self.model.layers[0].physics.raw_sigma
        mu_index = next(index for index, parameter in enumerate(parameters) if parameter is mu)
        sigma_index = next(index for index, parameter in enumerate(parameters) if parameter is sigma)
        parameters[mu_index], parameters[sigma_index] = parameters[sigma_index], parameters[mu_index]
        swapped_optimizer = torch.optim.Adam(parameters, lr=.0037)
        swapped_before = copy.deepcopy(swapped_optimizer.state_dict())
        with self.assertRaisesRegex(ValueError, "parameter-name layout"):
            self.model.restore_checkpoint(payload, swapped_optimizer)
        for name, value in before.items():
            torch.testing.assert_close(self.model.state_dict()[name], value, rtol=0, atol=0)
        torch.testing.assert_close(swapped_optimizer.state_dict(), swapped_before, rtol=0, atol=0)
        torch.testing.assert_close(torch.random.get_rng_state(), before_rng, rtol=0, atol=0)
        # Rejected malformed moments must not poison the next real update.
        optimizer.zero_grad(set_to_none=True)
        self.objective().backward()
        optimizer.step()
        self.assertTrue(all(bool(torch.isfinite(parameter).all()) for parameter in self.model.parameters()))
        # A late sensor-clock error must also undo the already restored encoder
        # and nested network, not only the component that raised the exception.
        sensor = IrregularHCSNEncoder(3, grid=mechanism_grid())
        stream = sensor.initial_state(2)
        sensor_payload = sensor.checkpoint(stream)
        sensor_payload["last_timestamp"] = torch.zeros(3, dtype=torch.float64)
        with torch.no_grad():
            sensor.encoder.projection[0].bias.add_(.13)
        sensor_before = copy.deepcopy(sensor.state_dict())
        sensor_rng_before = torch.random.get_rng_state().clone()
        with self.assertRaises(ValueError):
            sensor.restore_checkpoint(sensor_payload)
        for name, value in sensor_before.items():
            torch.testing.assert_close(sensor.state_dict()[name], value, rtol=0, atol=0)
        torch.testing.assert_close(torch.random.get_rng_state(), sensor_rng_before, rtol=0, atol=0)
        self.measurements["rejected_restore_cases"] = len(corruptions) + 2
        self.measurements["optimizer_moment_shape_and_nonfinite_rejections"] = 2
        self.measurements["same_shape_physics_parameter_permutation_rejected"] = True
        self.measurements["next_adam_step_after_rejections_finite"] = True

    def test_no_reset_control_and_32_step_unobserved_transport(self):
        grid = mechanism_grid()
        killed = ContinuousSpikingNetwork(3, content_dim=3, layer_count=2, grid=grid,
                    operators=[DifferentiableDistributionOperator(grid, reset_enabled=False) for _ in range(2)])
        killed.load_state_dict(self.model.state_dict())
        with self.assertRaisesRegex(ValueError, "configuration mismatch"):
            killed.restore_checkpoint(self.model.checkpoint(fresh_state(self.model, 1)))
        zeros = torch.zeros(1, 32, 3, dtype=torch.float64)
        durations = torch.full((1, 32), .075, dtype=torch.float64)
        missing = torch.zeros(1, 32, dtype=torch.bool)
        with torch.no_grad():
            recurrent = self.model(zeros, durations, state=fresh_state(self.model, 1), observed=missing)
            absorbed = killed(zeros, durations, state=fresh_state(killed, 1), observed=missing)
            first = self.model(zeros[:, :16], durations[:, :16], state=fresh_state(self.model, 1), observed=missing[:, :16])
            continued = self.model(zeros[:, 16:], durations[:, 16:], state=first.state, observed=missing[:, 16:])
        self.assert_states_close(continued.state, recurrent.state)
        total_regenerative = recurrent.expected_events.sum((0, 1))
        total_killed = absorbed.expected_events.sum((0, 1))
        self.assertTrue(bool((total_regenerative > total_killed + .01).all()))
        self.assertTrue(bool((total_killed <= 1. + 1e-10).all()))
        self.assertGreater(float((recurrent.state.layers[-1].probability-absorbed.state.layers[-1].probability).abs().sum()), .01)
        self.measurements["long_no_observation"] = dict(steps=32, elapsed=float(recurrent.state.elapsed[0]),
            regenerative_expected_events=total_regenerative.tolist(), killed_expected_events=total_killed.tolist(),
            regenerative_mass_residual=recurrent.diagnostics["maximum_mass_residual"],
            killed_mass_residual=absorbed.diagnostics["maximum_mass_residual"],
            graph_retained=False, fidelity_claim=False)


if __name__ == "__main__":
    unittest.main()
