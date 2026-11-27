"""Discrete-map gradients, fixed-mesh precision, and fixed-precision refinement."""

import copy
import unittest

import torch

from experiments.call_put_stable_flow.flow import BoundaryFlow


def small_flow(mode="analytic", max_step=0.25, dtype=torch.float64):
    model = BoundaryFlow(mode, 2, 1, max_step=max_step).to(dtype=dtype)
    with torch.no_grad():
        model.drive_v.weight.copy_(torch.tensor([[0.15, -0.2]], dtype=dtype))
        model.drive_q.weight.copy_(torch.tensor([[0.1, 0.05]], dtype=dtype))
    return model


def objective(model):
    state = model.initial_state(2)
    dtype = next(model.parameters()).dtype
    drive = torch.tensor([[0.4, -0.2], [-0.7, 0.3]], dtype=torch.float32).to(dtype=dtype)
    for dt in [0.2, 0.5, 0.75]:
        represented_dt = torch.tensor(dt, dtype=torch.float32).to(dtype=dtype)
        state, a, p = model.step(drive, represented_dt, state)
    return (0.7 * state[0] + 0.3 * state[1] + 0.2 * state[2] + 0.4 * a - 0.6 * p).sum()


def value_and_grad(model):
    value = objective(model)
    gradients = torch.autograd.grad(value, tuple(model.parameters()))
    return value.detach(), torch.cat([g.flatten() for g in gradients]).detach()


class FlowTests(unittest.TestCase):
    def test_parameter_layout_equilibrium_and_zero_dt(self):
        layouts = []
        for mode in ["analytic", "matched_c1", "sigmoid"]:
            model = small_flow(mode)
            layouts.append([(name, tuple(p.shape)) for name, p in model.named_parameters()])
            state = model.initial_state(3)
            zeros = torch.zeros(3, 2, dtype=torch.float64)
            rhs = model.rhs(zeros, state)
            torch.testing.assert_close(torch.stack(rhs), torch.zeros(3, 3, 1, dtype=torch.float64),
                                       rtol=0, atol=2e-15)
            unchanged, _, _ = model.step(zeros, torch.zeros(3), state)
            torch.testing.assert_close(torch.stack(unchanged), torch.stack(state), rtol=0, atol=0)
            p = model.effective_parameters()
            self.assertTrue((p["tau_z"] >= p["tau_q"] + 0.25).all())
            self.assertTrue(state[1].requires_grad and state[2].requires_grad)
        self.assertEqual(layouts[0], layouts[1])
        self.assertEqual(layouts[0], layouts[2])

    def test_all_parameter_gradients_match_same_discrete_map_fd(self):
        model = small_flow(max_step=0.125)
        _, gradients = value_and_grad(model)
        self.assertTrue(torch.isfinite(gradients).all())
        self.assertTrue((gradients.abs() > 1e-8).all())
        observed = []
        epsilon = 1e-5
        for parameter in model.parameters():
            for j in range(parameter.numel()):
                with torch.no_grad():
                    saved = parameter.flatten()[j].item()
                    parameter.flatten()[j] = saved + epsilon
                    upper = objective(model).item()
                    parameter.flatten()[j] = saved - epsilon
                    lower = objective(model).item()
                    parameter.flatten()[j] = saved
                observed.append((upper - lower) / (2 * epsilon))
        fd = torch.tensor(observed, dtype=torch.float64)
        torch.testing.assert_close(gradients, fd, rtol=3e-5, atol=3e-9)

    def test_fixed_h_fp32_fp64_and_separate_fp64_refinement(self):
        # Exactly represented FP32 weights are promoted, not reinitialized.
        single = small_flow(dtype=torch.float32)
        double = copy.deepcopy(single).double()
        value32, gradient32 = value_and_grad(single)
        value64, gradient64 = value_and_grad(double)
        self.assertLess(abs(value32.item() - value64.item()), 2e-6)
        self.assertLess(torch.linalg.vector_norm(gradient32.double() - gradient64).item()
                        / torch.linalg.vector_norm(gradient64).item(), 2e-5)

        reference = copy.deepcopy(double)
        reference.max_step = 1 / 128
        reference_value, reference_gradient = value_and_grad(reference)
        errors = []
        for h in [0.25, 0.125, 0.0625]:
            candidate = copy.deepcopy(double)
            candidate.max_step = h
            value, gradient = value_and_grad(candidate)
            errors.append((abs(value.item() - reference_value.item()),
                           torch.linalg.vector_norm(gradient - reference_gradient).item()))
        for previous, later in zip(errors, errors[1:]):
            self.assertLess(later[0], 0.45 * previous[0])
            self.assertLess(later[1], 0.45 * previous[1])

    def test_dt_shapes_and_input_state_autograd(self):
        model = small_flow()
        drive = torch.tensor([[0.4, -0.2], [0.2, 0.3]], dtype=torch.float64, requires_grad=True)
        dt = torch.tensor([0.31, 0.47], dtype=torch.float64, requires_grad=True)
        state = tuple(t.detach().clone().requires_grad_() for t in model.initial_state(2))
        result, a, p = model.step(drive, dt, state)
        gradients = torch.autograd.grad(sum(t.sum() for t in result) + a.sum() + p.sum(),
                                        (drive, dt, *state))
        self.assertTrue(all(torch.isfinite(g).all() for g in gradients))
        column, _, _ = model.step(drive, dt[:, None], state)
        torch.testing.assert_close(torch.stack(result), torch.stack(column), rtol=0, atol=0)

    def test_mesh_is_independent_of_other_batch_members(self):
        model = small_flow()
        drive = torch.tensor([[0.4, -0.2], [0.2, 0.3]], dtype=torch.float64)
        dt = torch.tensor([0.13, 1.2], dtype=torch.float64)
        together, _, _ = model.step(drive, dt, model.initial_state(2))
        separately = [model.step(drive[j:j+1], dt[j], model.initial_state(1))[0]
                      for j in range(2)]
        expected = torch.cat([torch.stack(state) for state in separately], dim=1)
        torch.testing.assert_close(torch.stack(together), expected, rtol=0, atol=1e-15)

    def test_prepared_sequence_preserves_values_and_all_gradients(self):
        for dtype in [torch.float32, torch.float64]:
            for mode in ["analytic", "matched_c1", "sigmoid"]:
                original = small_flow(mode, max_step=0.0625, dtype=dtype)
                records = []
                for cached in [False, True]:
                    model = copy.deepcopy(original)
                    inputs = torch.tensor([[[0.4, -0.2], [3., -2.], [-3., 2.]],
                                           [[0.2, 0.3], [-3., 2.], [3., -2.]]],
                                          dtype=dtype, requires_grad=True)
                    times = torch.tensor([[0., 0.31, 0.47], [0.13, 0.2, 0.41]],
                                         dtype=dtype, requires_grad=True)
                    prepared = model.prepare_sequence(times) if cached else None
                    state = model.initial_state(2, prepared=prepared)
                    outputs = []
                    for index in range(3):
                        if cached:
                            state, a, p = model.step_prepared(inputs[:, index], state, prepared, index)
                        else:
                            state, a, p = model.step(inputs[:, index], times[:, index], state)
                        outputs.append(torch.stack((*state, a, p)))
                    values = torch.stack(outputs)
                    gradients = torch.autograd.grad(values.square().sum(),
                                                    (*model.parameters(), inputs, times))
                    records.append((values.detach(), torch.cat([g.flatten() for g in gradients])))
                torch.testing.assert_close(records[0][0], records[1][0], rtol=0, atol=0)
                tolerance = 2e-6 if dtype == torch.float32 else 1e-12
                relative = torch.linalg.vector_norm(records[0][1] - records[1][1]) / torch.linalg.vector_norm(records[0][1])
                self.assertLess(relative.item(), tolerance)


if __name__ == "__main__":
    unittest.main()
