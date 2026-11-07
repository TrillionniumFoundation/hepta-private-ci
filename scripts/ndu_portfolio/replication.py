"""Independent fit identities and crossed fit/source inference around factorial v1.

This is an arithmetic evidence auditor, not an owner/evaluator authenticator.
Planning uses a declared crossed random-effects approximation; the independently
resampled fit/source percentile intervals are approximate, not exact coverage.
See Owen and Eckles (2012), https://doi.org/10.1214/12-AOAS547.
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np

from . import factorial as f

SCHEMA = "ndu-replicated-factorial-v1"
FAMILY_SIZE = 20
PHASES = ("training", "search", "evaluation")


def design_digest(protocol):
    """Pin common opportunities and tasks before fit-specific artifacts exist."""
    fitted = {"policy_digest", "training_actual", "research_costs"}
    return f.canonical_digest({**protocol, "profiles": {
        key: {k: v for k, v in profile.items() if k not in fitted
              and (k != "model_digest" or key.startswith("frozen:"))}
        for key, profile in protocol["profiles"].items()}})


def validate_plan(plan, expected_plan_digest):
    """Check an externally pinned roster and prospective power assumptions.

    For Y[fit,source] = mu + a[fit] + b[source] + e[fit,source],
    Var(mean) = vf/R + vs/G + vi/(R*G). Variances are predeclared conservative
    bounds for the complete contrast family, not estimates from confirmation.
    This calculation does not authenticate the pilot or guarantee actual power.
    """
    f._need(f._hash(expected_plan_digest) and
            f.canonical_digest(plan) == expected_plan_digest, "external plan pin differs")
    f._need(plan.get("schema") == SCHEMA, "unsupported replicated plan")
    registered = f._time(plan.get("registered_at"))
    f._need(f._hash(plan.get("design_digest")), "missing common design digest")
    fits = plan.get("fits")
    f._need(isinstance(fits, list) and len(fits) >= 2, "independent fits required")
    ids, seeds = set(), set()
    for fit in fits:
        f._need(set(fit) == {"fit_id", "training_seed"}, "invalid planned fit")
        identity, seed = fit["fit_id"], fit["training_seed"]
        f._need(isinstance(identity, str) and identity and identity not in ids, "duplicate fit id")
        f._need(type(seed) is int and seed not in seeds, "duplicate/invalid training seed")
        ids.add(identity); seeds.add(seed)
    power = plan.get("power", {})
    f._need(power.get("method") == "crossed-normal-planning-v1", "unknown power method")
    f._need(power.get("family_size") == FAMILY_SIZE, "all 20 contrasts must be planned")
    alpha, desired = power.get("alpha"), power.get("power")
    f._need(type(alpha) in (int, float) and 0 < alpha < .5, "invalid planning alpha")
    f._need(type(desired) in (int, float) and .5 < desired < 1, "invalid planning power")
    effect = f._number(power.get("effect_above_margin"), "effect above decision margin", 1e-30)
    vf, vs, vi = [f._number(power.get(k), k) for k in
                  ("fit_variance", "source_variance", "interaction_variance")]
    f._need(vf + vs + vi > 0, "zero variance is not a prospective power justification")
    f._need(f._hash(power.get("pilot_sha256")), "missing pilot binding")
    f._need(f._time(power.get("pilot_frozen_at")) < registered, "pilot must precede registration")
    for key in ("pilot_source_groups", "pilot_fit_run_ids"):
        values = power.get(key)
        f._need(isinstance(values, list) and values and
                all(isinstance(x, str) and x for x in values) and len(set(values)) == len(values),
                f"missing/duplicate {key}")
    draws = plan.get("bootstrap_samples")
    f._need(type(draws) is int and draws >= 10000, "at least 10000 bootstrap samples required")
    f._need(type(plan.get("bootstrap_seed")) is int, "invalid bootstrap seed")
    z = NormalDist().inv_cdf(1 - alpha / (2 * FAMILY_SIZE)) + NormalDist().inv_cdf(desired)
    residual = (effect / z) ** 2 - vf / len(fits)
    required = None if residual <= 0 else max(20, math.ceil((vs + vi / len(fits)) / residual))
    return {"independent_fits": len(fits), "required_source_groups_per_test_cohort": required,
            "status": "MORE_INDEPENDENT_FITS_REQUIRED" if required is None else "PLANNED_UNDER_ASSUMPTIONS",
            "variance_of_mean": "vf/R + vs/G + vi/(R*G)", "family_size": FAMILY_SIZE,
            "method": power["method"], "power": desired, "alpha": alpha,
            "pilot_authentication_verified": False, "power_is_guaranteed": False}


def _attempts(record, seen_attempts, registered):
    """Retain every training/search/evaluation attempt, including unknown costs."""
    attempts = record.get("research_attempts")
    f._need(isinstance(attempts, list) and attempts, "missing research attempt inventory")
    costs, unknown, counts, incomplete_keys = defaultdict(float), [], defaultdict(int), set()
    for attempt in attempts:
        identity = attempt.get("attempt_id")
        f._need(isinstance(identity, str) and identity and identity not in seen_attempts,
                "reused research attempt identity")
        seen_attempts.add(identity)
        phase, profile = attempt.get("phase"), attempt.get("profile")
        f._need(phase in PHASES and profile in {f"{r}:{a}" for r in f.REGIMES
                for a in (*f.CELLS, *f.BASELINES)}, "invalid research phase/profile")
        f._need(attempt.get("status") in ("success", "failed", "unresolved"), "invalid research attempt status")
        f._need(f._hash(attempt.get("receipt_digest")), "missing research receipt digest")
        start = f._time(attempt.get("started_at"))
        f._need(registered < start, "research attempt outside prospective chronology")
        if attempt["status"] == "unresolved" and attempt.get("finished_at") is None:
            pass  # No fabricated terminal time for an unreconciled original job.
        else:
            f._need(start <= f._time(attempt.get("finished_at")), "research attempt reversed chronology")
        cost = attempt.get("cost")
        key = f"{profile}:{phase}"
        counts[key] += 1
        if cost is None or attempt["status"] == "unresolved":
            unknown.append(identity)
            incomplete_keys.add(key)
        if cost is not None:
            costs[key] += f._number(cost, "research attempt cost")
    return costs, counts, unknown, incomplete_keys


def _definitions(protocol, selection):
    definitions = {}
    for regime in f.REGIMES:
        for name, terms in (("B-A", {"B": 1, "A": -1}), ("D-C", {"D": 1, "C": -1}),
                            ("D-B", {"D": 1, "B": -1}),
                            ("interaction", {"D": 1, "C": -1, "B": -1, "A": 1})):
            definitions[f"{regime}:{name}"] = ("new", [(regime, a, w) for a, w in terms.items()], True,
                                                protocol["net_margin"])
        for arm, pool in (("B", "ordinary"), ("D", "complete")):
            baseline = selection["choices"][regime][pool]
            definitions[f"{regime}:{arm}-strongest"] = (
                "new", [(regime, arm, 1), (regime, baseline, -1)], True, protocol["net_margin"])
    for arm in f.CELLS:
        terms = [("joint", arm, 1), ("frozen", arm, -1)]
        definitions[f"joint-frozen:{arm}"] = ("new", terms, True, protocol["net_margin"])
        definitions[f"retention:{arm}"] = ("retention", terms, False, -protocol["retention_margin"])
    return definitions


def crossed_interval(values, *, draws, seed, alpha):
    """Resample paired training fits and source groups independently.

    Episode randomness has already been averaged within a source group. Arms and
    regimes have already been contrasted within the same fit/source cell.
    """
    values = np.asarray(values, dtype=float)
    f._need(values.ndim == 2 and min(values.shape) >= 2 and np.isfinite(values).all(),
            "crossed inference needs a complete finite fit/source array")
    rng = np.random.default_rng(seed)
    r, g = values.shape
    boot = np.empty(draws)
    for start in range(0, draws, 250):
        n = min(250, draws - start)
        fit_weights = rng.multinomial(r, np.full(r, 1 / r), size=n) / r
        group_weights = rng.multinomial(g, np.full(g, 1 / g), size=n) / g
        boot[start:start+n] = np.einsum("bf,fg,bg->b", fit_weights, values, group_weights)
    tail = alpha / (2 * FAMILY_SIZE)
    return [float(x) for x in np.quantile(boot, [tail, 1 - tail])]


def seal_fit(record):
    """Bind pre-evaluation attempts; the native owner must authenticate this lock."""
    body = {key: record[key] for key in ("fit_id", "training_seed", "fit_run_id", "training_receipt_digest")}
    body.update(selection_digest=record["selection"]["digest"],
                pre_evaluation_attempts=sorted((a for a in record["research_attempts"]
                    if a["phase"] in ("training", "search")), key=lambda a: a["attempt_id"]))
    return {**body, "digest": f.canonical_digest(body)}


def _evaluation_coverage(rows, costs, counts, incomplete_keys):
    """An observed episode needs an evaluation receipt, including partial fits."""
    lower_bounds, unknown = defaultdict(float), []
    for row in rows:
        f._need(isinstance(row, dict) and isinstance(row.get("costs"), dict)
                and set(row["costs"]) == set(f.COSTS), "malformed retained episode costs")
        key = f'{row.get("regime")}:{row.get("arm")}:evaluation'
        for value in row["costs"].values():
            if value is None:
                unknown.append(f"{key}:unknown_episode_cost")
                incomplete_keys.add(key)
            else:
                lower_bounds[key] += f._number(value, "retained episode cost")
    for key, lower in lower_bounds.items():
        if not counts[key] or key in incomplete_keys or costs[key] + 1e-9 < lower:
            unknown.append(f"{key}:evaluation_cost_not_covered")
            incomplete_keys.add(key)
    return unknown, sum(max(0, value - costs[key]) for key, value in lower_bounds.items())


def audit_replicates(plan, records, *, expected_plan_digest):
    """Audit the entire planned roster; failed fits cannot disappear from inference."""
    planning = validate_plan(plan, expected_plan_digest)
    f._need(isinstance(records, list), "fit records must be an array")
    planned = {entry["fit_id"]: entry for entry in plan["fits"]}
    f._need(len(records) == len(planned) and {r.get("fit_id") for r in records} == set(planned),
            "incomplete or duplicate planned fit roster")
    registered = f._time(plan["registered_at"])
    unknown, violations, outcomes, values = [], [], {}, defaultdict(list)
    attempts, fit_runs, episode_runs, episode_attempts, training_receipts = set(), set(), set(), set(), set()
    thresholds, totals, profile_totals, amortized = {}, [], defaultdict(list), defaultdict(list)
    all_rows, completed = [], 0
    for record in sorted(records, key=lambda r: r["fit_id"]):
        fid = record["fit_id"]
        f._need(record.get("training_seed") == planned[fid]["training_seed"], "training seed differs from roster")
        if record.get("status") == "not_started":
            f._need(record.get("fit_run_id") is None and record.get("training_receipt_digest") is None
                    and record.get("research_attempts") == [] and record.get("rows") == []
                    and all(record.get(key) is None for key in ("protocol", "selection", "fit_lock")),
                    "not-started fit cannot contain an execution")
            outcomes[fid] = {"status": "not_started", "research_total": None,
                "research_known_lower_bound": 0, "attempts": 0, "failed_attempts": 0}
            totals.append(None); unknown.append(f"{fid}:not_started")
            continue
        run = record.get("fit_run_id")
        f._need(isinstance(run, str) and run and run not in fit_runs and
                run not in plan["power"]["pilot_fit_run_ids"], "reused fit or pilot execution")
        fit_runs.add(run)
        receipt = record.get("training_receipt_digest")
        f._need(f._hash(receipt) and receipt not in training_receipts, "missing/reused independent fit receipt")
        training_receipts.add(receipt)
        status = record.get("status")
        f._need(status in ("complete", "failed", "unresolved"), "invalid fit status")
        costs, counts, missing, incomplete_keys = _attempts(record, attempts, registered)
        f._need(isinstance(record.get("rows"), list), "fit must retain observed rows, even if empty")
        uncovered, extra_lower = _evaluation_coverage(record["rows"], costs, counts, incomplete_keys)
        missing.extend(uncovered)
        unknown.extend(f"{fid}:research:{x}" for x in missing)
        total = None if missing else sum(costs.values())
        totals.append(total)
        outcomes[fid] = {"status": status, "research_total": total,
            "research_known_lower_bound": sum(costs.values()) + extra_lower,
            "attempts": len(record["research_attempts"]),
            "failed_attempts": sum(a["status"] == "failed" for a in record["research_attempts"])}
        if status != "complete":
            partial = record.get("rows")
            f._need(isinstance(partial, list), "unfinished fit must retain observed rows, even if empty")
            # Partial fit outputs stay in the raw record and its digest. They do
            # not enter complete-case inference or silently become zero rows.
            outcomes[fid].update(retained_partial_rows=len(partial),
                                  retained_partial_rows_digest=f.canonical_digest(partial))
            unknown.append(f"{fid}:{status}")
            continue
        p, rows, selection = record["protocol"], record["rows"], record["selection"]
        f._need(record.get("fit_lock") == seal_fit(record), "pre-evaluation fit receipt lock changed")
        f._need(design_digest(p) == plan["design_digest"], "fit changed registered design/opportunity")
        f._need(p["alpha"] == plan["power"]["alpha"], "planning/inference alpha differs")
        tasks, indexed, incomplete = f._validate_rows(p, rows, {"validation", "test"})
        val = [row for row in rows if row["split"] == "validation"]
        f._need(selection == f.select_comparators(p, val, selection.get("locked_at")),
                "fit comparator lock differs")
        lock_time = f._time(selection["locked_at"])
        f._need(all(f._time(row["started_at"]) > lock_time for row in rows if row["split"] == "test"),
                "confirmation observed before comparator lock")
        first_validation = min(f._time(row["started_at"]) for row in val)
        f._need(all(a.get("finished_at") is None or f._time(a["finished_at"]) < first_validation for a in record["research_attempts"]
                    if a["phase"] in ("training", "search")), "training/search continued into validation")
        test_groups = {t["source_group"] for t in tasks.values() if t["split"] == "test"}
        f._need(not test_groups.intersection(plan["power"]["pilot_source_groups"]), "pilot leaks into confirmation")
        for key, profile in p["profiles"].items():
            subtotals = []
            for phase in PHASES:
                ledger_key = f"{key}:{phase}"
                f._need(counts[ledger_key] > 0, "profile lost research attempt inventory")
                declared = profile["research_costs"][phase]
                if ledger_key not in incomplete_keys:
                    f._need(declared is not None and math.isclose(declared, costs[ledger_key], abs_tol=1e-9,
                                                                rel_tol=1e-12), "research ledger/profile cost differs")
                elif declared is not None:
                    f._need(declared >= costs[ledger_key], "known research lower bound exceeds declared cost")
                subtotals.append(declared)
            profile_totals[key].append(None if any(f"{key}:{phase}" in incomplete_keys for phase in PHASES)
                                      or any(x is None for x in subtotals) else sum(subtotals))
        for row in rows:
            f._need(row["run_id"] not in episode_runs and not episode_attempts.intersection(row["attempt_ids"]),
                    "episode execution reused across independent fits")
            episode_runs.add(row["run_id"]); episode_attempts.update(row["attempt_ids"])
        unknown.extend(f"{fid}:{x}" for x in incomplete)
        budget, integrity = f._observation_findings(p, rows)
        violations.extend({"fit_id": fid, **v} for v in budget + integrity)
        completed += 1; all_rows.extend(rows)
        definitions = _definitions(p, selection)
        for name, (cohort, terms, net, threshold) in definitions.items():
            thresholds[name] = threshold
            vector = f._cluster_values(p, tasks, indexed, "test", cohort, terms, net)
            values[name].append(vector)
            required = planning["required_source_groups_per_test_cohort"]
            if required is None or (vector is not None and len(vector) < required):
                unknown.append(f"{fid}:{cohort}:sample_size_below_prospective_plan")
        for regime in f.REGIMES:
            baseline = selection["choices"][regime]["complete"]
            d, b = profile_totals[f"{regime}:D"][-1], profile_totals[f"{regime}:{baseline}"][-1]
            for n in p["deployment_counts"]:
                amortized[f"{regime}:{n}"].append(None if d is None or b is None else p["cost_weight"] * (d-b) / n)
        outcomes[fid].update(comparators=selection["choices"], episodes=len(rows),
            failed_episodes=sum(row["status"] == "failed" for row in rows))
    # Even an entirely failed roster retains the complete preregistered family.
    names = [f"{regime}:{name}" for regime in f.REGIMES for name in
             ("B-A", "D-C", "D-B", "interaction", "B-strongest", "D-strongest")]
    names += [f"{prefix}:{arm}" for arm in f.CELLS for prefix in ("joint-frozen", "retention")]
    contrasts = {name: {"estimate": None, "ci": None, "statistical_gate": "HOLD",
                        "scientific_gate": "HOLD"} for name in names}
    for name, matrices in values.items():
        result = {"estimate": None, "ci": None, "statistical_gate": "HOLD", "scientific_gate": "HOLD"}
        if completed == len(planned) and all(x is not None for x in matrices):
            matrix = np.stack(matrices)
            ci = crossed_interval(matrix, draws=plan["bootstrap_samples"], seed=plan["bootstrap_seed"],
                                  alpha=plan["power"]["alpha"])
            passes = ci[0] >= thresholds[name] if name.startswith("retention:") else ci[0] > thresholds[name]
            result.update(estimate=float(matrix.mean()), ci=ci, independent_fits=matrix.shape[0],
                source_groups=matrix.shape[1], threshold=thresholds[name],
                descriptive_gate="PASS" if passes else "NOT_ESTABLISHED",
                statistical_gate="HOLD" if unknown or violations else "PASS" if passes else "NOT_ESTABLISHED")
        contrasts[name] = result
    adjusted = {}
    for key, shifts in amortized.items():
        regime, _ = key.split(":")
        ci = contrasts[f"{regime}:D-strongest"]["ci"]
        adjusted[key] = None if ci is None or any(x is None for x in shifts) else crossed_interval(
            np.stack(values[f"{regime}:D-strongest"]) - np.asarray(shifts)[:, None],
            draws=plan["bootstrap_samples"], seed=plan["bootstrap_seed"], alpha=plan["power"]["alpha"])
    return {"schema": "ndu-replicated-factorial-audit-v1", "plan_digest": expected_plan_digest,
        "records_digest": f.canonical_digest(records), "planned_fits": len(planned), "complete_fits": completed,
        "planning": planning, "fits": outcomes, "contrasts": contrasts,
        "unknowns": sorted(set(unknown)), "violations": violations,
        "research_total": None if any(x is None for x in totals) else sum(totals),
        "research_known_lower_bound": sum(o["research_known_lower_bound"] for o in outcomes.values()),
        "inference_cost_ledger": f.cost_ledger(all_rows),
        "D_minus_strongest_amortized_ci_at_deployments": adjusted,
        "ledger_note": "Research includes evaluation and failed fits; do not add inference again. Inference ledger covers complete fits only; partial rows remain in raw records. Amortization includes each fit's research costs.",
        "inference": "paired contrasts; equal fit/source weighting; crossed percentile bootstrap; Bonferroni 20",
        "evidence_status": "Inconclusive", "scientific_admission": "HOLD", "adoption_authorized": False,
        "native_receipt_authentication": "NOT_IMPLEMENTED", "independent_fit_authentication": "NOT_IMPLEMENTED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-digest", required=True)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text())
        result = (audit_replicates(plan, json.loads(args.records.read_text()), expected_plan_digest=args.expected_plan_digest)
                  if args.records else validate_plan(plan, args.expected_plan_digest))
    except (f.InvalidEvidence, KeyError, ValueError, TypeError, AttributeError, OSError) as error:
        result = {"evidence_status": "Failed", "scientific_admission": "HOLD",
                  "adoption_authorized": False, "error": str(error)}
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        raise SystemExit(2) from error
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
