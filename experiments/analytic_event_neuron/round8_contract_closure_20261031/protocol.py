"""Predeclared tasks, budgets and comparisons for the contract closure."""

from dataclasses import replace

from ..round7.data import task_configuration
from ..round7.task import TaskParameters


SEEDS = tuple(range(11, 16))
MODES = ("direct", "continuous", "clocked", "first_passage")
STAGES = ("baseline", "readout", "content_readout")
EPISODES_PER_FIT_REGIME = 128
WORLD_START = {"nominal": 81000000, "heldout": 82000000}


def heldout_configuration(index):
    """New public parameter combinations, never used to select checkpoints."""
    base = TaskParameters(horizon=5, budget=4, ordinary_reliability=0.74,
                          delayed_reliability=0.87, corruption_probability=0.25,
                          read_cost=0.018, wait_cost=0.006, repair_cost=0.023,
                          latency_cost=0.006)
    variants = (
        {},
        {"horizon": 3, "budget": 1, "read_budget": 1,
         "ordinary_reliability": 0.66, "delayed_reliability": 0.92},
        {"horizon": 4, "budget": 5, "arrival_tick": 1,
         "ordinary_reliability": 0.77, "delayed_reliability": 0.86},
        {"horizon": 6, "budget": 2, "arrival_tick": 3,
         "ordinary_reliability": 0.62, "delayed_reliability": 0.94},
        {"horizon": 2, "budget": 0, "prior_probability": 0.60},
        {"read_cost": 0.052, "repair_cost": 0.035,
         "corruption_probability": 0.48},
        {"read_cost": 0.006, "wait_cost": 0.014,
         "ordinary_reliability": 0.73, "delayed_reliability": 0.89},
        {"ordinary_reliability": 0.83, "delayed_reliability": 0.88,
         "corruption_probability": 0.45},
    )
    return replace(base, **variants[index % len(variants)])


def configurations(regime):
    if regime == "nominal":
        return [task_configuration(i) for i in range(8)]
    if regime == "heldout":
        return [heldout_configuration(i) for i in range(8)]
    raise ValueError(regime)
