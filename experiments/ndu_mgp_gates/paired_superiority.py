"""Research-only P1 comparison of ACTUAL decoded, paired heldout output scores.

This does not run a decoder, authenticate observations, or verify signatures. It
rejects incomplete/different-information arms and cannot mint scientific authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Mapping

import numpy as np

ARMS = ("ndu", "no_change", "static", "moe", "risk_neutral_mpc",
        "fixed_risk_mpc", "free_controller")
CONTROLS = ARMS[1:]
METRICS = ("loss", "quality", "ambiguity", "inconsistency")
COST_PARTS = ("encoder", "backbone", "cell", "controller", "decoder",
              "verifier", "training_amortized")


class EvidenceGap(ValueError):
    """Reject omissions and incomparable or non-finite heldout evidence."""


def _need(test, why):
    if not test:
        raise EvidenceGap(why)


def _number(x, name, *, lower=0.0, upper=float("inf")):
    _need(type(x) in (int, float) and math.isfinite(x) and lower <= x <= upper,
          "nonfinite/out-of-bound " + name)
    return float(x)


def cvar90(x):
    """Worst 10% equal-probability *mass*, including fractional boundary row."""
    x = np.asarray(x, dtype=np.float64)
    _need(x.ndim == 1 and x.size >= 10 and np.isfinite(x).all() and (x >= 0).all(),
          "CVaR requires >=10 finite nonnegative worlds")
    ordered = np.sort(x)[::-1]
    mass = 0.1 * len(ordered)
    whole = math.floor(mass)
    numerator = float(ordered[:whole].sum())
    if mass > whole:
        numerator += (mass - whole) * float(ordered[whole])
    return numerator / mass


def evaluate(study: Mapping):
    """Return a paired, simultaneous-CI shadow report, never production PASS.

    ``worlds`` must list every preregistered world in every seed. One draw row
    covers one actual decoded output: no standalone-loss mixture is accepted.
    Measured physical-cost components must reconcile to the actual observed total.
    """
    _need(isinstance(study, dict) and study.get("schema") == "hepta-mgp-paired-v1",
          "unknown study protocol")
    protocol = study.get("protocol")
    _need(isinstance(protocol, dict), "missing preregistration")
    seeds = protocol.get("seeds")
    world_ids = protocol.get("heldout_world_ids")
    _need(isinstance(seeds, list) and len(seeds) >= 3 and
          all(type(s) is int for s in seeds) and len(set(seeds)) == len(seeds),
          "need >=3 distinct registered seeds")
    _need(isinstance(world_ids, dict) and set(world_ids) == {str(s) for s in seeds},
          "heldout world manifest must cover every registered seed")
    counts = [len(world_ids[str(s)]) for s in seeds]
    _need(len(set(counts)) == 1 and counts[0] >= 32, "need >=32 matched worlds per seed")
    flat_ids = [k for s in seeds for k in world_ids[str(s)]]
    _need(all(isinstance(k, str) and k for k in flat_ids) and
          len(set(flat_ids)) == len(flat_ids), "missing/duplicated heldout world IDs")
    calibration_ids = protocol.get("calibration_world_ids")
    _need(isinstance(calibration_ids, list) and len(calibration_ids) > 0 and
          all(isinstance(x, str) and x for x in calibration_ids) and
          len(set(calibration_ids)) == len(calibration_ids) and
          len(set(flat_ids).intersection(calibration_ids)) == 0,
          "calibration/heldout leakage or invalid/empty calibration lock")
    _need(tuple(protocol.get("arms", [])) == ARMS, "comparison arms not exact/frozen")
    _need(protocol.get("validation_selected_best") in CONTROLS and
          isinstance(protocol.get("selection_lock_digest"), str) and
          len(protocol["selection_lock_digest"]) == 64, "missing frozen validation selection")
    for key in ("model_digest", "decoder_digest", "objective_digest", "actuator_digest"):
        _need(isinstance(protocol.get(key), str) and len(protocol[key]) == 64,
              "missing frozen same-model/actuator identity: " + key)
    min_gain = _number(protocol.get("minimum_cvar_improvement"), "minimum gain", lower=0.01)
    quality_tol = _number(protocol.get("max_quality_drop"), "quality tolerance", upper=0.05)
    ambiguity_tol = _number(protocol.get("max_ambiguity_increase"), "ambiguity tolerance", upper=0.05)
    inconsistency_tol = _number(protocol.get("max_inconsistency_increase"), "inconsistency tolerance", upper=0.05)
    max_cost_ratio = _number(protocol.get("max_total_cost_ratio"), "cost ratio", lower=1, upper=1.1)
    boots = protocol.get("bootstrap_replicates")
    _need(type(boots) is int and 100 <= boots <= 20000, "invalid bootstrap size")
    _need(type(protocol.get("bootstrap_seed")) is int, "missing preregistered bootstrap seed")
    alpha = _number(protocol.get("familywise_alpha"), "familywise alpha", lower=1e-5, upper=0.1)
    failure_loss = _number(protocol.get("failure_loss"), "registered failure loss", lower=1)
    draws = protocol.get("draws_per_world")
    _need(type(draws) is int and 1 <= draws <= 16, "unregistered draw count")
    cost_units = protocol.get("cost_units")
    _need(isinstance(cost_units, str) and len(cost_units) > 0, "missing measured cost unit")
    observations = study.get("worlds")
    _need(isinstance(observations, list) and len(observations) == len(flat_ids),
          "unobserved or selectively omitted heldout worlds")
    size = counts[0]
    values = np.empty((len(ARMS), len(seeds), size, len(METRICS) + 1))
    protected = np.zeros((len(seeds), size), dtype=bool)
    arm_idx = {a: i for i, a in enumerate(ARMS)}
    for i, seed in enumerate(seeds):
        for j, world_id in enumerate(world_ids[str(seed)]):
            row = observations[i * size + j]
            _need(isinstance(row, dict) and row.get("seed") == seed and
                  row.get("world_id") == world_id, "heldout world order/identity mismatch")
            context = row.get("public_input_digest")
            _need(isinstance(context, str) and len(context) == 64, "missing public input identity")
            protected[i, j] = row.get("protected_task") is True
            _need(type(row.get("protected_task")) is bool, "protected status missing")
            outcomes = row.get("outcomes")
            _need(isinstance(outcomes, dict) and set(outcomes) == set(ARMS),
                  "missing required matched control or NDU")
            for name in ARMS:
                out = outcomes[name]
                _need(isinstance(out, dict) and out.get("public_input_digest") == context and
                      out.get("model_digest") == protocol["model_digest"] and
                      out.get("decoder_digest") == protocol["decoder_digest"] and
                      out.get("objective_digest") == protocol["objective_digest"] and
                      out.get("actuator_digest") == protocol["actuator_digest"],
                      "different information, decoder, objective or actuator")
                drows = out.get("decoded_draw_scores")
                _need(isinstance(drows, list) and len(drows) == draws,
                      "missing raw-decoded draw scoring")
                entries = np.zeros((draws, len(METRICS)))
                for k, dr in enumerate(drows):
                    _need(isinstance(dr, dict) and set(dr) == set(METRICS + ("status", "output_witness_sha256")),
                          "incomplete decoded draw metrics/witness")
                    _need(dr["status"] in ("completed", "failed"), "invalid draw status")
                    _need(isinstance(dr["output_witness_sha256"], str) and
                          len(dr["output_witness_sha256"]) == 64 and
                          all(ch in "0123456789abcdef" for ch in dr["output_witness_sha256"]),
                          "missing raw-output or failure witness")
                    if dr["status"] == "failed":
                        _need(dr["loss"] == failure_loss and dr["quality"] == 0 and
                              dr["ambiguity"] == 1 and dr["inconsistency"] == 1,
                              "a failed/overbudget output cannot be dropped or awarded quality")
                    else:
                        # A declared failure penalty must be no smaller than
                        # any admitted successful semantic loss. Otherwise
                        # a failed run can look *better* than successful arms
                        # and manufacture CVaR/efficacy improvement.
                        _number(dr["loss"], "completed loss vs registered failure penalty",
                                upper=failure_loss)
                    for m, metric in enumerate(METRICS):
                        upper = float("inf") if metric == "loss" else 1
                        entries[k, m] = _number(dr[metric], metric, upper=upper)
                cost = out.get("measured_cost")
                _need(isinstance(cost, dict) and set(cost) == set(COST_PARTS + ("total",)),
                      "incomplete physical total cost receipt")
                subtotal = sum(_number(cost[x], x) for x in COST_PARTS)
                total = _number(cost["total"], "total", lower=1e-12)
                _need(abs(subtotal - total) <= max(1e-9, total * 1e-7),
                      "physical cost ledger not reconciled")
                values[arm_idx[name], i, j, :len(METRICS)] = entries.mean(axis=0)
                values[arm_idx[name], i, j, -1] = total
    # Protected-task comparisons are required for *every* registered seed,
    # not merely one convenient world in the pooled cohort. A minimum 10%
    # support (at least three independent worlds) prevents a single protected
    # fixture from satisfying a cohort-level no-regression claim.
    min_protected = max(3, math.ceil(0.1 * size))
    _need(bool(np.all(protected.sum(axis=1) >= min_protected)),
          "no protected-task or insufficient protected-task coverage per seed")
    # Every sampled heldout unit remains paired. Tail CVaR is computed within
    # seed AFTER draw aggregation, then averaged over training seeds.
    def summarize(v):
        res = np.empty((len(ARMS), len(METRICS) + 1))
        res[:, 0] = np.mean([[cvar90(row) for row in arm] for arm in v[..., 0]], axis=1)
        res[:, 1:] = v[..., 1:].mean(axis=(1, 2))
        return res
    point = summarize(values)
    rng = np.random.default_rng(protocol["bootstrap_seed"])
    # Dimension order (bootstrap, arm, metrics): same sampled seed/world draws
    # for every arm; no per-arm resampling or selecting the best test arm.
    deltas = np.empty((boots, len(CONTROLS), len(METRICS) + 1))
    # Estimate uncertainty in the *ratio* itself. A point-average cost ratio
    # hides per-training-seed resource spikes and is insufficient to claim
    # resource comparability with independently chosen controllers.
    bootstrap_cost_ratios = np.empty((boots, len(CONTROLS)))
    for k in range(boots):
        seed_sample = rng.integers(0, len(seeds), size=len(seeds))
        world_sample = rng.integers(0, size, size=(len(seeds), size))
        paired = np.stack([values[:, si, world_sample[t]] for t, si in enumerate(seed_sample)], axis=1)
        boot = summarize(paired)
        deltas[k] = boot[0] - boot[1:]
        bootstrap_cost_ratios[k] = boot[0, -1] / boot[1:, -1]
    # Bonferroni across all six comparisons and loss/quality/ambiguity/
    # inconsistency/cost; positive loss differences are bad.
    tail_level = alpha / (len(CONTROLS) * (len(METRICS) + 1))
    out = {}
    local_all = True
    for index, name in enumerate(CONTROLS):
        x = point[0] - point[index + 1]
        cloud = deltas[:, index]
        upper = np.quantile(cloud, 1 - tail_level, axis=0)
        lower = np.quantile(cloud, tail_level, axis=0)
        ratio = point[0, -1] / point[index + 1, -1]
        upper_cost_ratio = float(np.quantile(bootstrap_cost_ratios[:, index], 1 - tail_level))
        protected_delta = values[0, :, :, 1] - values[index + 1, :, :, 1]
        protected_ok = bool(np.all(protected_delta[protected] >= -1e-12))
        gates = {
            "cvar90_incremental_superiority": bool(x[0] <= -min_gain and upper[0] < -min_gain),
            "factual_quality_noninferiority": bool(lower[1] >= -quality_tol),
            "ambiguity_noninferiority": bool(upper[2] <= ambiguity_tol),
            "consistency_noninferiority": bool(upper[3] <= inconsistency_tol),
            "physical_total_cost": bool(ratio <= max_cost_ratio and
                                        upper_cost_ratio <= max_cost_ratio),
            "protected_task_no_regression": protected_ok,
        }
        local_all &= all(gates.values())
        out[name] = {"mean_pair_difference": dict(zip(("cvar90", "quality", "ambiguity", "inconsistency", "total_cost"), x.tolist())),
                     "simultaneous_lower": lower.tolist(), "simultaneous_upper": upper.tolist(),
                     "observed_cost_ratio": ratio,
                     "bootstrap_upper_cost_ratio": upper_cost_ratio,
                     "gates": gates}
    receipt = {"schema": "hepta-mgp-paired-review-v1", "status": "HOLD_NO_GO", "authority": "DENY_ALL",
               "source": "LOCAL_RESEARCH_UNAUTHENTICATED", "scientific_superiority_proven": False,
               "all_provisional_gates_pass": bool(local_all and boots >= 2000),
               "all_registered_worlds_seen": True, "registered_seeds": len(seeds),
               "worlds_per_seed": size, "draws_per_world": draws,
               "familywise_alpha": alpha, "bootstrap_replicates": boots,
               "comparator_selection": protocol["validation_selected_best"],
               "comparison": out,
               "limitations": ["untrusted caller supplied observations and metadata",
                               "no independent observer, signature verification or prospective attestation",
                               "does not execute a pretrained encoder, model, decoder or GPU inference",
                               "does not satisfy any P0-P4 production final-use gate"]}
    receipt["input_sha256"] = sha256(json.dumps(study, sort_keys=True, allow_nan=False,
                                             separators=(",", ":")).encode()).hexdigest()
    return receipt
