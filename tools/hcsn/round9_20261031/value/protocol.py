"""Predeclared new experiment; R8 holdouts remain historical regression data."""

from dataclasses import asdict, replace

from tools.hcsn.round8_20261031.value_calibration import finite


MODES = ("first_passage", "clocked", "direct")
SEEDS = (11, 12, 13, 14, 15)
TRAIN_EXTRA = (
    dict(ordinary_reliability=.55, delayed_reliability=.70, prior_probability=.35),
    dict(horizon=4, budget=4, ordinary_reliability=.60, delayed_reliability=.75, prior_probability=.70),
    dict(corruption_probability=.90, arrival_tick=3),
    dict(budget=3, corruption_probability=.60, arrival_tick=4),
    dict(read_cost=.10, repair_cost=.14, latency_cost=.025),
    dict(horizon=4, budget=4, read_cost=.06, repair_cost=.09, latency_cost=.015),
    dict(ordinary_reliability=.60, delayed_reliability=.75, prior_probability=.35,
         corruption_probability=.60, arrival_tick=3, read_cost=.06, repair_cost=.09, latency_cost=.015),
    dict(horizon=5, budget=3, ordinary_reliability=.80, delayed_reliability=.92, prior_probability=.70,
         corruption_probability=.90, arrival_tick=4, read_cost=.10, repair_cost=.14, latency_cost=.025),
)
BLIND = (
    dict(horizon=5, budget=5, ordinary_reliability=.63, delayed_reliability=.81, prior_probability=.60,
         corruption_probability=.55, arrival_tick=3, read_cost=.03, repair_cost=.07, latency_cost=.012),
    dict(horizon=6, budget=3, ordinary_reliability=.76, delayed_reliability=.86, prior_probability=.42,
         corruption_probability=.72, arrival_tick=3, read_cost=.07, repair_cost=.105, latency_cost=.018),
    dict(horizon=4, budget=4, ordinary_reliability=.59, delayed_reliability=.74, prior_probability=.62,
         corruption_probability=.65, arrival_tick=3, read_cost=.05, repair_cost=.06, latency_cost=.010),
    dict(horizon=5, budget=2, ordinary_reliability=.73, delayed_reliability=.88, prior_probability=.45,
         corruption_probability=.85, arrival_tick=4, read_cost=.09, repair_cost=.13, latency_cost=.022),
    dict(horizon=3, budget=1, ordinary_reliability=.61, delayed_reliability=.79, prior_probability=.55,
         corruption_probability=.40, arrival_tick=2, read_cost=.02, repair_cost=.04, latency_cost=.008),
    dict(horizon=6, budget=6, ordinary_reliability=.78, delayed_reliability=.93, prior_probability=.68,
         corruption_probability=.25, arrival_tick=2, read_cost=.065, repair_cost=.11, latency_cost=.017),
    dict(horizon=6, budget=5, ordinary_reliability=.56, delayed_reliability=.73, prior_probability=.38,
         corruption_probability=.88, arrival_tick=4, read_cost=.008, repair_cost=.025, latency_cost=.007),
    dict(horizon=4, budget=3, ordinary_reliability=.68, delayed_reliability=.83, prior_probability=.52,
         corruption_probability=.50, arrival_tick=2, read_cost=.04, repair_cost=.075, latency_cost=.013),
)


def contracts(regime):
    if regime == "training":
        return finite.configurations() + [replace(finite.task.TaskParameters(), **p) for p in TRAIN_EXTRA]
    if regime == "blind":
        return [replace(finite.task.TaskParameters(), **p) for p in BLIND]
    return finite.configurations(regime)


def record():
    return {"schema": "hepta.r9.value.protocol.v1", "base_commit": "333fb9b036b80cf5d892aed222a1aac7aad80e53",
        "training_contracts": [asdict(p) for p in contracts("training")],
        "blind_contracts": [asdict(p) for p in contracts("blind")],
        "regimes": ["nominal", "drift", "missing", "cost_shift", "blind"],
        "historical_regression_only": ["nominal", "drift", "missing", "cost_shift"],
        "modes": list(MODES), "core_seeds": list(SEEDS), "head_seed_offset": 931000,
        "hidden": 32, "iteration_cap": 2400, "episodes_per_contract_fit": 128,
        "episode_seed_start": 93100000, "latent_seed_offset": 20000000,
        "training_weights": "equal contracts, equal public states within contract, equal latent states",
        "repair": "factor known action plus latency costs; learn only continuation relative to current evidence quality",
        "nominal_preservation": "exact membership of original 18-dimensional nominal public inputs uses unchanged R8 head; all other inputs execute trained R9 head; no rejection",
        "control": "identical decoder, router, capacity, label access and optimizer cap for first_passage, clocked, direct",
        "primary_regime": "blind", "primary_contrasts": "R9 routed head minus frozen R8 calibrated head within each family",
        "primary_interval": "five paired fit means, Student-t, Bonferroni 98.333333% for three families",
        "primary_gates": {"utility_interval_lower": 0., "action_regret_reduction_interval_lower": 0.,
            "quality_noninferiority_margin": .02, "cpu_priced_interval_lower": 0.,
            "cpu_price": 1., "training_amortization_sessions": 10000},
        "no_retuning_after_holdout": True, "online_oracle": False,
        "cost_scope": "new training and label generation, routing and full per-decision encoder/cell/head execution; R7/R8 training is shared sunk work; evaluation is reported separately",
        "not_claimed": ["causal isolation of decomposition versus expanded training", "model-free learning",
            "new joint boundary training", "analytic-state advantage", "continuous QVI", "production authorization"]}
