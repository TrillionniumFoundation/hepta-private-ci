"""Frozen-feature cosine controls; no Encoder, Reader or Head optimization.

The zero-threshold score has no fitted parameter. A SECOND, explicit control
fits one scalar threshold on registered TRAIN pairs only. Neither is a calibrated
probability, certified evidence sufficiency, or production call-skipping policy.
"""
from __future__ import annotations
from copy import deepcopy
import math
import re

import five_causal_experiments as c

PROFILE = "hepta.cell.saved-feature-similarity-control.v1"
ORDER = ("aa", "ab", "ba", "bb")
FLAGS = ("positive_interaction", "both_question_rankings", "both_evidence_rankings", "all_four_threshold_directions")
ORIGINS = {
    "heads": {"run": 38526481788, "source": "592b5b645ada09c335f942ce7ca11561d5eb2cf1",
              "path": ".github/workflows/hepta-shared-question-gate.yml",
              "artifact": "hepta-shared-question-gate-development"},
    "crossed": {"run": 38526874475, "source": "9da0908298f26fab8173a7ffa04807c9ab179ca7",
                "path": ".github/workflows/hepta-shared-gate-crossed.yml",
                "artifact": "hepta-saved-gate-crossed-evidence-check-disposition"},
}


def artifact_origin(role, run, artifacts):
    c.require(role in ORIGINS and isinstance(run, dict) and isinstance(artifacts, dict), "known authenticated origin required")
    expected = ORIGINS[role]
    c.require(type(run.get("id")) is int and run["id"] == expected["run"]
              and run.get("head_sha") == expected["source"] and run.get("path") == expected["path"]
              and type(run.get("run_attempt")) is int and run["run_attempt"] >= 1
              and all(run.get(k, {}).get("full_name") == "TrillionniumFoundation/hepta-private-ci"
                      for k in ("repository", "head_repository")), "wrong fixed execution origin")
    record = dict(expected, observed_status=run.get("status"), observed_conclusion=run.get("conclusion"),
                  run_attempt=run["run_attempt"], metadata_sha256=c.digest([run, artifacts]))
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return record | {"ready": False, "status": "deferred_fixed_origin_not_successful"}
    rows = artifacts.get("artifacts")
    c.require(isinstance(rows, list) and type(artifacts.get("total_count")) is int
              and artifacts["total_count"] == len(rows) <= 100
              and all(isinstance(a, dict) for a in rows), "incomplete artifact page")
    matches = [a for a in rows if a.get("name") == expected["artifact"]]
    c.require(len(matches) == 1, "exactly one named artifact required")
    a = matches[0]
    c.require(type(a.get("id")) is int and a["id"] > 0 and a.get("expired") is False
              and type(a.get("size_in_bytes")) is int and a["size_in_bytes"] > 0
              and re.fullmatch(r"sha256:[0-9a-f]{64}", str(a.get("digest"))) is not None
              and type(a.get("workflow_run", {}).get("id")) is int
              and a["workflow_run"]["id"] == expected["run"]
              and a["workflow_run"].get("head_sha") == expected["source"], "artifact bytes/origin not bound")
    return record | {"ready": True, "artifact_id": a["id"], "artifact_sha256": a["digest"][7:],
                     "status": "ready_for_saved_feature_readout"}


def dependency(head_run, head_artifacts, cross_run, cross_artifacts):
    origins = {"heads": artifact_origin("heads", head_run, head_artifacts),
               "crossed": artifact_origin("crossed", cross_run, cross_artifacts)}
    return {"schema": PROFILE + ".dependency", "origins": origins,
            "ready": all(x["ready"] for x in origins.values()), "analysis_completed": False,
            "new_pretrained_model_loads": 0, "production_accepted": False}


def cosine(question, evidence):
    """FP64 scalar arithmetic on frozen vectors; no corpus-fitted normalization.

    Scale before squaring to avoid overflow/underflow. Clipping only removes
    final floating-point overshoot of [-1,1], never clips a failed feature.
    """
    c.require(isinstance(question, (list, tuple)) and isinstance(evidence, (list, tuple))
              and 1 <= len(question) == len(evidence) <= 8192, "vector geometry")
    scaled = []
    for values in (question, evidence):
        c.require(all(c.finite(x, -1e308, 1e308) for x in values), "nonfinite/boolean feature")
        scale = max(abs(x) for x in values)
        c.require(scale > 0, "zero feature")
        v = [float(x / scale) for x in values]
        norm = math.sqrt(math.fsum(x*x for x in v))
        scaled.append([x/norm for x in v])
    score = math.fsum(a*b for a, b in zip(*scaled))
    c.require(math.isfinite(score) and -1.000000000001 <= score <= 1.000000000001, "invalid cosine reduction")
    return min(1.0, max(-1.0, score))


def indexed(rows):
    c.require(isinstance(rows, list) and all(isinstance(r, dict) and c.sha(r.get("pair_id")) for r in rows), "invalid pair inventory")
    out = {r["pair_id"]: r for r in rows}
    c.require(len(out) == len(rows), "duplicate pair")
    return out


def score_pairs(units, features, *, split, roles):
    c.require(split in ("train", "select") and roles in (("matched", "mismatched"), ORDER), "unregistered score geometry")
    indexed(units)
    before = c.digest(units)
    rows = []
    for u in units:
        c.require(u["split"] == split, "partition changed")
        row = {"pair_id": u["pair_id"], "status": "unavailable", "logits": None}
        if u["status"] == "available":
            c.require(tuple(v["role"] for v in u["variants"]) == roles, "variant order changed")
            row.update(status="succeeded", logits=[cosine(features[v["question_key"]], features[v["evidence_key"]]) for v in u["variants"]])
        else:
            c.require(u["status"] in ("unavailable_donor", "unavailable_reference_or_donor") and not u["variants"], "unregistered missingness")
        rows.append(row)
    c.require(c.digest(units) == before, "source plan changed")
    return rows


def fit_train_threshold(units, rows):
    """One scalar fit, not zero-fitting. SELECT/TEST never enters this function.

    Minimize strict matched-positive/mismatched-negative classification errors.
    Search only TRAIN midpoint candidates plus outside endpoints. Break ties by
    abs(threshold), then numerical threshold. Never select on SELECT performance.
    """
    plan, values = indexed(units), indexed(rows)
    c.require(plan and set(plan) == set(values) and all(u["split"] == "train" for u in units), "TRAIN-only complete threshold cohort required")
    pairs = []
    for key, u in plan.items():
        row = values[key]
        if u["status"] != "available":
            c.require(row["status"] == "unavailable" and row["logits"] is None, "missing threshold row imputed")
            continue
        s = row["logits"]
        c.require(row["status"] == "succeeded" and isinstance(s, list) and len(s) == 2
                  and all(c.finite(x, -1, 1) for x in s), "threshold scores invalid")
        pairs.append(s)
    c.require(pairs, "no TRAIN scores for scalar fit")
    unique = sorted(set(x for pair in pairs for x in pair))
    candidates = {-2.0, 2.0}
    if 0.0 not in unique:
        candidates.add(0.0)
    for a, b in zip(unique, unique[1:]):
        middle = a + (b-a)/2.0
        if a < middle < b:
            candidates.add(middle)
    table = [{"threshold": t, "strict_errors": sum(int(a <= t) + int(b >= t) for a, b in pairs)} for t in sorted(candidates)]
    best = min(table, key=lambda x: (x["strict_errors"], abs(x["threshold"]), x["threshold"]))
    return {"schema": PROFILE + ".train-threshold", **best, "candidate_scores": table,
            "planned_train_pairs": len(plan), "scored_train_pairs": len(pairs),
            "unavailable_train_pairs": len(plan)-len(pairs), "train_error_fraction": best["strict_errors"]/(2*len(pairs)),
            "train_inputs_sha256": c.digest(units), "train_scores_sha256": c.digest(rows),
            "neural_parameters_fitted": 0, "scalar_parameters_fitted": 1,
            "select_access": False, "probability_calibrated": False, "production_accepted": False}


def shift(rows, threshold):
    c.require(c.finite(threshold, -2, 2), "invalid frozen threshold")
    indexed(rows)
    result = deepcopy(rows)
    for row in result:
        if row["status"] == "unavailable":
            c.require(row["logits"] is None, "missing score imputed")
        else:
            c.require(row["status"] == "succeeded" and isinstance(row["logits"], list)
                      and len(row["logits"]) in (2, 4) and all(c.finite(x, -1, 1) for x in row["logits"]), "invalid raw cosine scores")
            row["logits"] = [x-threshold for x in row["logits"]]
    return result


def compare_flags(units, candidate, baseline):
    """Paired binary outcomes, never subtract incomparable logit scales.

    Flags are derived by the existing crossed-evidence readout in the driver.
    No confidence bound: original families/donors/seeds are not independent.
    """
    plan, a, b = indexed(units), indexed(candidate), indexed(baseline)
    c.require(plan and set(plan) == set(a) == set(b), "paired denominator changed")
    result = {k: {"candidate_only": 0, "baseline_only": 0, "both": 0, "neither": 0} for k in FLAGS}
    observed = 0
    for key, unit in plan.items():
        left, right = a[key], b[key]
        if unit["status"] != "available":
            c.require(all(row["status"] == "unavailable" and row["flags"] is None for row in (left, right)), "missing contrast imputed")
            continue
        for row in (left, right):
            c.require(row["status"] == "succeeded" and isinstance(row["flags"], dict)
                      and set(row["flags"]) == set(FLAGS) and all(type(x) is bool for x in row["flags"].values()), "invalid binary comparison")
        observed += 1
        for k in FLAGS:
            x, y = left["flags"][k], right["flags"][k]
            label = "both" if x and y else "candidate_only" if x else "baseline_only" if y else "neither"
            result[k][label] += 1
    return {"planned_pairs": len(plan), "observed_pairs": observed, "unavailable_pairs": len(plan)-observed,
            "criteria": result, "raw_score_difference_reported": False,
            "confidence_interval": None, "semantic_accuracy": None, "production_accepted": False}
