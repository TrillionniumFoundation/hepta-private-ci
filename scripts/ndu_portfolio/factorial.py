"""Preregistered, clustered 2x2 evaluation; never authorizes model adoption.

This module validates structure and arithmetic; it cannot establish receipt
authenticity by reading a JSON declaration. No native receipt verifier is
implemented here, so every scientific admission gate always remains HOLD.
"""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

COSTS = ("encoder", "shared", "decoder", "critic", "planning", "codec", "failure", "retry", "sync")
RESEARCH = ("training", "search", "evaluation")
CELLS = {"A": ("ordinary", "light"), "B": ("ordinary", "ndu"),
         "C": ("hepta", "light"), "D": ("hepta", "ndu")}
BASELINES = ("initial", "tuned_fixed", "voi", "mpc")
FAMILIES = ("text_sufficient", "complementary", "asymmetric", "prepare_then_gain", "stop_worthwhile")
REGIMES = ("frozen", "joint")
# UTC episode timestamps and reported latency cover the same end-to-end scope.
# Allow at most one millisecond for serialization/measurement rounding, with no
# relative tolerance that could hide a large discrepancy on a long episode.
TIMING_TOLERANCE_SECONDS = 0.001


class InvalidEvidence(ValueError):
    """The supplied record cannot be evaluated without changing the estimand."""


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def protocol_digest(protocol):
    """Hash preregistered design; observed costs are separately retained evidence."""
    design = {**protocol, "profiles": {key: {k: v for k, v in profile.items()
              if k not in ("research_costs", "training_actual")}
              for key, profile in protocol["profiles"].items()}}
    return canonical_digest(design)


def _need(condition, message):
    if not condition:
        raise InvalidEvidence(message)


def _number(value, name, minimum=0):
    _need(type(value) in (int, float) and math.isfinite(value) and value >= minimum,
          f"invalid {name}")
    return float(value)


def _time(value):
    _need(isinstance(value, str), "missing timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidEvidence("invalid timestamp") from error
    _need(stamp.tzinfo is not None, "timestamp needs timezone")
    return stamp


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_protocol(protocol):
    """Validate a complete design independently of whether any run succeeded."""
    _need(isinstance(protocol, dict), "protocol must be an object")
    p = protocol
    _need(p.get("schema") == "ndu-factorial-v1", "unsupported protocol")
    _need(p.get("evidence_kind") in ("real", "synthetic"), "missing evidence_kind")
    _time(p.get("registered_at"))
    _need(p.get("weighting") == "equal_cluster", "unsupported weighting")
    _need(p.get("risk_profile_id") in ("nested-entropic-portfolio-v1", "population-entropic-v3"),
          "unknown or mixed risk profile")
    for field in ("dataset_digest", "objective_digest", "evaluator_digest", "measurement_digest"):
        _need(_hash(p.get(field)), f"missing {field}")
    _need(isinstance(p.get("cost_unit"), str) and p["cost_unit"], "missing cost unit")
    for field in ("cost_weight", "net_margin", "retention_margin"):
        _number(p.get(field), field)
    _need(0 < _number(p.get("alpha"), "alpha") < 0.5, "alpha outside (0,.5)")
    _need(type(p.get("min_clusters")) is int and p["min_clusters"] >= 20, "at least 20 independent clusters per split/cohort required")
    _need(type(p.get("bootstrap_samples")) is int and p["bootstrap_samples"] >= 10000,
          "at least 10000 bootstrap samples required for 20 contrasts")
    _need(type(p.get("bootstrap_seed")) is int, "missing bootstrap seed")
    _need(0 <= _number(p.get("failure_score"), "failure score") <= 1, "failure score > 1")
    _need(isinstance(p.get("seeds"), list) and p["seeds"] and
          all(type(s) is int for s in p["seeds"]) and len(set(p["seeds"])) == len(p["seeds"]),
          "invalid seeds")
    _need(isinstance(p.get("deployment_counts"), list) and p["deployment_counts"] and
          all(type(n) is int and n > 0 for n in p["deployment_counts"]), "invalid deployment counts")
    _need(p.get("arms") == list(CELLS) + list(BASELINES), "exact A/B/C/D plus four baselines required")
    tasks, seen, clusters, sources, source_clusters = {}, set(), {}, {}, {}
    _need(isinstance(p.get("tasks"), list) and p["tasks"], "missing task registry")
    for task in p["tasks"]:
        _need(isinstance(task, dict), "task must be an object")
        tid = task.get("task_id")
        _need(isinstance(tid, str) and tid and tid not in seen, "duplicate or invalid task")
        seen.add(tid)
        split, cohort = task.get("split"), task.get("cohort")
        _need(split in ("train", "validation", "test") and cohort in ("new", "retention"),
              "invalid task split/cohort")
        _need(task.get("family") in FAMILIES, "invalid task family")
        for name, grouping in (("cluster_id", clusters), ("source_group", sources)):
            value = task.get(name)
            _need(isinstance(value, str) and value, f"missing {name}")
            _need(grouping.get(value, split) == split, f"cross-split leakage: {name} {value}")
            grouping[value] = split
        source = task["source_group"]
        _need(source_clusters.get(source, task["cluster_id"]) == task["cluster_id"],
              "dependent source group relabelled as independent clusters")
        source_clusters[source] = task["cluster_id"]
        tasks[tid] = task
    for split in ("validation", "test"):
        new = [t for t in tasks.values() if t["split"] == split and t["cohort"] == "new"]
        _need({t["family"] for t in new} == set(FAMILIES), f"missing required {split} task family")
        _need(len({t["cluster_id"] for t in new}) >= p["min_clusters"], f"too few {split} clusters")
        old = [t for t in tasks.values() if t["split"] == split and t["cohort"] == "retention"]
        _need(len({t["cluster_id"] for t in old}) >= p["min_clusters"], f"too few {split} retention clusters")
    _need(any(t["split"] == "train" for t in tasks.values()), "training split must be registered")
    expected = {f"{r}:{a}" for r in REGIMES for a in p["arms"]}
    _need(set(p.get("profiles", {})) == expected, "missing/extra profile")
    unknown = []
    reference = None
    for key, profile in p["profiles"].items():
        _need(isinstance(profile, dict), "profile must be an object")
        regime, arm = key.split(":")
        for field in ("data_digest", "initial_content_digest", "model_digest", "policy_digest"):
            _need(_hash(profile.get(field)), f"missing profile {field}: {key}")
        _need(profile["data_digest"] == p["dataset_digest"], f"data mismatch: {key}")
        _need(profile.get("risk_profile_id") == p["risk_profile_id"], f"risk profile mismatch: {key}")
        _need(profile.get("objective_digest") == p["objective_digest"], f"objective mismatch: {key}")
        _need(profile.get("deployable") is True, f"undeployable arm: {key}")
        _need(type(profile.get("active_parameters")) is int and profile["active_parameters"] > 0,
              f"unknown capacity: {key}")
        budget = profile.get("budget", {})
        for field in ("train_compute", "train_examples", "search_trials", "episode_cost", "wall_seconds", "peak_bytes"):
            _number(budget.get(field), f"budget {field}: {key}", minimum=1e-30)
        if reference is None:
            reference = (profile["active_parameters"], budget)
        _need((profile["active_parameters"], budget) == reference, f"capacity/budget mismatch: {key}")
        if arm in CELLS:
            _need((profile.get("core"), profile.get("controller")) == CELLS[arm], f"wrong factorial cell: {key}")
        else:
            _need((profile.get("core"), profile.get("controller")) == ("ordinary", arm),
                  f"wrong registered comparator: {key}")
        actual = profile.get("training_actual", {})
        for field in ("train_compute", "train_examples", "search_trials"):
            value = actual.get(field)
            if value is None:
                unknown.append(f"{key}:training_actual:{field}")
            else:
                # An observed overrun is evidence to retain, not a malformed
                # design that may erase unsuccessful experimental expenditure.
                _number(value, field)
        _need(set(profile.get("research_costs", {})) == set(RESEARCH), f"research cost categories: {key}")
        for component, value in profile["research_costs"].items():
            if value is None:
                unknown.append(f"{key}:research:{component}")
            else:
                _number(value, f"{key}:{component}")
    # Within-core controller comparisons and both training regimes start from the same content.
    for pair in (("A", "B"), ("C", "D")):
        digests = {p["profiles"][f"{r}:{a}"]["initial_content_digest"] for r in REGIMES for a in pair}
        _need(len(digests) == 1, f"different initial content for pair {pair}")
    for pair in (("A", "B", *BASELINES), ("C", "D")):
        models = {p["profiles"][f"frozen:{a}"]["model_digest"] for a in pair}
        _need(len(models) == 1, f"frozen controllers must share the same content model: {pair}")
    return tasks, unknown


def _validate_rows(protocol, rows, splits):
    tasks, unknown = validate_protocol(protocol)
    _need(isinstance(rows, list), "rows must be an array")
    expected = {(t["split"], tid, seed, regime, arm) for tid, t in tasks.items()
                if t["split"] in splits for seed in protocol["seeds"]
                for regime in REGIMES for arm in protocol["arms"]}
    indexed, run_ids, attempt_ids = {}, set(), set()
    for row in rows:
        _need(isinstance(row, dict), "row must be an object")
        _need(row.get("split") in splits, "unexpected row split")
        key = (row["split"], row.get("task_id"), row.get("seed"), row.get("regime"), row.get("arm"))
        _need(key in expected and key not in indexed, f"extra or duplicate episode: {key}")
        _need(row.get("row_type") == "episode_terminal", "step rows cannot be independent samples")
        tid, regime, arm = key[1], key[3], key[4]
        profile = protocol["profiles"][f"{regime}:{arm}"]
        _need(row.get("cluster_id") == tasks[tid]["cluster_id"], "cluster identity mismatch")
        for field in ("model_digest", "policy_digest"):
            _need(row.get(field) == profile[field], f"episode {field} mismatch")
        _need(row.get("evaluator_digest") == protocol["evaluator_digest"], "evaluator identity mismatch")
        _need(row.get("risk_profile_id") == protocol["risk_profile_id"], "episode risk profile mismatch")
        _need(row.get("objective_digest") == protocol["objective_digest"], "episode objective mismatch")
        _need(row.get("measurement_digest") == protocol["measurement_digest"], "meter identity mismatch")
        _need(_hash(row.get("output_digest")), "missing output artifact digest")
        run_id = row.get("run_id")
        _need(isinstance(run_id, str) and run_id and run_id not in run_ids, "reused run identity")
        run_ids.add(run_id)
        attempts = row.get("attempt_ids")
        _need(isinstance(attempts, list) and attempts and all(isinstance(x, str) and x for x in attempts),
              "missing attempts")
        _need(len(set(attempts)) == len(attempts) and not set(attempts) & attempt_ids, "reused attempt identity")
        attempt_ids.update(attempts)
        failed = row.get("failed_attempts")
        _need(type(failed) is int and 0 <= failed <= len(attempts), "invalid failed attempt count")
        status = row.get("status")
        _need(status in ("success", "failed", "unresolved"), "invalid episode status")
        if status == "success":
            _need(failed < len(attempts), "successful episode has no successful attempt")
        if status == "failed":
            _need(failed == len(attempts), "failed episode lost an attempt")
        if status == "unresolved":
            unknown.append(f"{run_id}:unresolved")
        score = row.get("external_score")
        if score is None:
            unknown.append(f"{run_id}:external_score")
        else:
            _need(0 <= _number(score, "external score") <= 1, "score outside fixed [0,1] objective")
            if status == "failed":
                _need(score == protocol["failure_score"], "failed episode must retain fixed failure score")
        _need(set(row.get("costs", {})) == set(COSTS), "missing/extra cost component")
        for component, value in row["costs"].items():
            if value is None:
                unknown.append(f"{run_id}:{component}")
            else:
                _number(value, component)
        for field, limit in (("latency_seconds", "wall_seconds"), ("peak_bytes", "peak_bytes")):
            value = row.get(field)
            if value is None:
                unknown.append(f"{run_id}:{field}")
            else:
                _number(value, field)
        start, end = _time(row.get("started_at")), _time(row.get("finished_at"))
        _need(_time(protocol["registered_at"]) < start, "episode precedes preregistration")
        indexed[key] = row
    _need(set(indexed) == expected, f"incomplete preregistered matrix: missing {len(expected-set(indexed))}")
    return tasks, indexed, unknown


def _observation_findings(protocol, rows):
    """Retain complete observations while recording budget/timing violations."""
    budget_violations, integrity_violations = [], []
    for key, profile in protocol["profiles"].items():
        for field in ("train_compute", "train_examples", "search_trials"):
            value = profile.get("training_actual", {}).get(field)
            limit = profile["budget"][field]
            if value is not None and value > limit:
                budget_violations.append({"scope": "training", "profile": key,
                    "metric": field, "observed": value, "limit": limit})
    for row in rows:
        budget = protocol["profiles"][f'{row["regime"]}:{row["arm"]}']["budget"]
        costs = row["costs"].values()
        known_cost = sum(value for value in costs if value is not None)
        if known_cost > budget["episode_cost"]:
            budget_violations.append({"scope": "episode", "run_id": row["run_id"],
                "metric": "episode_cost", "observed": known_cost,
                "observed_is_lower_bound": any(value is None for value in costs),
                "limit": budget["episode_cost"]})
        for field, cap in (("latency_seconds", "wall_seconds"), ("peak_bytes", "peak_bytes")):
            value = row.get(field)
            if value is not None and value > budget[cap]:
                budget_violations.append({"scope": "episode", "run_id": row["run_id"],
                    "metric": field, "observed": value, "limit": budget[cap]})
        duration = (_time(row["finished_at"]) - _time(row["started_at"])).total_seconds()
        if duration < 0:
            integrity_violations.append({"scope": "episode", "run_id": row["run_id"],
                "kind": "timing", "code": "reversed_episode_time",
                "timestamp_span_seconds": duration})
            continue
        if duration > budget["wall_seconds"]:
            budget_violations.append({"scope": "episode", "run_id": row["run_id"],
                "metric": "timestamp_span_seconds", "observed": duration,
                "limit": budget["wall_seconds"]})
        latency = row.get("latency_seconds")
        if latency is not None and abs(duration - latency) > TIMING_TOLERANCE_SECONDS:
            integrity_violations.append({"scope": "episode", "run_id": row["run_id"],
                "kind": "timing", "code": "latency_timestamp_mismatch",
                "declared_latency_seconds": latency, "timestamp_span_seconds": duration,
                "absolute_difference_seconds": abs(duration - latency),
                "tolerance_seconds": TIMING_TOLERANCE_SECONDS})
    return budget_violations, integrity_violations


def _pre_evaluation_receipts(protocol):
    """Freeze completed training/search usage, including any missing values.

    Evaluation charges can be measured later. Already completed training/search
    receipts cannot be edited, or nulls filled, after the comparator was locked.
    A future native verifier would need an explicit, separately audited amendment
    procedure; no such procedure exists in this JSON arithmetic audit.
    """
    return {key: {
        "training_actual": {field: profile.get("training_actual", {}).get(field)
            for field in ("train_compute", "train_examples", "search_trials")},
        "research_costs": {field: profile["research_costs"][field]
            for field in ("training", "search")}}
        for key, profile in protocol["profiles"].items()}


def _utility(row, protocol, net=True):
    if row["external_score"] is None or any(v is None for v in row["costs"].values()):
        return None
    return row["external_score"] - (protocol["cost_weight"] * sum(row["costs"].values()) if net else 0)


def _cluster_values(protocol, tasks, indexed, split, cohort, terms, net=True):
    grouped = defaultdict(list)
    for tid, task in tasks.items():
        if task["split"] != split or task["cohort"] != cohort:
            continue
        for seed in protocol["seeds"]:
            components = [(_utility(indexed[(split, tid, seed, regime, arm)], protocol, net), weight)
                          for regime, arm, weight in terms]
            if any(value is None for value, _ in components):
                return None
            grouped[task["cluster_id"]].append(sum(value * weight for value, weight in components))
    return np.array([np.mean(grouped[key]) for key in sorted(grouped)], dtype=float)


def _selection(protocol, rows, locked_at):
    tasks, indexed, unknown = _validate_rows(protocol, rows, {"validation"})
    metadata_unknown = validate_protocol(protocol)[1]
    _need(not (set(unknown) - set(metadata_unknown)), "unknown validation costs or outcomes prevent comparator selection")
    lock = _time(locked_at)
    _need(all(_time(row["finished_at"]) < lock for row in rows), "selection lock must follow validation")
    choices, scores = {}, {}
    for regime in REGIMES:
        scores[regime] = {arm: float(_cluster_values(protocol, tasks, indexed, "validation", "new", [(regime, arm, 1)]).mean())
                          for arm in protocol["arms"] if arm != "D"}
        ordinary_pool = list(BASELINES) + ["A"]
        complete_pool = ordinary_pool + ["B", "C"]
        # Registered lexical tie break makes selection independent of row ordering.
        choices[regime] = {"ordinary": min(ordinary_pool, key=lambda a: (-scores[regime][a], a)),
                           "complete": min(complete_pool, key=lambda a: (-scores[regime][a], a))}
    body = {"schema": "ndu-comparator-lock-v1", "protocol_digest": protocol_digest(protocol),
            "validation_digest": canonical_digest(sorted(rows, key=lambda r: r["run_id"])),
            "pre_evaluation_receipts": _pre_evaluation_receipts(protocol),
            "locked_at": locked_at, "choices": choices, "validation_net_scores": scores}
    return {**body, "digest": canonical_digest(body)}


def select_comparators(protocol, validation_rows, locked_at):
    """Create the validation-only lock; save it before running the held-out matrix."""
    return _selection(protocol, validation_rows, locked_at)


def audit(protocol, rows, selection):
    """Return eligibility, all factorial contrasts and research-cost amortization."""
    _need(isinstance(selection, dict), "selection must be an object")
    tasks, indexed, unknown = _validate_rows(protocol, rows, {"validation", "test"})
    val = [row for row in rows if row["split"] == "validation"]
    expected = _selection(protocol, val, selection.get("locked_at"))
    _need(selection == expected, "comparator lock does not match frozen validation/protocol")
    _need(all(_time(row["started_at"]) > _time(selection["locked_at"]) for row in rows if row["split"] == "test"),
          "test observed before comparator lock")
    budget_violations, integrity_violations = _observation_findings(protocol, rows)
    definitions = {}
    for regime in REGIMES:
        for name, weights in (("B-A", {"B": 1, "A": -1}), ("D-C", {"D": 1, "C": -1}),
                              ("D-B", {"D": 1, "B": -1}), ("interaction", {"D": 1, "C": -1, "B": -1, "A": 1})):
            definitions[f"{regime}:{name}"] = ("new", [(regime, arm, w) for arm, w in weights.items()], True, protocol["net_margin"])
        for arm, pool in (("B", "ordinary"), ("D", "complete")):
            baseline = selection["choices"][regime][pool]
            definitions[f"{regime}:{arm}-strongest"] = ("new", [(regime, arm, 1), (regime, baseline, -1)], True, protocol["net_margin"])
    for arm in CELLS:
        terms = [("joint", arm, 1), ("frozen", arm, -1)]
        definitions[f"joint-frozen:{arm}"] = ("new", terms, True, protocol["net_margin"])
        definitions[f"retention:{arm}"] = ("retention", terms, False, -protocol["retention_margin"])
    rng, contrasts = np.random.default_rng(protocol["bootstrap_seed"]), {}
    # Bonferroni two-sided percentile intervals cover the complete declared contrast family.
    tail = protocol["alpha"] / (2 * len(definitions))
    for name, (cohort, terms, net, threshold) in definitions.items():
        values = _cluster_values(protocol, tasks, indexed, "test", cohort, terms, net)
        if values is None:
            contrasts[name] = {"estimate": None, "ci": None, "gate": "HOLD"}
            continue
        boot = np.empty(protocol["bootstrap_samples"])
        for start in range(0, len(boot), 500):
            count = min(500, len(boot) - start)
            boot[start:start+count] = values[rng.integers(0, len(values), (count, len(values)))].mean(axis=1)
        lower, upper = np.quantile(boot, [tail, 1-tail])
        passed = lower >= threshold if name.startswith("retention:") else lower > threshold
        contrasts[name] = {"estimate": float(values.mean()), "ci": [float(lower), float(upper)],
                           "clusters": len(values), "threshold": threshold,
                           "gate": "PASS" if passed else "NOT_ESTABLISHED"}
    costs, amortized = {}, {}
    for key, profile in protocol["profiles"].items():
        values = profile["research_costs"]
        costs[key] = {"components": values, "total": None if any(v is None for v in values.values()) else sum(values.values())}
    for regime in REGIMES:
        baseline = selection["choices"][regime]["complete"]
        delta = contrasts[f"{regime}:D-strongest"].get("estimate")
        d, b = costs[f"{regime}:D"]["total"], costs[f"{regime}:{baseline}"]["total"]
        amortized[regime] = {str(n): None if None in (delta, d, b) else delta - protocol["cost_weight"] * (d-b)/n
                            for n in protocol["deployment_counts"]}
    amortized_intervals = {}
    for regime in REGIMES:
        ci = contrasts[f"{regime}:D-strongest"].get("ci")
        baseline = selection["choices"][regime]["complete"]
        d, b = costs[f"{regime}:D"]["total"], costs[f"{regime}:{baseline}"]["total"]
        amortized_intervals[regime] = {str(n): None if ci is None or d is None or b is None else
            [bound - protocol["cost_weight"] * (d-b)/n for bound in ci]
            for n in protocol["deployment_counts"]}
    # JSON assertions never establish native authenticity. Conditional results
    # describe what these numbers would imply only after independent verification.
    conditional_blocked = bool(unknown or budget_violations or integrity_violations
                               or protocol["evidence_kind"] != "real")
    for contrast in contrasts.values():
        contrast["statistical_gate"] = contrast["gate"]
        contrast["conditional_gate_on_verified_receipts"] = (
            "HOLD" if conditional_blocked else contrast["statistical_gate"])
        contrast["gate"] = "HOLD"
    gates = {"frozen_control": ["frozen:B-strongest", "frozen:D-strongest"],
             "joint_training": ["joint-frozen:D", "joint:D-strongest", "retention:D"],
             "hepta_increment": ["joint:D-B"]}
    conditional = {name: ("HOLD" if conditional_blocked else
                         "PASS" if all(contrasts[c]["statistical_gate"] == "PASS" for c in members)
                         else "NOT_ESTABLISHED") for name, members in gates.items()}
    scientific = {name: "HOLD" for name in gates}
    return {"schema": "ndu-factorial-audit-v1", "protocol_digest": protocol_digest(protocol),
            "observed_protocol_digest": canonical_digest(protocol),
            "episodes_digest": canonical_digest(sorted(rows, key=lambda r: r["run_id"])),
            "selection_digest": selection["digest"], "evidence_kind": protocol["evidence_kind"],
            "matrix_complete": True, "episode_count": len(rows),
            "failed_episodes": sum(row["status"] == "failed" for row in rows),
            "failed_attempts": sum(row["failed_attempts"] for row in rows),
            "unknowns": sorted(set(unknown)), "comparators": selection["choices"],
            "budget_violations": budget_violations, "integrity_violations": integrity_violations,
            "timing_check": {"scope": "end-to-end episode including failures, retries and synchronization",
                             "absolute_tolerance_seconds": TIMING_TOLERANCE_SECONDS,
                             "relative_tolerance": 0},
            "contrasts": contrasts, "multiplicity": {"method": "Bonferroni cluster percentile bootstrap",
            "family_size": len(definitions), "alpha": protocol["alpha"], "tail": tail},
            "scientific_gates": scientific,
            "conditional_gates_on_verified_receipts": conditional,
            "native_receipt_verification": {"verified": False, "status": "NOT_IMPLEMENTED",
                "required_for_scientific_admission": True,
                "reason": "A self-reported real flag and matching JSON hashes do not verify native evidence."},
            "research_costs": costs,
            "inference_cost_ledger": cost_ledger(rows),
            "study_research_total": None if any(c["total"] is None for c in costs.values()) else sum(c["total"] for c in costs.values()),
            "D_minus_strongest_amortized_at_deployments": amortized,
            "D_minus_strongest_amortized_ci_at_deployments": amortized_intervals,
            "adoption_authorized": False,
            "scope": "Receipt structure and arithmetic only; independent provenance/authenticity and native-owner verification remain caller obligations."}


def cost_ledger(rows):
    """Full observed deployment ledger; any unknown leaves its subtotal null."""
    groups = defaultdict(list)
    for row in rows:
        groups[f'{row["split"]}:{row["regime"]}:{row["arm"]}'].append(row)
    groups["all_observed_episodes"] = rows
    result = {}
    for key, group in sorted(groups.items()):
        components = {}
        for component in COSTS:
            values = [r["costs"][component] for r in group]
            missing = sum(v is None for v in values)
            components[component] = {"total": None if missing else sum(values),
                                     "unknown_episodes": missing}
        totals = [v["total"] for v in components.values()]
        result[key] = {
            "episodes": len(group), "attempts": sum(len(r["attempt_ids"]) for r in group),
            "failed_episodes": sum(r["status"] == "failed" for r in group),
            "failed_attempts": sum(r["failed_attempts"] for r in group),
            "components": components,
            "total": None if any(v is None for v in totals) else sum(totals)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--rows", required=True, type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--locked-at")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        protocol, rows = json.loads(args.protocol.read_text()), json.loads(args.rows.read_text())
        if args.select:
            result = select_comparators(protocol, rows, args.locked_at)
        else:
            _need(args.selection is not None, "--selection required for held-out audit")
            result = audit(protocol, rows, json.loads(args.selection.read_text()))
    except (InvalidEvidence, KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError) as error:
        result = {"schema": "ndu-factorial-audit-v1", "matrix_complete": False,
                  "scientific_gates": {"all": "HOLD"}, "adoption_authorized": False,
                  "error": str(error)}
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        raise SystemExit(2) from error
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
