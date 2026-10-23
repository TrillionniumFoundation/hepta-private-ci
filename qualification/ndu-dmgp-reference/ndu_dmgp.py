#!/usr/bin/env python3
"""Qualification-only A0-A5 NDU-DMGP evidence evaluator.

This module never calls a model, updates weights, signs receipts, or grants authority.
Numerical diagnostics do not constitute production evidence or causal identification.
Python >=3.10, standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from typing import Any

ARMS = ("A0", "A1", "A2", "A3", "A4", "A5")
REQUIRED_SPLITS = ("future", "retention")
REQUIRED_MODALITIES = {"text", "image", "audio", "video"}


class EvidenceError(ValueError):
    """Invalid or unsupported evidence; fail closed rather than infer a benefit."""


def require(test: bool, message: str) -> None:
    if not test:
        raise EvidenceError(message)


def finite(value: Any, name: str, lo: float = -math.inf, hi: float = math.inf) -> float:
    require(type(value) in (int, float), f"{name}: expected numeric scalar")
    number = float(value)
    require(math.isfinite(number) and lo <= number <= hi, f"{name}: invalid value")
    return number


def nonempty(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{name}: missing")
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def paired_lcb(deltas: list[float], alpha: float = 0.01) -> dict[str, float]:
    """One-sided normal approximation. Minimum 30 independent pairing units."""
    require(len(deltas) >= 30, "paired comparison: at least 30 independent groups required")
    mu = statistics.mean(deltas)
    se = statistics.stdev(deltas) / math.sqrt(len(deltas))
    z = statistics.NormalDist().inv_cdf(1 - alpha)
    return {"mean": mu, "lcb": mu - z * se, "n": len(deltas), "alpha": alpha}


def rank(matrix: list[list[float]], relative_floor: float = 1e-8) -> int:
    m = [list(row) for row in matrix]
    if not m:
        return 0
    n = len(m)
    require(all(len(row) == n for row in m), "rank: covariance must be square")
    scale = max(1.0e-30, max(abs(x) for row in m for x in row))
    pivot_row = 0
    for col in range(n):
        pivot = max(range(pivot_row, n), key=lambda row: abs(m[row][col])) if pivot_row < n else pivot_row
        if pivot_row >= n or abs(m[pivot][col]) <= relative_floor * scale:
            continue
        m[pivot_row], m[pivot] = m[pivot], m[pivot_row]
        r = m[pivot_row][col]
        for i in range(pivot_row + 1, n):
            factor = m[i][col] / r
            for j in range(col, n):
                m[i][j] -= factor * m[pivot_row][j]
        pivot_row += 1
    return pivot_row


def eigenvalues_symmetric(matrix: list[list[float]]) -> list[float]:
    """Jacobi eigenvalue reference for a symmetric small covariance (dimension <=8)."""
    a = [row[:] for row in matrix]
    n = len(a)
    for _ in range(40 * n * n):
        p, q = max(((i, j) for i in range(n) for j in range(i + 1, n)),
                   key=lambda ij: abs(a[ij[0]][ij[1]]))
        if abs(a[p][q]) <= 1e-12 * max(1.0, max(abs(a[i][i]) for i in range(n))):
            break
        apq = a[p][q]
        tau = (a[q][q] - a[p][p]) / (2 * apq)
        t = (1 if tau >= 0 else -1) / (abs(tau) + math.sqrt(1 + tau*tau))
        c = 1 / math.sqrt(1 + t*t)
        sn = c * t
        a[p][p] -= t * apq
        a[q][q] += t * apq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            if k in (p, q):
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = c * akp - sn * akq
            a[k][q] = a[q][k] = sn * akp + c * akq
    return sorted(a[i][i] for i in range(n))


def low_rank_covariance(samples: list[dict[str, Any]], width: int, max_rank: int = 2) -> dict[str, Any]:
    """Conditional joint-trajectory covariance diagnostic (NOT a BSDE Z estimate).

    Mean-centre matched action-advantage vectors, reject rank/support collapse,
    shrink to diagonal and construct PSD diagonal-plus-low-rank approximation.
    """
    require(2 <= width <= 8, "covariance: expected 2..8 matched controls")
    require(len(samples) >= max(30, 8 * width), "covariance: insufficient matched joint trials")
    seen: set[str] = set()
    vectors: list[list[float]] = []
    weights: list[float] = []
    conditioning: str | None = None
    for trial in samples:
        group = nonempty(trial.get("group_id"), "covariance.group_id")
        require(group not in seen, "covariance: reused independent group")
        seen.add(group)
        current = nonempty(trial.get("condition_digest"), "covariance.condition_digest")
        if conditioning is None:
            conditioning = current
        require(current == conditioning, "covariance: mixed pre-decision conditional states")
        vector = trial.get("advantages")
        require(isinstance(vector, list) and len(vector) == width, "covariance: joint vector width mismatch")
        vectors.append([finite(v, "covariance.advantage", -2, 2) for v in vector])
        weights.append(finite(trial.get("weight", 1), "covariance.weight", 0.000001, 100))
    total = sum(weights)
    ess = total**2 / sum(w * w for w in weights)
    require(ess >= max(30, 8 * width), "covariance: insufficient effective sample size")
    mean = [sum(w * v[j] for v, w in zip(vectors, weights)) / total for j in range(width)]
    # Effective finite-sample weighted covariance denominator.
    denom = total - sum(w * w for w in weights) / total
    require(denom > 0, "covariance: degenerate weights")
    cov = [[sum(w * (v[i] - mean[i]) * (v[j] - mean[j]) for v, w in zip(vectors, weights)) / denom
            for j in range(width)] for i in range(width)]
    require(rank(cov) == width, "covariance: unidentifiable rank; use deterministic NDU")
    spectral = eigenvalues_symmetric(cov)
    require(spectral[0] > 1e-8, "covariance: eigenvalue floor violated; use deterministic NDU")
    condition_number = spectral[-1] / spectral[0]
    require(condition_number <= 1e6, "covariance: condition number unsupported; use deterministic NDU")
    trace = sum(cov[i][i] for i in range(width))
    require(trace > 1e-10, "covariance: collapsed conditional variance")
    # Empirical pilot profile: 25% diagonal shrinkage. This is NOT a fitted optimum.
    shrunk = [[0.75 * cov[i][j] + (0.25 * cov[i][i] if i == j else 0)
               for j in range(width)] for i in range(width)]
    residual = [row[:] for row in shrunk]
    factors: list[list[float]] = []
    for seed in range(min(max_rank, width)):
        v = [float(i == seed) + 0.1 for i in range(width)]
        for _ in range(80):
            nxt = [sum(residual[i][j] * v[j] for j in range(width)) for i in range(width)]
            norm = math.sqrt(sum(x * x for x in nxt))
            if norm <= 1e-14:
                break
            v = [x / norm for x in nxt]
        eigenvalue = sum(v[i] * sum(residual[i][j] * v[j] for j in range(width)) for i in range(width))
        if eigenvalue <= 1e-12:
            break
        factor = [math.sqrt(eigenvalue) * x for x in v]
        factors.append(factor)
        residual = [[residual[i][j] - factor[i] * factor[j] for j in range(width)] for i in range(width)]
    diagonal = [max(1e-9, residual[i][i]) for i in range(width)]
    approximation = [[(diagonal[i] if i == j else 0) + sum(f[i] * f[j] for f in factors)
                      for j in range(width)] for i in range(width)]
    relative_error = math.sqrt(sum((shrunk[i][j] - approximation[i][j])**2 for i in range(width) for j in range(width)) /
                               max(1e-24, sum(x*x for row in shrunk for x in row)))
    require(relative_error <= 0.35, "covariance: low-rank approximation unsupported; deterministic fallback")
    return {"n": len(samples), "effective_n": ess, "dimension": width,
            "conditional_digest": conditioning, "rank": len(factors),
            "diagonal": diagonal, "factors": factors,
            "relative_frobenius_error": relative_error, "condition_number": condition_number,
            "min_eigenvalue": spectral[0],
            "profile": "sample-centred-diag-shrink-0.25-rank2-v1"}


def linear_fit(rows: list[dict[str, Any]], fields: tuple[str, ...], ridge: float = 1e-5) -> list[float]:
    n = len(fields) + 1
    xtx = [[0.0] * n for _ in range(n)]
    xty = [0.0] * n
    for row in rows:
        x = [1.0] + [finite(row[key], key, -10, 10) for key in fields]
        y = finite(row["next_outcome"], "next_outcome", -10, 10)
        for i in range(n):
            xty[i] += x[i] * y
            for j in range(n):
                xtx[i][j] += x[i] * x[j]
    for i in range(1, n):
        xtx[i][i] += ridge
    for i in range(n):
        pivot = max(range(i, n), key=lambda j: abs(xtx[j][i]))
        require(abs(xtx[pivot][i]) > 1e-12, "closure: singular regression")
        xtx[i], xtx[pivot] = xtx[pivot], xtx[i]
        xty[i], xty[pivot] = xty[pivot], xty[i]
        scale = xtx[i][i]
        xtx[i] = [v / scale for v in xtx[i]]
        xty[i] /= scale
        for j in range(n):
            if i == j:
                continue
            factor = xtx[j][i]
            xtx[j] = [a - factor*b for a, b in zip(xtx[j], xtx[i])]
            xty[j] -= factor * xty[i]
    return xty


def closure_audit(rows: list[dict[str, Any]], min_relative_gain: float = 0.05) -> dict[str, Any]:
    """Held-out linear Markov-sufficiency probe; cannot prove true Markov closure."""
    require(0 < min_relative_gain < 1, "closure: invalid gain threshold")
    train = [row for row in rows if row.get("split") == "train"]
    future = [row for row in rows if row.get("split") == "future"]
    require(len(train) >= 40 and len(future) >= 30, "closure: insufficient train/future rows")
    require({row.get("group_id") for row in train}.isdisjoint({row.get("group_id") for row in future}),
            "closure: future-group leakage")
    # Restrict dimension intentionally: one registered scalar state and history probe.
    short = linear_fit(train, ("state",))
    long = linear_fit(train, ("state", "history"))
    def mse(params: list[float], extended: bool) -> float:
        return statistics.mean((finite(r["next_outcome"], "next_outcome", -10, 10) -
               sum(a*b for a, b in zip(params, [1., finite(r["state"], "state", -10, 10)] +
                   ([finite(r["history"], "history", -10, 10)] if extended else []))))**2 for r in future)
    compact_error, augmented_error = mse(short, False), mse(long, True)
    gain = (compact_error - augmented_error) / max(compact_error, 1e-10)
    return {"compact_mse": compact_error, "history_augmented_mse": augmented_error,
            "history_gain": gain, "probe_sufficient": gain <= min_relative_gain,
            "qualification": "restricted linear heldout probe only; not a Markov proof"}


def credit_audit(pairs: list[dict[str, Any]], objective: str, observer: str) -> dict[str, Any]:
    require(len(pairs) >= 30, "credit: at least 30 matched full-circuit interventions")
    groups: set[str] = set()
    deltas = []
    for row in pairs:
        group = nonempty(row.get("group_id"), "credit.group_id")
        require(group not in groups, "credit: repeated group")
        groups.add(group)
        require(row.get("objective_digest") == objective and row.get("observer_id") == observer,
                "credit: objective or independent observer mismatch")
        require(row.get("independent_full_circuit_outcome") is True and
                row.get("randomized_or_matched_intervention") is True,
                "credit: local reward is not full-circuit causal evidence")
        require(row.get("only_one_cell_changed") is True and
                nonempty(row.get("counterfactual_support_digest"), "credit.support_digest"),
                "credit: unsupported cross-cell attribution")
        v1 = finite(row.get("joint_utility"), "joint_utility", -1, 1)
        v0 = finite(row.get("reference_joint_utility"), "reference_joint_utility", -1, 1)
        deltas.append(v1 - v0)
    result = paired_lcb(deltas)
    result.update({"supported_positive_credit": result["lcb"] > 0,
                   "scope": "full-circuit matched intervention (not additive Cell reward)"})
    return result


def _check_manifest(manifest: dict[str, Any]) -> None:
    for key in ("objective_digest", "dataset_digest", "current_snapshot_digest", "next_snapshot_digest",
                "critic_digest", "policy_digest", "observer_id", "actor_id", "critic_owner_id",
                "hardware_digest", "semantic_plan_schema_digest", "independent_metric_digest"):
        nonempty(manifest.get(key), "manifest." + key)
    require(len({manifest["actor_id"], manifest["critic_owner_id"], manifest["observer_id"]}) == 3,
            "manifest: Actor, Critic and outcome observer must be independent owners")
    require(manifest["current_snapshot_digest"] != manifest["next_snapshot_digest"],
            "manifest: current-run parameter update forbidden")
    require(manifest.get("next_generation", 0) > manifest.get("current_generation", -1),
            "manifest: candidate must target a later generation")
    require(manifest.get("arms") == list(ARMS), "manifest: A0-A5 preregistration is required")
    require(manifest.get("outcome_metric_frozen") is True, "manifest: unfrozen external metric")
    require(manifest.get("split_assignment_frozen") is True, "manifest: unfrozen split")
    finite(manifest.get("max_policy_kl"), "manifest.max_policy_kl", 0, 0.1)
    finite(manifest.get("compute_budget_units"), "manifest.compute_budget_units", 1, 1e12)
    require(manifest.get("mode") in ("reference_fixture", "observed"), "manifest: unknown evidence mode")
    if manifest["mode"] == "observed":
        nonempty(manifest.get("observer_trust_root_digest"), "manifest.observer_trust_root_digest")


def _check_run(row: dict[str, Any], manifest: dict[str, Any]) -> None:
    for field, expected in (("objective_digest", manifest["objective_digest"]),
                            ("snapshot_digest", manifest["current_snapshot_digest"]),
                            ("critic_digest", manifest["critic_digest"]),
                            ("observer_id", manifest["observer_id"]),
                            ("hardware_digest", manifest["hardware_digest"])):
        require(row.get(field) == expected, "run: mismatched " + field)
    require(row.get("arm") in ARMS and row.get("split") in REQUIRED_SPLITS,
            "run: unsupported arm or split")
    require(row.get("evaluated_arm") == row["arm"],
            "run: unlabeled policy fallback cannot be counted as the requested arm")
    for field in ("episode_id", "group_id", "input_digest", "semantic_plan_digest",
                  "outcome_receipt_digest", "run_receipt_digest"):
        nonempty(row.get(field), "run." + field)
    require(row.get("admitted_compute_budget_units") == manifest["compute_budget_units"],
            "run: unequal precommitted compute budget across arms")
    finite(row.get("measured_compute_units"), "run.measured_compute_units", 0, manifest["compute_budget_units"])
    require(row.get("independent_observed_outcome") is True,
            "run: self-scored or unobserved reward")
    require(row.get("hard_constraints_ok") is True, "run: hard-constraint violation")
    for field in ("utility", "quality"):
        finite(row.get(field), "run." + field, -1, 1)
    for field in ("elapsed_ns", "decoder_ns", "controller_ns", "peak_rss_bytes"):
        finite(row.get(field), "run." + field, 0, 1e16)
    require(row["elapsed_ns"] >= max(row["decoder_ns"], row["controller_ns"]),
            "run: incompatible wall-clock and stage measurements")
    finite(row.get("policy_kl"), "run.policy_kl", 0, manifest["max_policy_kl"])
    consistency = row.get("consistency")
    require(isinstance(consistency, dict), "run: missing cross-modal independent check")
    require(consistency.get("semantic_plan_digest") == row["semantic_plan_digest"] and
            consistency.get("semantic_plan_schema_digest") == manifest["semantic_plan_schema_digest"],
            "run: inconsistent shared semantic plan")
    require(consistency.get("verifier_id") == manifest["observer_id"],
            "run: consistency verifier not independent observer")
    require(consistency.get("bidirectional_checked") is True and
            nonempty(consistency.get("evidence_digest"), "run.consistency.evidence_digest"),
            "run: bidirectional check absent")
    require(consistency.get("entity_violations") == 0 and consistency.get("timeline_violations") == 0,
            "run: cross-modal entity/timeline constraint failure")
    finite(consistency.get("semantic_agreement"), "run.consistency.semantic_agreement", 0.8, 1)
    modes = row.get("modalities")
    require(isinstance(modes, list) and set(modes) <= REQUIRED_MODALITIES and len(set(modes)) >= 2,
            "run: expected at least two unique output modalities")
    if "audio" in modes and "video" in modes:
        finite(consistency.get("av_sync_ms"), "run.consistency.av_sync_ms", 0, 80)


def evaluate(bundle: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic conservative A0-A5 qualification checks on supplied evidence.

    Success here is structural eligibility only; it cannot validate signature,
    model execution, causal inference or physical benchmark authenticity.
    """
    manifest = bundle.get("manifest")
    require(isinstance(manifest, dict), "bundle: missing manifest")
    _check_manifest(manifest)
    rows = bundle.get("runs")
    require(isinstance(rows, list), "bundle: runs must be a list")
    by: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    independent_groups: dict[tuple[str, str], str] = {}
    shared_inputs: dict[tuple[str, str], str] = {}
    shared_plans: dict[tuple[str, str], str] = {}
    for row in rows:
        require(isinstance(row, dict), "run: expected object")
        _check_run(row, manifest)
        key = (row["split"], row["episode_id"])
        require(row["arm"] not in by[key], "run: duplicated arm per episode")
        by[key][row["arm"]] = row
        group_key = (row["split"], row["episode_id"])
        group = independent_groups.setdefault(group_key, row["group_id"])
        require(group == row["group_id"], "run: mismatched independent-group identity across arms")
        original_input = shared_inputs.setdefault(group_key, row["input_digest"])
        require(original_input == row["input_digest"], "run: unequal multimodal input across ablation arms")
        original_plan = shared_plans.setdefault(group_key, row["semantic_plan_digest"])
        require(original_plan == row["semantic_plan_digest"], "run: unequal shared plan across ablation arms")
    for split in REQUIRED_SPLITS:
        eps = [key for key in by if key[0] == split]
        require(len(eps) >= 30, f"{split}: at least 30 paired episodes needed")
        require(len({independent_groups[e] for e in eps}) == len(eps),
                f"{split}: correlated group reuse violates independent pairing")
        require(all(set(by[e]) == set(ARMS) for e in eps), f"{split}: incomplete A0-A5 pairing")
    require(set(g for (split, _), g in independent_groups.items() if split == "future").isdisjoint(
            set(g for (split, _), g in independent_groups.items() if split == "retention")),
            "evaluation: future/retention group leakage")
    future = [by[e] for e in sorted(by) if e[0] == "future"]
    retention = [by[e] for e in sorted(by) if e[0] == "retention"]
    # Pre-registered seven contrasts: 5 vs A0, A5 vs A2 and A5 vs A4.
    # One-sided Bonferroni family alpha = 0.05/7.
    family_alpha = 0.05 / 7
    comparisons = {arm: paired_lcb([entry[arm]["utility"] - entry["A0"]["utility"] for entry in future], family_alpha)
                   for arm in ARMS[1:]}
    incremental = {"A5_vs_A2": paired_lcb([entry["A5"]["utility"] - entry["A2"]["utility"]
                                             for entry in future], family_alpha),
                   "A5_vs_A4": paired_lcb([entry["A5"]["utility"] - entry["A4"]["utility"]
                                             for entry in future], family_alpha)}
    old_task = paired_lcb([entry["A5"]["utility"] - entry["A0"]["utility"] for entry in retention])
    quality = paired_lcb([entry["A5"]["quality"] - entry["A0"]["quality"] for entry in future])
    net_savings = paired_lcb([(entry["A0"]["decoder_ns"] - entry["A5"]["decoder_ns"]) -
                              (entry["A5"]["controller_ns"] - entry["A0"]["controller_ns"])
                              for entry in future])
    wall_improvement = paired_lcb([entry["A0"]["elapsed_ns"] - entry["A5"]["elapsed_ns"] for entry in future])
    p95 = {arm: sorted(entry[arm]["elapsed_ns"] for entry in future)[math.ceil(.95 * len(future))-1]
           for arm in ARMS}
    peak_rss = {arm: max(entry[arm]["peak_rss_bytes"] for entry in future) for arm in ARMS}
    cov = low_rank_covariance(bundle.get("joint_trials", []),
                              int(manifest.get("joint_action_width", 0)))
    closure = closure_audit(bundle.get("closure_probe", []))
    credit = credit_audit(bundle.get("credit_pairs", []), manifest["objective_digest"], manifest["observer_id"])
    gates = {
        "independent_outcome_structure": True,
        "cross_modal_structural_checks": True,
        "conditional_covariance_support": cov["effective_n"] >= max(30, 8 * cov["dimension"]),
        "controller_net_compute_saving": net_savings["lcb"] > 0 and wall_improvement["lcb"] > 0,
        "a5_future_ndu_gain": comparisons["A5"]["lcb"] > 0,
        "a5_beats_router": incremental["A5_vs_A2"]["lcb"] > 0,
        "a5_beats_a4_portfolio": incremental["A5_vs_A4"]["lcb"] > 0,
        "heldout_quality_noninferiority": quality["lcb"] >= -0.02,
        "retention_noninferiority": old_task["lcb"] >= -0.02,
        "frozen_critic_next_snapshot": True,
        "no_history_dependence_detected": closure["probe_sufficient"],
        "supported_positive_full_circuit_credit": credit["supported_positive_credit"],
    }
    report = {
        "schema": "hepta.ndu-dmgp.reference-report.v1",
        "manifest_digest": digest(manifest),
        "evidence_mode": manifest["mode"],
        "comparisons_vs_A0": comparisons, "incremental_comparisons": incremental,
        "retention": old_task, "quality": quality, "net_compute_saving_ns": net_savings,
        "wall_latency_saving_ns": wall_improvement, "p95_elapsed_ns": p95,
        "peak_rss_bytes": peak_rss, "covariance": cov, "closure": closure, "credit": credit,
        "gates": gates,
        "reference_checks_passed": all(gates.values()),
        "production_qualified": False,
        "production_blockers": [
            "cryptographic observer/evidence verification against host trust root not implemented",
            "no production model or decoder execution performed by this reference evaluator",
            "causal attribution, BSDE numerical well-posedness and true Markov sufficiency not certified",
            "independent future-window selection/release requires learning.eval and final-use owner",
        ],
    }
    report["report_digest"] = digest(report)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="JSON qualification input with preregistered A0-A5 evidence")
    ap.add_argument("--output", help="write JSON report to this path")
    args = ap.parse_args()
    with open(args.bundle, encoding="utf-8") as source:
        bundle = json.load(source)
    try:
        report = evaluate(bundle)
    except (EvidenceError, KeyError, TypeError, OverflowError, ValueError) as exc:
        raise SystemExit(f"BLOCKED_NDU_DMGP_REFERENCE: {exc}") from exc
    output = json.dumps(report, sort_keys=True, indent=2, allow_nan=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as target:
            target.write(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
