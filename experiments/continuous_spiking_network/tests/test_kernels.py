import math

import pytest
import torch

from experiments.continuous_spiking_network.kernels import (
    first_passage_cdf,
    first_passage_density,
    first_passage_terms,
    reset_at_interval_end_mean,
)


def tensor(value):
    return torch.tensor(value, dtype=torch.float64)


@pytest.mark.parametrize("drift", [-0.7, 0.0, 0.8])
def test_density_integral_is_independent_cdf_oracle(drift):
    time = torch.linspace(0, 1.4, 16001, dtype=torch.float64)
    density = first_passage_density(tensor(0.9), tensor(drift), tensor(0.6), time)
    integrated = torch.trapezoid(density, time)
    cdf = first_passage_cdf(tensor(0.9), tensor(drift), tensor(0.6), time[-1])
    torch.testing.assert_close(cdf, integrated, atol=2e-8, rtol=2e-8)


def test_reflection_survival_and_terminal_probability():
    d, mu, sigma, time = tensor(0.8), tensor(0.0), tensor(0.7), tensor(1.2)
    terms = first_passage_terms(d, mu, sigma, time)
    reflection = math.erfc(float(d / (sigma * (2 * time).sqrt())))
    assert abs(float(terms["cdf"]) - reflection) < 1e-12
    torch.testing.assert_close(terms["cdf"] + terms["survival"], tensor(1.0))
    assert terms["cdf"] > torch.special.ndtr((mu * time - d) / (sigma * time.sqrt()))


def test_parameter_gradients_are_true_derivatives():
    arguments = tuple(tensor(x).requires_grad_() for x in [0.8, -0.25, 0.7, 1.3])
    assert torch.autograd.gradcheck(first_passage_cdf, arguments, eps=1e-6, atol=2e-5)


def test_limits_monotonicity_and_extremes_are_finite():
    d = tensor([1.0, 1.0, 1.0, 0.0])
    terms = first_passage_terms(
        d, tensor(0.2), tensor(0.8), tensor([0.0, 0.5, 2.0, 0.0])
    )
    assert terms["cdf"][0] == 0 and terms["cdf"][-1] == 1
    assert terms["cdf"][1] < terms["cdf"][2]
    mu = tensor([-100.0, -10.0, 0.0, 10.0, 100.0]).requires_grad_()
    output = first_passage_cdf(tensor(0.5), mu, tensor(0.02), tensor(1.0))
    output.sum().backward()
    assert torch.isfinite(output).all() and torch.isfinite(mu.grad).all()
    assert bool(((output >= 0) & (output <= 1)).all())


def test_killed_density_moment_matches_reset_contract():
    state, boundary, mu, sigma, time = [tensor(x) for x in [0.2, 1.0, 0.3, 0.7, 0.6]]
    points = torch.linspace(-7, float(boundary), 24001, dtype=torch.float64)
    scale = sigma * time.sqrt()
    normal = torch.distributions.Normal(state + mu * time, scale)
    reflected = torch.distributions.Normal(2 * boundary - state + mu * time, scale)
    density = (
        normal.log_prob(points).exp()
        - torch.exp(2 * mu * (boundary - state) / sigma.square())
        * reflected.log_prob(points).exp()
    )
    oracle = torch.trapezoid(points * density, points)
    mean, _ = reset_at_interval_end_mean(state, boundary, mu, sigma, time)
    torch.testing.assert_close(mean, oracle, atol=2e-8, rtol=2e-8)


def test_against_frozen_pr4154_probability_and_gradient_oracle():
    from experiments.continuous_spiking_network.reference.hitting import (
        hit_probability_and_gradient,
        hit_sensitivities,
    )

    distance = tensor([0.01, 0.8, 4.0]).requires_grad_()
    drift, sigma, time = tensor([-0.7, 0.0, 0.8]), tensor(0.6), tensor(1.4)
    probability = first_passage_cdf(distance, drift, sigma, time)
    gradient = torch.autograd.grad(probability.sum(), distance)[0]
    expected, initial_gradient = hit_probability_and_gradient(
        distance.detach().numpy(), time.numpy(), drift.numpy(), sigma.numpy()
    )
    torch.testing.assert_close(
        probability, torch.as_tensor(expected), atol=1e-11, rtol=1e-10
    )
    torch.testing.assert_close(
        -gradient, torch.as_tensor(initial_gradient), atol=1e-10, rtol=1e-9
    )
    args = tuple(tensor(x).requires_grad_() for x in [0.8, 0.3, 0.7, 1.2])
    gradients = torch.autograd.grad(first_passage_cdf(*args), args)
    oracle = hit_sensitivities(0.8, 1.2, 0.3, 0.7)
    for actual, key in zip(gradients[1:], ("mu", "sigma", "horizon"), strict=True):
        assert abs(float(actual) - oracle[key]) < 1e-9
