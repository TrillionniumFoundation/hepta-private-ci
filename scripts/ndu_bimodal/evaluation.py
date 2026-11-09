"""Frozen finite-model comparisons retaining no-update.

Future procedural draws are first generated after every fit/calibration freezes.
They still share the teacher's known finite support; this is not a claim about
real future tasks, semantic model improvement or matched complete real cost.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time
from . import finite as f
from .learning import (
    calibrate,
    digest,
    fit_candidate,
    model_identity,
    save_candidate,
    state_key,
)

BASELINES = (
    "encoder-only",
    "static-quota",
    "fixed-steps",
    "light",
    "exact-DP",
    "privileged-oracle",
    "tuned-fixed",
)


def draw(seed, state, action):
    """Common counter randomness; only prophet may read future draws."""
    raw = hashlib.sha256(json.dumps([seed, state.time, action.name]).encode()).digest()
    return int.from_bytes(raw[:8], "big") / 2**64


def sampled_transition(state, action, model, seed):
    rows, uniform, total = (
        model.transitions(state, action),
        draw(seed, state, action),
        0.0,
    )
    for probability, successor, cost in rows:
        total += probability
        if uniform < total:
            return successor, cost
    return rows[-1][1], rows[-1][2]


def terminal_choice(state, model):
    actions = [a for a in f.legal_actions(state, model) if a.verb in {"STOP", "SUBMIT"}]
    return max(actions, key=lambda a: f.terminal_value(state, model, a))


def baseline(kind, model, seed, *, fixed_schedule=()):
    """All controls use current public state; prophet receives extra future data."""
    if kind not in BASELINES:
        raise ValueError("Unknown fixed comparator")
    fixed_schedule = tuple(fixed_schedule)
    if len(fixed_schedule) > 3 or set(fixed_schedule) - {"text", "image", "both"}:
        raise ValueError("Invalid registered fixed schedule")

    @lru_cache(maxsize=None)
    def prophet(state):
        scores = {}
        for action in f.legal_actions(state, model):
            if action.verb in {"STOP", "SUBMIT"}:
                scores[action] = f.terminal_value(state, model, action)
            else:
                successor, cost = sampled_transition(state, action, model, seed)
                scores[action] = (
                    prophet(successor)[0] - model.utility_per_credit * cost.total
                )
        chosen = max(scores, key=scores.get)
        return scores[chosen], chosen

    def choose(state):
        legal, terminal = f.legal_actions(state, model), terminal_choice(state, model)
        if kind == "encoder-only":
            return terminal
        if kind == "privileged-oracle":
            return prophet(state)[1]
        if kind == "exact-DP":
            scores = f.exact_scores(state, model)
            return max(scores, key=scores.get)
        if kind == "light":
            scores = {
                a: f.terminal_value(state, model, a)
                for a in legal
                if a.verb in {"STOP", "SUBMIT"}
            }
            for action in legal:
                if action in scores:
                    continue
                rows = model.transitions(state, action)
                values = [
                    f.terminal_value(s, model, terminal_choice(s, model))
                    - model.utility_per_credit * c.total
                    for _, s, c in rows
                ]
                scores[action] = f.certainty_equivalent(
                    values, [p for p, _, _ in rows], model.risk
                )
            return max(scores, key=scores.get)
        if kind == "tuned-fixed":
            if state.steps >= len(fixed_schedule):
                return terminal
            desired = fixed_schedule[state.steps]
            return next(
                (a for a in legal if a.verb == "REPAIR" and a.modality == desired),
                terminal,
            )
        if kind == "fixed-steps" and state.steps >= 2:
            return terminal
        wanted = (
            "both"
            if kind == "fixed-steps"
            else ("text" if state.steps % 2 == 0 else "image")
        )
        selected = [a for a in legal if a.verb == "REPAIR" and a.modality == wanted]
        return selected[0] if selected else terminal

    return choose


def rollout(root, model, policy, seed):
    state, total, controller_seconds, steps, categories, fallback = (
        root,
        0,
        0.0,
        [],
        {},
        0,
    )
    for _ in range(model.max_steps + 2):
        started = time.perf_counter()
        result = policy(state)
        elapsed = time.perf_counter() - started
        action, metadata = result if isinstance(result, tuple) else (result, {})
        controller_seconds += elapsed
        fallback += int(metadata.get("fallback", False))
        if action not in f.legal_actions(state, model):
            raise ValueError("Policy produced illegal action")
        cost = model.cost(state, action)
        for category, amount in asdict(cost).items():
            categories[category] = categories.get(category, 0) + amount
        steps.append(
            {
                "action": action.name,
                "modality_shares": list(action.shares),
                "credits": cost.total,
                "time": state.time,
            }
        )
        if action.verb in {"STOP", "SUBMIT"}:
            return {
                "net_utility": f.terminal_value(state, model, action)
                - model.utility_per_credit * total,
                "credits": total + cost.total,
                "controller_seconds": controller_seconds,
                "cost_categories": categories,
                "steps": steps,
                "final_state": asdict(state),
                "terminal_action": action.name,
                "fallback_decisions": fallback,
            }
        state, observed_cost = sampled_transition(state, action, model, seed)
        if observed_cost != cost:
            raise AssertionError("Observed finite fee differs from public quote")
        total += cost.total
    raise AssertionError("Finite policy failed to terminate")


def _paired_interval(values, *, seed=1907, draws=1200, alpha=0.05):
    if not values or not values[0] or any(len(row) != len(values[0]) for row in values):
        raise ValueError("Complete rectangular paired outcomes required")
    mean = statistics.fmean(statistics.fmean(row) for row in values)
    rng, samples = random.Random(seed), []
    for _ in range(draws):
        fi = rng.choices(range(len(values)), k=len(values))
        si = rng.choices(range(len(values[0])), k=len(values[0]))
        samples.append(statistics.fmean(values[i][j] for i in fi for j in si))
    samples.sort()
    return {
        "mean": mean,
        "interval": [
            samples[int(alpha / 2 * (draws - 1))],
            samples[int((1 - alpha / 2) * (draws - 1))],
        ],
        "fits": len(values),
        "sources": len(values[0]),
        "scope": "descriptive crossed procedural-source/initialization bootstrap",
    }


def tune_fixed(roots, model, calibration_seeds, grid):
    """Select one frozen schedule using calibration outcomes only."""
    if (
        len(set(calibration_seeds)) != len(calibration_seeds)
        or not calibration_seeds
        or not grid
    ):
        raise ValueError("Unique calibration seeds and a registered grid required")
    started, cpu = time.perf_counter(), time.process_time()
    trials = []
    for index, schedule in enumerate(grid):
        samples = []
        for seed in calibration_seeds:
            root = random.Random(seed).choice(roots)
            row = rollout(
                root,
                model,
                baseline("tuned-fixed", model, seed, fixed_schedule=schedule),
                seed,
            )
            samples.append(
                {
                    "source_id": f"procedural-calibration-{seed}",
                    "seed": seed,
                    "net_utility": row["net_utility"],
                    "credits": row["credits"],
                    "controller_seconds": row["controller_seconds"],
                    "terminal_action": row["terminal_action"],
                }
            )
        trials.append(
            {
                "index": index,
                "schedule": list(schedule),
                "mean_net_utility": statistics.fmean(r["net_utility"] for r in samples),
                "samples": samples,
            }
        )
    selected = max(trials, key=lambda row: row["mean_net_utility"])
    return {
        "selection": "highest calibration mean realized net utility; first registered schedule breaks ties",
        "selected_index": selected["index"],
        "selected_schedule": selected["schedule"],
        "grid_sha256": digest(grid),
        "calibration_seeds": list(calibration_seeds),
        "trials": trials,
        "schedule_attempts": len(trials),
        "calibration_episodes": len(trials) * len(calibration_seeds),
        "tuning_seconds": time.perf_counter() - started,
        "tuning_cpu_seconds": time.process_time() - cpu,
        "simulated_credits": sum(
            r["credits"] for trial in trials for r in trial["samples"]
        ),
        "controller_seconds": math.fsum(
            r["controller_seconds"] for trial in trials for r in trial["samples"]
        ),
        "outcome_scope": "declared finite simulator; calibration only; no future reselection",
    }


def control_factorial(rows, seeds):
    """Reuse executed rows for training x fixed/dynamic execution contrasts."""
    fixed = [r["net_utility"] for r in rows["static-quota"]]
    left, right = rows["dynamic/fixed/trained"], rows["dynamic/trainable/trained"]
    if (
        not fixed
        or len(left) != len(seeds)
        or len(right) != len(seeds)
        or any(len(fit) != len(fixed) for fit in (*left, *right))
    ):
        raise ValueError("Complete paired factorial rows required")
    values = {
        "A": [list(fixed) for _ in seeds],
        "B": [[r["net_utility"] for r in fit] for fit in left],
        "C": [list(fixed) for _ in seeds],
        "D": [[r["net_utility"] for r in fit] for fit in right],
    }
    coefficients = {
        "dynamic_minus_fixed/fixed_hidden": {"B": 1, "A": -1},
        "dynamic_minus_fixed/trainable_hidden": {"D": 1, "C": -1},
        "training_difference/fixed_execution": {"C": 1, "A": -1},
        "training_difference/dynamic_execution": {"D": 1, "B": -1},
        "interaction": {"D": 1, "C": -1, "B": -1, "A": 1},
    }
    contrasts = {}
    for name, factors in coefficients.items():
        paired = [
            [
                math.fsum(coef * values[cell][i][j] for cell, coef in factors.items())
                for j in range(len(fixed))
            ]
            for i in range(len(seeds))
        ]
        contrasts[name] = {
            "coefficients": factors,
            "paired_values": paired,
            **_paired_interval(paired),
        }
    return {
        "training_factor": ["fixed_hidden", "trainable_hidden"],
        "execution_factor": ["fixed_execution", "dynamic_execution"],
        "cells": {
            "A": {
                "training": "fixed_hidden",
                "execution": "fixed_execution",
                "method": "static-quota",
            },
            "B": {
                "training": "fixed_hidden",
                "execution": "dynamic_execution",
                "method": "dynamic/fixed/trained",
            },
            "C": {
                "training": "trainable_hidden",
                "execution": "fixed_execution",
                "method": "static-quota",
            },
            "D": {
                "training": "trainable_hidden",
                "execution": "dynamic_execution",
                "method": "dynamic/trainable/trained",
            },
        },
        "training_seeds": list(seeds),
        "values": values,
        "contrasts": contrasts,
        "additional_fits": 0,
        "fixed_execution_independent_of_fit": True,
        "fixed_execution_physical_episodes": len(fixed),
        "duplicated_matrix_values_are_new_executions": False,
        "scope": "finite controller representation training; not full Hepta or NDU joint training",
    }


def run_experiment(
    roots,
    model,
    *,
    seeds=(11, 29, 47),
    epochs=240,
    calibration_sources=24,
    future_sources=48,
    output=None,
):
    if (
        len(seeds) < 3
        or len(set(seeds)) != len(seeds)
        or not 10 <= calibration_sources <= 256
        or not 8 <= future_sources <= 512
    ):
        raise ValueError("Three independent fits and bounded source rosters required")
    roots = tuple(roots)
    if not roots:
        raise ValueError("At least one public initial state required")
    registration = {
        "schema": "hepta.bimodal.finite-evaluation.v1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "model_id": model_identity(model),
        "model": asdict(model),
        "roots": [asdict(s) for s in roots],
        "training_seeds": list(seeds),
        "training_source": "declared_finite_model_exhaustive_DP_support",
        "calibration_seeds": list(range(100000, 100000 + calibration_sources)),
        "future_seeds": list(range(200000, 200000 + future_sources)),
        "methods": list(BASELINES)
        + [
            f"dynamic/{t}/{m}"
            for t in ("fixed", "trainable")
            for m in ("trained", "reset")
        ],
        "epochs": epochs,
        "margin": 0.002,
        "alpha": 0.1,
        "training_and_execution_ablation": "fixed/trainable hidden training crossed with fixed/dynamic execution",
        "representation_ablation": "separate trained/reset hidden execution features; identical backbone",
        "fixed_schedule_grid": [
            list(s)
            for n in range(4)
            for s in product(("text", "image", "both"), repeat=n)
        ],
        "no_semantic_source_holdout_claim": True,
        "future_seeds_registered_before_fit": True,
        "future_outcomes_materialized_after_freeze": True,
        "oracle": "prophet sees future counter draws; extra information and search cost; excluded from fair promotion",
    }
    sets = [
        set(registration[k])
        for k in ("training_seeds", "calibration_seeds", "future_seeds")
    ]
    if any(a & b for i, a in enumerate(sets) for b in sets[i + 1 :]):
        raise ValueError("Training/calibration/future seeds overlap")
    folder = Path(output) if output is not None else None
    if folder:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "registration.json").write_text(
            json.dumps(registration, indent=2) + "\n"
        )
    started, cpu = time.perf_counter(), time.process_time()
    build_start = time.perf_counter()
    states = tuple(sorted(f.reachable_states(roots, model), key=state_key))
    for state in states:
        f.exact_scores(state, model)
    pairs = [
        (s, a)
        for s in states
        for a in f.legal_actions(s, model)
        if f.uncertain(s, a, model)
    ]
    build_seconds = time.perf_counter() - build_start
    if not pairs:
        raise ValueError("No uncertain finite support")
    groups = {
        f"procedural-calibration-{seed}": random.Random(seed).sample(
            pairs, min(16, len(pairs))
        )
        for seed in registration["calibration_seeds"]
    }
    tuning = tune_fixed(
        roots,
        model,
        registration["calibration_seeds"],
        registration["fixed_schedule_grid"],
    )
    candidates, fits, checkpoints, calibrations = [], [], [], []
    for seed in seeds:
        for train in ("fixed", "trainable"):
            candidate = fit_candidate(
                roots,
                model,
                seed=seed,
                trainable_features=train == "trainable",
                epochs=epochs,
            )
            fits.append(candidate.receipt)
            for mode in ("trained", "reset"):
                record = calibrate(
                    candidate, model, groups, mode=mode, alpha=registration["alpha"]
                )
                calibrations.append({"training_seed": seed, "train": train, **record})
            candidates.append((seed, train, candidate))
            if folder:
                checkpoints.append(
                    save_candidate(candidate, folder / f"advantage-{train}-{seed}.json")
                )
    frozen = {
        "fits_frozen_at": datetime.now(timezone.utc).isoformat(),
        "candidate_parameter_sha256": [
            digest({k: v.tolist() for k, v in c.network.state_dict().items()})
            for _, _, c in candidates
        ],
        "calibrations_sha256": digest(calibrations),
        "fixed_tuning_sha256": digest(tuning),
    }
    if folder:
        (folder / "candidate-freeze.json").write_text(
            json.dumps(frozen, indent=2) + "\n"
        )
    # Outcomes and procedural roots are first materialized after every fit freezes.
    future = [
        (f"procedural-future-{seed}", seed, random.Random(seed).choice(roots))
        for seed in registration["future_seeds"]
    ]
    rows, coverage = {}, []
    for kind in BASELINES:
        rows[kind] = [
            rollout(
                root,
                model,
                baseline(
                    kind,
                    model,
                    seed,
                    fixed_schedule=tuning["selected_schedule"]
                    if kind == "tuned-fixed"
                    else (),
                ),
                seed,
            )
            for _, seed, root in future
        ]
    for seed, train, candidate in candidates:
        for mode in ("trained", "reset"):
            key = f"dynamic/{train}/{mode}"
            rows.setdefault(key, []).append(
                [
                    rollout(
                        root,
                        model,
                        lambda s: candidate.choose(
                            s, model, mode=mode, margin=registration["margin"]
                        ),
                        episode_seed,
                    )
                    for _, episode_seed, root in future
                ]
            )
            covered, attempted, rejected = 0, 0, 0
            calibration = candidate.calibrations[mode]
            for _, episode_seed, _ in future:
                for state, action in random.Random(episode_seed).sample(
                    pairs, min(16, len(pairs))
                ):
                    attempted += 1
                    target = f.exact_scores(state, model)[action] - f.terminal_value(
                        state, model
                    )
                    radius = calibration["radius"]
                    if radius is None:
                        rejected += 1
                    else:
                        covered += (
                            abs(candidate.predict(state, action, mode) - target)
                            <= radius
                        )
            coverage.append(
                {
                    "training_seed": seed,
                    "train": train,
                    "execution": mode,
                    "pairs": attempted,
                    "rejected": rejected,
                    "covered": covered,
                    "empirical_pair_coverage": covered / attempted,
                    "scope": "future procedural finite-DP approximation; no conditional guarantee",
                }
            )
    after = [
        digest({k: v.tolist() for k, v in c.network.state_dict().items()})
        for _, _, c in candidates
    ]
    if (
        after != frozen["candidate_parameter_sha256"]
        or digest(calibrations) != frozen["calibrations_sha256"]
    ):
        raise AssertionError("Future evaluation changed frozen candidate")
    if digest(tuning) != frozen["fixed_tuning_sha256"]:
        raise AssertionError("Future evaluation changed fixed-policy selection")
    summaries = {}
    for method, result in rows.items():
        flat = result if method in BASELINES else [r for fit in result for r in fit]
        summaries[method] = {
            "episodes": len(flat),
            "mean_net_utility": statistics.fmean(r["net_utility"] for r in flat),
            "mean_credits": statistics.fmean(r["credits"] for r in flat),
            "controller_seconds": math.fsum(r["controller_seconds"] for r in flat),
            "fallback_decisions": sum(r["fallback_decisions"] for r in flat),
            "mean_cost_categories": {
                k: statistics.fmean(r["cost_categories"].get(k, 0) for r in flat)
                for k in sorted({k for r in flat for k in r["cost_categories"]})
            },
        }
    selected = "dynamic/trainable/trained"
    fair = [m for m in BASELINES if m not in {"privileged-oracle", "exact-DP"}]
    contrasts = {
        name: _paired_interval(
            [
                [r["net_utility"] - b["net_utility"] for r, b in zip(fit, rows[name])]
                for fit in rows[selected]
            ],
            alpha=0.05 / len(fair),
        )
        for name in fair
    }
    representation_contrasts = {}
    for left, right in (
        ("dynamic/trainable/trained", "dynamic/fixed/trained"),
        ("dynamic/trainable/trained", "dynamic/trainable/reset"),
        ("dynamic/fixed/trained", "dynamic/fixed/reset"),
    ):
        representation_contrasts[f"{left} minus {right}"] = _paired_interval(
            [
                [a["net_utility"] - b["net_utility"] for a, b in zip(lf, rf)]
                for lf, rf in zip(rows[left], rows[right])
            ]
        )
    robust = all(contrasts[m]["interval"][0] > registration["margin"] for m in fair)
    report = {
        "registration": registration,
        "registration_sha256": digest(registration),
        "freeze": frozen,
        "status": "completed",
        "decision": "no-update",
        "production_adoption": False,
        "finite_domain_gain_clears_descriptive_margin": robust,
        "reason": "synthetic model and incomplete independent real-cost/retention evidence"
        if robust
        else "no robust net gain over all registered fixed/light controls",
        "summaries": summaries,
        "paired_contrasts": contrasts,
        "coverage": coverage,
        "fits": fits,
        "control_factorial": control_factorial(rows, seeds),
        "representation_ablation": {
            "execution_levels": ["trained", "reset"],
            "contrasts": representation_contrasts,
        },
        "fixed_policy_tuning": tuning,
        "calibrations": calibrations,
        "checkpoints": checkpoints,
        "sources": [x[0] for x in future],
        "episodes": rows,
        "reachable_states": len(states),
        "uncertain_pairs": len(pairs),
        "costs": {
            "shared_DP_support_build_seconds": build_seconds,
            "fixed_tuning_seconds": tuning["tuning_seconds"],
            "fixed_tuning_cpu_seconds": tuning["tuning_cpu_seconds"],
            "fixed_tuning_simulated_credits": tuning["simulated_credits"],
            "fit_seconds": math.fsum(r["training_seconds"] for r in fits),
            "whole_evaluation_seconds": time.perf_counter() - started,
            "whole_evaluation_cpu_seconds": time.process_time() - cpu,
            "action_credits": "identical immutable seven-category transition tariff for every method",
            "controller_timing": "measured raw wall time extra to simulated tariffs; warm cache; inference/support checks included",
            "nested_clocks_additive": False,
            "whole_real_resource_budget_matched": False,
            "energy_joules": None,
            "provider_money": None,
            "value_semantics": "terminal utility less all simulated fees; not flattened nested-entropic risk",
        },
        "oracle_is_fair_baseline": False,
        "state_space_global_optimality": "exact DP only inside declared finite model",
        "future_source_scope": "registered procedural RNG draws on known finite support; not real future distribution",
    }
    if folder:
        (folder / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
    return report


def run_study(
    output,
    *,
    roots=None,
    model=None,
    seeds=(11, 29, 47),
    epochs=240,
    calibration_sources=24,
    future_sources=48,
):
    """Stable runner entry; default roots cover the registered finite profile."""
    model = f.Model() if model is None else model
    if roots is None:
        roots = tuple(
            f.State(text_grade=t, image_grade=i, budget=b)
            for b in (18, 24, 30)
            for t in (0, 1)
            for i in (0, 1)
        )
    return run_experiment(
        roots,
        model,
        seeds=seeds,
        epochs=epochs,
        calibration_sources=calibration_sources,
        future_sources=future_sources,
        output=output,
    )
