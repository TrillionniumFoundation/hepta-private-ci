"""Shared V3 reporting primitives with explicit tie and retention semantics."""

import itertools
import math

import numpy as np


def rank_scores(candidate_ids, predicted, actual, *, tie_tolerance):
    """Compare costs on one common objective/horizon over executed candidates.

    Input order is the frozen tie-break order. The executed minimum is an
    offline finite-candidate diagnostic, never a controller selection rule.
    """
    ids = list(candidate_ids)
    predicted, actual = np.asarray(predicted, dtype=float), np.asarray(actual, dtype=float)
    if (len(ids) < 2 or len(set(ids)) != len(ids) or any(not isinstance(key, str) for key in ids)
            or predicted.shape != (len(ids),) or actual.shape != predicted.shape
            or not np.isfinite(predicted).all() or not np.isfinite(actual).all()
            or not np.isfinite(tie_tolerance) or tie_tolerance < 0):
        raise ValueError("distinct executed candidates and finite common scores required")
    counts = {key: 0 for key in ("concordant", "discordant", "predicted_only_tie",
                                  "actual_only_tie", "both_tied")}
    pairs = []
    for left, right in itertools.combinations(range(len(ids)), 2):
        delta_p, delta_a = predicted[left] - predicted[right], actual[left] - actual[right]
        p = 0 if abs(delta_p) <= tie_tolerance else int(np.sign(delta_p))
        a = 0 if abs(delta_a) <= tie_tolerance else int(np.sign(delta_a))
        if not p and not a: kind = "both_tied"
        elif not p: kind = "predicted_only_tie"
        elif not a: kind = "actual_only_tie"
        else: kind = "concordant" if p == a else "discordant"
        counts[kind] += 1
        pairs.append({"left": ids[left], "right": ids[right], "predicted_difference": float(delta_p),
                      "actual_difference": float(delta_a), "classification": kind})
    strict = counts["concordant"] + counts["discordant"]
    denominator = math.sqrt((strict + counts["predicted_only_tie"])
                            * (strict + counts["actual_only_tie"]))
    predicted_min = float(predicted.min())
    tied = np.flatnonzero(predicted <= predicted_min + tie_tolerance)
    selected = int(tied[0])
    oracle = int(np.argmin(actual))
    regret = actual - actual[oracle]
    return {"candidate_ids": ids, "candidate_count": len(ids), "pair_count": len(pairs),
            "tie_tolerance": float(tie_tolerance), "pair_counts": counts,
            "strict_pairs": strict, "strict_pair_coverage": strict / len(pairs),
            "strict_order_agreement": counts["concordant"] / strict if strict else None,
            "kendall_tau_b": ((counts["concordant"] - counts["discordant"]) / denominator
                              if denominator else None),
            "predicted_top": ids[selected], "predicted_tied_minima": [ids[i] for i in tied],
            "executed_candidate_oracle": ids[oracle],
            "predicted_top_actual_regret": float(regret[selected]),
            "worst_predicted_tie_actual_regret": float(regret[tied].max()),
            "scope": "fixed executed candidate set; diagnostic hindsight minimum only",
            "pairs": pairs}


def path_retention(losses, warmup_losses, *, tolerance):
    """Future-step maximum of DATASET-MEAN excess; never mean individual maxima."""
    values, initial = np.asarray(losses, dtype=float), np.asarray(warmup_losses, dtype=float)
    if (values.ndim != 2 or len(values) < 2 or initial.shape != (values.shape[1],)
            or values.shape[1] == 0 or not np.isfinite(values).all() or not np.isfinite(initial).all()
            or not np.isfinite(tolerance) or tolerance < 0):
        raise ValueError("finite time-by-source loss trace and warmup anchor required")
    excess = (values - initial).mean(axis=1)
    future = excess[1:]
    return {"initial_mean_nll_excess": float(excess[0]),
            "terminal_mean_nll_excess": float(excess[-1]),
            "maximum_whole_path_mean_nll_excess": float(excess.max()),
            "maximum_future_mean_nll_excess": float(future.max()),
            "mean_nll_excess_by_step": excess.tolist(),
            "initial_probe_style_feasible": bool(excess[0] <= tolerance),
            "whole_path_probe_style_feasible": bool(np.all(excess <= tolerance)),
            "future_violation_steps": [int(k + 1) for k in np.flatnonzero(future > tolerance)],
            "future_probe_style_feasible": bool(np.all(future <= tolerance)),
            "tolerance": float(tolerance), "rows": int(values.shape[1])}
