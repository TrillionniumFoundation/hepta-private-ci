"""Independent delayed ODE, causal gradients, and complete-state continuation."""

from fractions import Fraction
from dataclasses import replace
import io
import unittest

import numpy as np
from scipy.integrate import solve_ivp
import torch

from qualification.hcsn_currentstate.differentiable import Physics, Work, intervene
from .checkpoint import state_from_record, state_to_record
from .network import FlowNetwork


torch.set_num_threads(1)


def scalar_physics(rate):
    z = rate.new_zeros(())
    return Physics(-rate.reshape(1, 1), rate.reshape(1), z.reshape(1), rate.new_ones(1),
                   z.reshape(1), z, z, rate.new_tensor(.15), Fraction(1, 5))


def delayed_ode(sequence, weights, rates, dt=.1, delay=.2):
    """Independent method of steps; no candidate advance/exponential is called."""
    layers, channels = len(weights), weights[0].shape[0] + 1
    y = np.zeros((layers, channels, 2)); y[:, 0, 0] = 1
    messages = np.zeros((layers, channels))
    history, emissions = [], []
    for step, vector in enumerate(sequence):
        left, right = step * dt, (step + 1) * dt
        for layer in range(layers):
            source = vector if layer == 0 else messages[layer - 1]
            y[layer, 1:, 0] += (weights[layer] @ source) * y[layer, 0, 0]
        previous_hits = y[:, :, 1].copy()

        def rhs(t, flat):
            active = flat.reshape(layers, channels, 2)[:, :, 0]
            incoming = np.zeros_like(active)
            past = t - delay
            for start, end, dense in reversed(history):
                if start - 1e-14 <= past <= end + 1e-14:
                    incoming = rates[:, None] * dense(past).reshape(layers, channels, 2)[:, :, 0]
                    break
            flux = rates[:, None] * active
            return np.stack((-flux + incoming, flux), axis=2).ravel()

        solution = solve_ivp(rhs, (left, right), y.ravel(), method="DOP853",
                             rtol=3e-12, atol=3e-14, dense_output=True, max_step=dt / 8)
        if not solution.success:
            raise RuntimeError(solution.message)
        y = solution.y[:, -1].reshape(layers, channels, 2)
        messages = y[:, :, 1] - previous_hits
        emissions.append(messages[-1].copy())
        history.append((left, right, solution.sol))
    return np.stack(emissions), y


class CoupledFlowTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(37)
        self.model = FlowNetwork(1, 2, layers=2, activation="linear").double()
        self.sequence = torch.tensor([[.3], [-.8], [.2], [.9], [-.4], [.1]], dtype=torch.float64)
        self.physics = tuple(scalar_physics(torch.tensor(r, dtype=torch.float64)) for r in (1.7, 2.1))

    def test_actual_network_matches_independent_delayed_ode(self):
        emitted, state = self.model(self.sequence, self.physics)
        weights = [w.weight.detach().numpy() for w in self.model.writers]
        reference, final = delayed_ode(self.sequence.numpy(), weights, np.array([1.7, 2.1]))
        np.testing.assert_allclose(emitted.detach().numpy(), reference, atol=2e-11, rtol=2e-10)
        for layer, cell in enumerate(state.cells):
            np.testing.assert_allclose(cell.active[:, 0].detach().numpy(), final[layer, :, 0], atol=2e-11, rtol=2e-10)
            np.testing.assert_allclose(cell.hits.detach().numpy(), final[layer, :, 1], atol=2e-11, rtol=2e-10)
        for balance in state.balances():
            torch.testing.assert_close(balance, torch.zeros_like(balance), atol=5e-13, rtol=0)
        self.assertGreater(len(state.cells[0].pending), 0)

    def test_future_inputs_cannot_reach_earlier_emissions(self):
        changed = self.sequence.clone(); changed[3:] += 100
        emitted, _ = self.model(self.sequence, self.physics)
        other, _ = self.model(changed, self.physics)
        torch.testing.assert_close(emitted[:4], other[:4], atol=0, rtol=0)
        self.assertGreater(float((emitted[4:] - other[4:]).norm().detach()), 1e-4)
        torch.testing.assert_close(emitted[0, 1:], torch.zeros_like(emitted[0, 1:]), atol=0, rtol=0)

    def test_weight_input_initial_content_and_physics_gradients(self):
        self.model.activation = "tanh"
        weights = tuple(w.weight.detach().requires_grad_() for w in self.model.writers)
        inputs = self.sequence[:4].clone().requires_grad_()
        content = torch.tensor([[.1], [-.2]], dtype=torch.float64, requires_grad=True)
        rate = torch.tensor(1.7, dtype=torch.float64, requires_grad=True)

        def evaluate(w0, w1, x, c, r):
            physics = (scalar_physics(r), self.physics[1])
            state = self.model.initial_state(physics, contents=(c, torch.zeros_like(c)))
            out, final = torch.func.functional_call(self.model,
                {"writers.0.weight": w0, "writers.1.weight": w1}, (x, physics, state))
            return torch.cat((out.ravel(), final.cells[0].active.ravel(), final.cells[1].active.ravel()))

        self.assertTrue(torch.autograd.gradcheck(evaluate, (*weights, inputs, content, rate),
                                                eps=1e-6, atol=2e-8, rtol=2e-5))
        gradients = torch.autograd.grad(evaluate(*weights, inputs, content, rate).sum(),
                                        (*weights, inputs, content, rate))
        self.assertTrue(all(float(g.norm()) > 1e-6 for g in gradients))

    def test_full_pending_and_message_buffer_cold_forward_continuation(self):
        first, saved = self.model(self.sequence[:3], self.physics)
        record = state_to_record(saved)
        buffer = io.BytesIO(); torch.save(record, buffer); buffer.seek(0)
        restored = state_from_record(torch.load(buffer, weights_only=True))
        warm, warm_state = self.model(self.sequence[3:], self.physics, saved)
        cold, cold_state = self.model(self.sequence[3:], self.physics, restored)
        whole, whole_state = self.model(self.sequence, self.physics)
        torch.testing.assert_close(cold, warm, atol=0, rtol=0)
        torch.testing.assert_close(torch.cat((first, cold)), whole, atol=0, rtol=0)
        for left, right in zip(cold_state.tensors(), whole_state.tensors()):
            torch.testing.assert_close(left, right, atol=0, rtol=0)
        self.assertTrue(all(not t.requires_grad for t in restored.tensors()))
        self.assertEqual(cold_state.tensor_bytes(), warm_state.tensor_bytes())

    def test_mass_ablation_and_explicit_resource_stop(self):
        mass = FlowNetwork(1, 2, layers=2, message_mode="mass", activation="linear").double()
        mass.load_state_dict(self.model.state_dict())
        a, _ = mass(self.sequence, self.physics)
        b, _ = mass(self.sequence * 10, self.physics)
        torch.testing.assert_close(a, b, atol=0, rtol=0)
        with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            self.model(self.sequence, self.physics, work=Work(max_dimension=5))

    def test_shared_law_batch_equals_independent_forward_and_vjp(self):
        self.model.activation = "tanh"
        sequence = torch.stack((self.sequence[:4], self.sequence[:4] * -.7), 1).requires_grad_()
        rate = torch.tensor(1.7, dtype=torch.float64, requires_grad=True)
        physics = (scalar_physics(rate), self.physics[1])
        output, state = self.model(sequence, physics)
        separate = torch.stack([self.model(sequence[:, i], physics)[0] for i in range(2)], 1)
        torch.testing.assert_close(output, separate, atol=2e-15, rtol=2e-14)
        weights = torch.linspace(-.4, .9, output.numel(), dtype=torch.float64).reshape(output.shape)
        inputs = (sequence, rate, *self.model.parameters())
        batched_grad = torch.autograd.grad((output * weights).sum(), inputs, retain_graph=True)
        single_grad = torch.autograd.grad((separate * weights).sum(), inputs)
        for batched, single in zip(batched_grad, single_grad):
            torch.testing.assert_close(batched, single, atol=3e-15, rtol=2e-13)
        for balance in state.balances():
            torch.testing.assert_close(balance, torch.zeros_like(balance), atol=3e-13, rtol=0)
        restored = state_from_record(state_to_record(state))
        self.assertEqual(restored.batch_size, 2)
        self.assertEqual(restored.messages[0].shape, (2, 3))

    def test_due_release_atom_receives_the_current_sample_write(self):
        model = FlowNetwork(1, 1, layers=1, activation="linear").double()
        with torch.no_grad():
            model.writers[0].weight.fill_(1)
        p = self.physics[0]
        state = model.initial_state((p,))
        swept = intervene(state.cells[0], p, p.lower.new_ones(1))
        # The all-refractory interval has zero active reward/occupation/flow.
        due = replace(swept, time=p.delay, discount_factor=torch.exp(-p.discount * float(p.delay)))
        state = replace(state, cells=(due,))
        emitted, final = model.step(p.lower.new_tensor([.5]), state, (p,))
        hit = -torch.expm1(-p.lower[0] * float(model.dt))
        torch.testing.assert_close(emitted, torch.stack((hit, .5 * hit)), atol=1e-15, rtol=1e-14)
        torch.testing.assert_close(final.written[0], p.lower.new_tensor([[.5]]), atol=0, rtol=0)
        torch.testing.assert_close(final.balances()[0], p.lower.new_zeros(2), atol=3e-15, rtol=0)


if __name__ == "__main__":
    unittest.main()
