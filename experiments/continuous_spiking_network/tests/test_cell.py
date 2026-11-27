import copy
import math

import pytest
import torch

from experiments.continuous_spiking_network.boundary import (
    FiniteHorizonStoppingBoundary,
    StoppingPolicy,
)
from experiments.continuous_spiking_network.cell import ContinuousSpikingBlock


@pytest.mark.parametrize("mode", ["dual", "single", "no_adaptation", "ordinary"])
def test_sequence_contract_and_adaptation(mode):
    torch.manual_seed(4)
    model = ContinuousSpikingBlock(6, depth=2, mode=mode)
    x, dt = torch.randn(3, 9, 6), torch.full((3, 9), 0.6)
    output, aux = model(x, dt)
    assert output.shape == x.shape and torch.isfinite(output).all()
    assert aux["event_probability"].shape == x.shape
    assert torch.isfinite(aux["voltage"]).all()
    assert bool((aux["diffusion"] > 0).all())
    if mode == "no_adaptation":
        assert aux["adaptation"].count_nonzero() == 0
    else:
        assert aux["adaptation"].sum() > 0
    if mode == "single":
        assert aux["regeneration"].count_nonzero() == 0


def test_joint_task_gradients_reach_all_mechanisms():
    torch.manual_seed(14)
    model = ContinuousSpikingBlock(5, boundary_mode="direct").double()
    x = torch.randn(4, 12, 5, dtype=torch.float64)
    target = torch.randn_like(x)
    output, _ = model(x, torch.full((4, 12), 0.7, dtype=torch.float64))
    (output - target).square().mean().backward()
    for name in (
        "drift_input.weight",
        "drift_bias",
        "raw_diffusion",
        "raw_recovery",
        "raw_regeneration",
        "raw_adaptation",
        "raw_adaptation_decay",
        "content_input.weight",
        "content_state.weight",
        "raw_boundary",
    ):
        gradient = dict(model.layers[0].named_parameters())[name].grad
        assert gradient is not None and torch.isfinite(gradient).all(), name
        assert gradient.abs().sum() > 1e-12, name


def test_event_mass_resets_and_zero_time_preserves_state():
    model = ContinuousSpikingBlock(3)
    with torch.no_grad():
        model.layers[0].drift_input.weight.zero_()
        model.layers[0].drift_bias.fill_(5)
    x = torch.randn(2, 3, 3)
    _, aux = model(x, torch.tensor([[1.0, 0.0, 1.0]]).expand(2, -1))
    assert aux["event_probability"][:, 0].min() > 0.99
    assert aux["voltage"][:, 0].abs().max() < 0.01
    torch.testing.assert_close(aux["content"][:, 0], aux["content"][:, 1])
    torch.testing.assert_close(aux["voltage"][:, 0], aux["voltage"][:, 1])
    assert aux["event_probability"][:, 1].count_nonzero() == 0


def test_value_boundary_is_causal_and_horizon_cost_sensitive():
    solver = FiniteHorizonStoppingBoundary(grid_size=257, quadrature_points=25).double()
    odds = torch.tensor([0.0, 0.0, 0.0], dtype=torch.float64)
    remaining = torch.tensor([0, 4, 4])
    result = solver(
        odds,
        remaining,
        torch.tensor([0.5], dtype=torch.float64),
        torch.tensor([0.01, 0.01, 0.6], dtype=torch.float64),
    )
    assert result["stop"].tolist() == [True, False, True]
    assert result["value"][1] > result["value"][0]
    assert result["wait_value"][2] < result["stop_value"][2]


def test_bellman_cache_equivalence_and_differentiable_cost():
    solver = FiniteHorizonStoppingBoundary().double()
    snr = torch.tensor([0.4], dtype=torch.float64, requires_grad=True)
    cost = torch.tensor([0.02], dtype=torch.float64, requires_grad=True)
    table = solver.table(snr, cost, 5)
    odds = torch.tensor([0.0, 0.3, 1.0], dtype=torch.float64)
    remaining = torch.tensor([4, 3, 2])
    result = solver.evaluate(odds, remaining, table)
    direct = solver(odds, remaining, snr, cost)
    torch.testing.assert_close(result["value"], direct["value"])
    result["value"].sum().backward()
    assert cost.grad.item() < 0 and torch.isfinite(snr.grad).all()


def test_direct_policy_receives_same_context_and_can_train():
    policy = StoppingPolicy("direct")
    result = policy(
        torch.tensor([0.1, 1.0]),
        torch.tensor([3, 0]),
        torch.tensor(0.4),
        torch.tensor(0.02),
    )
    assert result["stop"][-1] and result["stop_probability"][-1] == 1
    result["stop_probability"].sum().backward()
    assert policy.direct_context.grad.abs().sum() > 0


def test_value_stopping_is_not_claimed_as_natural_cell_boundary():
    with pytest.raises(ValueError, match="natural barrier"):
        ContinuousSpikingBlock(4, boundary_mode="value")


def test_ablations_have_no_unused_trainable_parameters():
    for mode in ("dual", "single", "no_adaptation", "ordinary"):
        model = ContinuousSpikingBlock(4, mode=mode)
        result, _ = model(torch.randn(2, 8, 4), torch.full((2, 8), 0.7))
        result.square().mean().backward()
        assert all(p.grad is not None for p in model.parameters() if p.requires_grad)
        names = dict(model.layers[0].named_parameters())
        if mode == "single":
            assert "raw_regeneration" not in names
            assert model.layers[0].channel_gates.out_features == 4
        if mode == "no_adaptation":
            assert "raw_adaptation" not in names
            assert "raw_adaptation_decay" not in names


def test_recovery_reduces_a_small_subthreshold_perturbation():
    weak = ContinuousSpikingBlock(2, mode="no_adaptation")
    with torch.no_grad():
        layer = weak.layers[0]
        layer.drift_input.weight.copy_(torch.eye(2))
        layer.drift_bias.zero_()
        layer.channel_gates.weight.zero_()
        layer.channel_gates.bias.zero_()
        layer.fixed_boundary.fill_(10)
        layer.raw_diffusion.fill_(math.log(math.expm1(0.05)))
        layer.raw_recovery.fill_(math.log(math.expm1(0.02)))
    strong = copy.deepcopy(weak)
    with torch.no_grad():
        strong.layers[0].raw_recovery.fill_(math.log(math.expm1(1.5)))
    x = torch.zeros(1, 40, 2)
    x[0, 0] = torch.tensor([1.0, -1.0])
    dt = torch.full((1, 40), 0.1)
    _, weak_aux = weak(x, dt)
    _, strong_aux = strong(x, dt)
    torch.testing.assert_close(weak_aux["voltage"][:, 0], strong_aux["voltage"][:, 0])
    assert strong_aux["voltage"][:, -1].norm() < 0.1 * weak_aux["voltage"][:, -1].norm()


def test_regeneration_changes_later_drift_and_event_probability():
    low = ContinuousSpikingBlock(2, mode="no_adaptation")
    with torch.no_grad():
        layer = low.layers[0]
        layer.drift_input.weight.zero_()
        layer.drift_bias.fill_(0.7)
        layer.channel_gates.weight.zero_()
        layer.channel_gates.bias.zero_()
        layer.raw_regeneration.fill_(-15)
    high = copy.deepcopy(low)
    with torch.no_grad():
        high.layers[0].raw_regeneration.fill_(math.log(math.expm1(3.0)))
    x, dt = torch.zeros(1, 3, 2), torch.ones(1, 3)
    _, low_aux = low(x, dt)
    _, high_aux = high(x, dt)
    torch.testing.assert_close(
        low_aux["event_probability"][:, 0], high_aux["event_probability"][:, 0]
    )
    assert high_aux["drift"][:, 1].min() > low_aux["drift"][:, 1].max()
    assert (
        high_aux["event_probability"][:, 1].min()
        > low_aux["event_probability"][:, 1].max()
    )


def test_long_trace_is_finite_and_content_is_bounded_at_initial_parameters():
    torch.manual_seed(7)
    model = ContinuousSpikingBlock(4)
    with torch.no_grad():
        result, aux = model(torch.randn(2, 256, 4), torch.full((2, 256), 0.25))
    assert torch.isfinite(result).all() and torch.isfinite(aux["voltage"]).all()
    assert aux["content"].abs().max() <= 1.000001
    assert aux["voltage"].abs().max() < 10


def test_analytic_bellman_matches_exact_single_observation_and_refines():
    errors = []
    for grid_size in (129, 257, 513):
        solver = FiniteHorizonStoppingBoundary(grid_size=grid_size).double()
        snr = torch.tensor([0.2, 0.5, 0.8], dtype=torch.float64)
        result = solver(
            torch.zeros_like(snr),
            torch.ones(3, dtype=torch.long),
            snr,
            torch.full_like(snr, 0.01),
        )
        exact = torch.special.ndtr(snr) - 0.01
        errors.append(float((result["wait_value"] - exact).abs().max()))
    assert errors[-1] < 3e-5 and errors[-1] < errors[0] / 8


def test_bellman_independent_quadrature_and_zero_information():
    analytic = FiniteHorizonStoppingBoundary(grid_size=257).double()
    quadrature = FiniteHorizonStoppingBoundary(
        grid_size=513, quadrature_points=121, integration="quadrature"
    ).double()
    snr, cost = (
        torch.tensor([0.5], dtype=torch.float64),
        torch.tensor([0.01], dtype=torch.float64),
    )
    result = analytic(
        torch.tensor([0.0, 0.7], dtype=torch.float64), torch.tensor([4, 3]), snr, cost
    )
    reference = quadrature(
        torch.tensor([0.0, 0.7], dtype=torch.float64), torch.tensor([4, 3]), snr, cost
    )
    torch.testing.assert_close(result["value"], reference["value"], atol=1e-3, rtol=0)
    no_information = analytic(
        torch.tensor([0.0]),
        torch.tensor([5]),
        torch.tensor([0.0]),
        torch.tensor([0.01]),
    )
    assert no_information["stop"].item()
