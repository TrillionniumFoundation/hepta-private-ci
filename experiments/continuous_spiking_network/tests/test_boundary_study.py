import torch

from experiments.continuous_spiking_network.boundary import (
    FiniteHorizonStoppingBoundary,
)
from experiments.continuous_spiking_network.boundary_study import (
    fit_direct,
    make_episodes,
    prefix_log_odds,
    stop_record,
    train_actor,
    value_mask,
)
from experiments.continuous_spiking_network.models import SequenceClassifier


def test_actual_actor_training_reload_and_causal_prefixes(tmp_path):
    train = make_episodes(32, 5, [0.4, 0.8], [0.01], 14, "fixture_train")
    validation = make_episodes(16, 5, [0.4], [0.01], 15, "fixture_validation")
    model, receipt = train_actor(train, validation, 3, tmp_path, updates=3, width=8)
    initial = SequenceClassifier(**model.config)
    assert (
        sum(
            float((a - b).abs().sum().detach())
            for a, b in zip(model.parameters(), initial.parameters(), strict=True)
        )
        > 0
    )
    assert receipt["checkpoint_reload_max_error"] == 0
    assert receipt["training_examples_seen"] == 96
    assert all(item["finite"] for item in receipt["gradient_groups"].values())
    modified = dict(validation)
    modified["x"] = validation["x"].clone()
    modified["x"][:, 3:, 0] += 50
    before, after = prefix_log_odds(model, validation), prefix_log_odds(model, modified)
    torch.testing.assert_close(before[:, :3], after[:, :3], atol=0, rtol=0)
    policy, direct = fit_direct(prefix_log_odds(model, train), train, updates=3)
    assert direct["gradient_groups"]["direct_bias"] > 0
    assert sum(p.numel() for p in policy.parameters()) == 4


def test_first_observation_cost_and_forced_horizon_stop():
    batch = make_episodes(2, 3, [0.5], [0.1], 6, "fixture")
    odds = torch.tensor([[2.0, -3.0, -3.0], [-2.0, 1.0, 2.0]])
    result = stop_record(
        odds, torch.tensor([[True, False, False], [False, False, False]]), batch
    )
    assert result["stop_index"].tolist() == [0, 2]
    assert result["observations"].tolist() == [1, 3]
    torch.testing.assert_close(
        result["total_cost"], torch.tensor([0.1, 0.3], dtype=torch.float64)
    )
    torch.testing.assert_close(
        result["net_utility"], result["correct"].double() - result["total_cost"]
    )
    assert result["action"].tolist() == [1, 1]


def test_cached_value_execution_matches_independent_single_step_value():
    batch = make_episodes(3, 2, [0.5], [0.01], 22, "fixture")
    odds = torch.zeros(3, 2)
    solver = FiniteHorizonStoppingBoundary(grid_size=513).double()
    cache, timing = (
        {},
        {"bellman_build_cpu_seconds": 0.0, "bellman_evaluation_cpu_seconds": 0.0},
    )
    mask = value_mask(odds, batch, solver, cache, timing)
    assert mask.tolist() == [[False, True]] * 3
    table = next(iter(cache.values()))
    value = solver.evaluate(
        torch.zeros(1, dtype=torch.float64), torch.tensor([1]), table
    )["wait_value"]
    exact = torch.special.ndtr(torch.tensor([0.5], dtype=torch.float64)) - 0.01
    torch.testing.assert_close(value, exact, atol=2e-5, rtol=0)
    changed = odds.clone()
    changed[:, 1] = 100
    assert torch.equal(
        value_mask(changed, batch, solver, cache, timing)[:, 0], mask[:, 0]
    )
    assert len(cache) == 1
