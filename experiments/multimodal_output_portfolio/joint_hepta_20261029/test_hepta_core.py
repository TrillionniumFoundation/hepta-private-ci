"""Mathematical and execution checks for the source-bound tensor core."""

import copy
import io
import math

import pytest
import torch

from .hepta_core import HeptaCore, first_passage_terms, reset_at_interval_end_mean


def tensor(value):
    return torch.tensor(value, dtype=torch.float64)


def assert_states_equal(left, right):
    assert len(left) == len(right)
    for first, second in zip(left, right, strict=True):
        assert set(first) == set(second)
        for name in first:
            torch.testing.assert_close(first[name], second[name], rtol=0, atol=0)


@pytest.mark.parametrize("drift", [-0.7, 0.0, 0.8])
def test_first_passage_against_independent_density_quadrature(drift):
    # Integrate the inverse-Gaussian density independently of the CDF code.
    times = torch.linspace(1e-8, 1.4, 16001, dtype=torch.float64)
    distance, sigma = 0.9, 0.6
    density = (
        distance / (sigma * math.sqrt(2 * math.pi) * times.pow(1.5))
        * torch.exp(-(distance - drift * times).square() / (2 * sigma**2 * times))
    )
    oracle = torch.trapezoid(density, times)
    terms = first_passage_terms(tensor(distance), tensor(drift), tensor(sigma), times[-1])
    torch.testing.assert_close(terms["cdf"], oracle, atol=2e-8, rtol=2e-8)
    torch.testing.assert_close(terms["cdf"] + terms["survival"], tensor(1.0))


def test_zero_drift_reflection_and_probability_not_terminal_observation():
    distance, sigma, time = tensor(0.8), tensor(0.7), tensor(1.2)
    actual = first_passage_terms(distance, tensor(0.0), sigma, time)["cdf"]
    expected = math.erfc(float(distance / (sigma * (2 * time).sqrt())))
    assert abs(float(actual) - expected) < 1e-12
    assert actual > torch.special.ndtr(-distance / (sigma * time.sqrt()))


def test_first_passage_interior_derivatives_against_finite_differences():
    arguments = tuple(tensor(x).requires_grad_() for x in (0.8, -0.25, 0.7, 1.3))
    assert torch.autograd.gradcheck(
        lambda *args: first_passage_terms(*args)["cdf"],
        arguments,
        eps=1e-6,
        atol=2e-5,
        rtol=1e-4,
    )


def test_killed_first_moment_against_independent_density_integral():
    state, barrier, mu, sigma, time = [tensor(x) for x in (0.2, 1.0, 0.3, 0.7, 0.6)]
    points = torch.linspace(-7, float(barrier), 24001, dtype=torch.float64)
    scale = sigma * time.sqrt()
    direct = torch.distributions.Normal(state + mu * time, scale)
    image = torch.distributions.Normal(2 * barrier - state + mu * time, scale)
    density = (
        direct.log_prob(points).exp()
        - torch.exp(2 * mu * (barrier - state) / sigma.square())
        * image.log_prob(points).exp()
    )
    oracle = torch.trapezoid(points * density, points)
    actual, _ = reset_at_interval_end_mean(state, barrier, mu, sigma, time)
    torch.testing.assert_close(actual, oracle, atol=2e-8, rtol=2e-8)


@pytest.mark.parametrize("dtype", [torch.float32, torch.float64])
def test_probability_tails_and_atoms_have_finite_backward(dtype):
    mu = torch.tensor([-100.0, -10.0, 0.0, 10.0, 100.0], dtype=dtype, requires_grad=True)
    actual = first_passage_terms(
        torch.tensor(0.5, dtype=dtype), mu,
        torch.tensor(0.02, dtype=dtype), torch.tensor(1.0, dtype=dtype),
    )["cdf"]
    actual.sum().backward()
    assert torch.isfinite(actual).all() and torch.isfinite(mu.grad).all()
    assert bool(((0 <= actual) & (actual <= 1)).all())
    atoms = first_passage_terms(
        tensor([1.0, 0.0, -0.1]), tensor(0.2), tensor(0.8), tensor(0.0)
    )
    torch.testing.assert_close(atoms["cdf"], tensor([0.0, 1.0, 1.0]))


@pytest.mark.parametrize("mode", ["dual", "ordinary", "single", "no_adaptation"])
def test_semantic_output_gradients_reach_each_active_mechanism(mode):
    torch.manual_seed(14)
    core = HeptaCore(5, depth=2, mode=mode, boundary_mode="direct").double()
    x = torch.randn(4, 12, 5, dtype=torch.float64, requires_grad=True)
    output, states, aux = core(x, 0.7)
    target = torch.randn_like(output[:, -1])
    (output[:, -1] - target).square().mean().backward()
    for name, parameter in core.named_parameters():
        assert parameter.grad is not None, name
        assert torch.isfinite(parameter.grad).all(), name
        assert parameter.grad.abs().sum() > 1e-12, name
    assert torch.isfinite(x.grad).all() and x.grad.abs().sum() > 0
    assert len(states) == 2 and aux["all_event_probability"].shape == (4, 12, 2, 5)
    assert aux["content"].shape == (4, 12, 5)
    assert aux["content"].abs().max() <= 1.000001
    assert bool((aux["diffusion"] > 0).all())
    if mode == "single":
        assert aux["regeneration"].count_nonzero() == 0
    if mode == "no_adaptation":
        assert aux["adaptation"].count_nonzero() == 0


def test_chunked_execution_and_model_state_restore_are_exact():
    torch.manual_seed(17)
    core = HeptaCore(4, depth=2).double()
    x = torch.randn(3, 11, 4, dtype=torch.float64)
    dt = torch.rand(3, 11, dtype=torch.float64) + 0.1
    whole, final, _ = core(x, dt)
    prefix, partial, _ = core(x[:, :4], dt[:, :4])
    retained = [{name: value.detach().clone() for name, value in layer.items()} for layer in partial]
    buffer = io.BytesIO()
    torch.save({"weights": core.state_dict(), "runtime": retained}, buffer)
    buffer.seek(0)
    restored = torch.load(buffer, weights_only=True)
    fresh = HeptaCore(4, depth=2).double()
    fresh.load_state_dict(restored["weights"])
    suffix, restored_final, _ = fresh(x[:, 4:], dt[:, 4:], state=restored["runtime"])
    torch.testing.assert_close(torch.cat((prefix, suffix), dim=1), whole, rtol=0, atol=0)
    assert_states_equal(final, restored_final)


def test_zero_duration_preserves_all_state_even_for_reached_boundary():
    torch.manual_seed(2)
    core = HeptaCore(3, depth=2).double()
    state = core.initial_state(2, content=torch.randn(2, 3, dtype=torch.float64))
    state[0]["voltage"].fill_(5.0)
    state[0]["event"].fill_(0.4)
    before = copy.deepcopy(state)
    _, after, aux = core.step(torch.randn(2, 3, dtype=torch.float64), state, 0.0)
    assert_states_equal(state, before)
    assert_states_equal(after, before)
    assert aux["all_event_probability"].count_nonzero() == 0


def test_encoder_initial_content_is_retained_and_differentiable():
    torch.manual_seed(6)
    core = HeptaCore(4).double()
    encoded = torch.randn(2, 4, dtype=torch.float64, requires_grad=True)
    state = core.initial_state(2, content=encoded)
    x = torch.zeros(2, 5, 4, dtype=torch.float64)
    output, _, _ = core(x, 0.3, state=state)
    output[:, -1].square().sum().backward()
    assert encoded.grad is not None and torch.isfinite(encoded.grad).all()
    assert encoded.grad.abs().sum() > 1e-10
    unconditioned, _, _ = core(x, 0.3)
    assert not torch.equal(unconditioned, output)


def test_probability_reset_changes_the_executed_voltage():
    core = HeptaCore(3).double()
    with torch.no_grad():
        core.layers[0].drift_input.weight.zero_()
        core.layers[0].drift_bias.fill_(5.0)
    _, state, aux = core.step(tensor([[0.0, 0.0, 0.0]]), core.initial_state(1), 1.0)
    assert aux["event_probability"].min() > 0.99
    assert state[0]["voltage"].abs().max() < 0.01
    assert aux["pre_reset_mean"].min() > 4.0


@pytest.mark.parametrize("bad_time", [-0.1, float("nan"), float("inf")])
def test_invalid_time_rejected_before_state_mutation(bad_time):
    core = HeptaCore(3)
    state = core.initial_state(2)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="dt"):
        core.step(torch.zeros(2, 3), state, bad_time)
    assert_states_equal(state, before)


def test_invalid_inputs_and_unimplemented_value_boundary_are_rejected():
    core = HeptaCore(3)
    with pytest.raises(ValueError, match="finite"):
        core.step(torch.full((2, 3), float("nan")), core.initial_state(2))
    with pytest.raises(ValueError, match="state fields"):
        core.step(torch.zeros(2, 3), [{"content": torch.zeros(2, 3)}])
    with pytest.raises(ValueError, match="natural boundary"):
        HeptaCore(3, boundary_mode="value")
    with pytest.raises(ValueError, match="positive"):
        first_passage_terms(tensor(1.0), tensor(0.0), tensor(0.0), tensor(1.0))
