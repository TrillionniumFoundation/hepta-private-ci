"""Four-arm attribution with pinned panels and a separate sealed capture roster.

The design is frozen before outcomes. Dynamic event IDs are instead pinned by
an independently retained capture manifest after execution; this module cannot
prove either timestamp or the honesty/completeness of an instrumented owner.
Events represent exclusive costs, never nested wall/CPU envelopes. One physical
shared computation may be referenced repeatedly inside one episode. Cross-arm
execution is separate; outer setup/training costs are reported, not amortized.
Training receipts belong to one arm/seed; shared pretraining belongs to setup.
The design must distinguish same_total_budget from same_component_dose (or
uncontrolled). Equal component dose may spend more on the joint arm; it does not
establish a gain at equal total budget. Resource caps, component update doses,
model provenance, and legal online information remain runner-level checks.
"""

import argparse
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics

ARMS = ("00", "10", "01", "11")
FAILURES = ("failed", "cancelled", "timeout", "incomplete")
CATEGORIES = {"encoder", "generation", "planner", "critic", "verification", "seal"}
OUTER_SCOPES = {"setup", "training", "analysis", "publication"}
BUDGET_ESTIMANDS = {"same_total_budget", "same_component_dose", "uncontrolled"}


def digest(value):
    """Canonical JSON digest; callers retain this independently from input files."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, name, nonnegative=False):
    _require(type(value) in (int, float) and math.isfinite(value), name + " unknown/nonfinite")
    _require(not nonnegative or value >= 0, name + " negative")
    return float(value)


def _unique(values, name):
    _require(isinstance(values, list) and values and len(set(values)) == len(values), name)
    return values


def certainty_equivalent(values, gamma=2.0):
    """Stable empirical CE; finite-sample plug-in, not an unbiased estimator."""
    _require(values, "empty outcome sample")
    gamma = _number(gamma, "gamma", True)
    values = [_number(x, "return") for x in values]
    if gamma == 0:
        return statistics.fmean(values)
    # Center on worst return to avoid multiplying a large absolute value by gamma.
    worst = min(values)
    shifted = [math.exp(-gamma * (x - worst)) for x in values]
    return worst - math.log(math.fsum(shifted) / len(values)) / gamma


def effects(values):
    """Subtract arm-level functionals; never apply CE to paired differences."""
    _require(set(values) == set(ARMS), "four arms required")
    values = {k: _number(v, "arm functional") for k, v in values.items()}
    u00, u10, u01, u11 = (values[k] for k in ARMS)
    return {
        "controller_on_frozen": u10 - u00,
        "generator_on_fixed": u01 - u00,
        "controller_on_learned": u11 - u01,
        "generator_on_learned_control": u11 - u10,
        "joint_minus_baseline": u11 - u00,
        "interaction": (u11 - u10) - (u01 - u00),
    }


def audit_panel(bundle, design_sha256, capture_sha256):
    """Reconcile every registered cell and every captured physical event."""
    design, capture = bundle["design"], bundle["capture"]
    _require(digest(design) == design_sha256, "design digest mismatch")
    _require(digest(capture) == capture_sha256, "capture digest mismatch")
    _require(capture["design_sha256"] == design_sha256, "capture belongs to other design")
    _require(design["schema"] == "hepta.factorial-design.v1", "design schema")
    _require(capture["schema"] == "hepta.factorial-capture.v1", "capture schema")
    sources = _unique(design["sources"], "source roster")
    seeds = _unique(design["training_seeds"], "training seed roster")
    repeats = _unique(design["replicates"], "replicate roster")
    _require(all(isinstance(x, str) and x for x in sources), "invalid source IDs")
    _require(all(type(x) is int for x in seeds + repeats), "invalid integer IDs")
    _require(design["stratum"] and design["cost_unit"], "stratum and cost unit required")
    _require(design["training_budget_estimand"] in BUDGET_ESTIMANDS, "training budget estimand required")
    penalties = design["failure_utilities"]
    _require(set(penalties) == set(FAILURES), "predeclared failure utilities required")
    for value in penalties.values():
        _number(value, "failure utility")
    expected = set(itertools.product(sources, seeds, repeats, ARMS))
    roster, observed, owners = {}, set(), {}
    for entry in capture["episodes"]:
        eid = entry["id"]
        key = (entry["source_id"], entry["training_seed"], entry["replicate"], entry["arm"])
        _require(isinstance(eid, str) and eid and eid not in roster, "duplicate/invalid episode ID")
        _require(key not in observed, "duplicate panel cell")
        roster[eid], observed = entry, observed | {key}
        for event_id in entry["event_ids"]:
            _require(isinstance(event_id, str) and event_id, "invalid event ID")
            _require(owners.get(event_id, eid) == eid, "cross-episode/arm event reuse")
            owners[event_id] = eid
    _require(observed == expected, "incomplete or extra registered panel cells")
    for event_id in capture["outer_event_ids"]:
        _require(isinstance(event_id, str) and event_id and event_id not in owners, "reused outer event")
        owners[event_id] = None
    events = {}
    for event in bundle["events"]:
        event_id = event["id"]
        _require(event_id not in events or events[event_id] == event, "conflicting physical event retry")
        events[event_id] = event
    _require(set(events) == set(owners), "missing or unregistered physical events")
    cost_by_episode = {eid: 0.0 for eid in roster}
    categories = {eid: set() for eid in roster}
    category_costs, outer_costs, candidate_costs = Counter(), Counter(), Counter()
    training_costs = Counter()
    for event_id, event in events.items():
        owner = owners[event_id]
        _require(event["episode_id"] == owner, "event owner mismatch")
        _require(event["metering"] == "exclusive", "nested/inclusive cost cannot be added")
        cost = _number(event["cost"], "event cost", True)
        _require(type(event["selected"]) is bool, "candidate selection unknown")
        _require(event["status"] in ("completed", "not_run") + FAILURES, "unknown event status")
        _require(event["status"] != "not_run" or cost == 0, "not-run event has physical cost")
        if owner is None:
            _require(event["scope"] in OUTER_SCOPES, "unknown outer scope")
            outer_costs[event["scope"]] += cost
            if event["scope"] == "training":
                cell = (event["training_seed"], event["arm"])
                _require(cell[0] in seeds and cell[1] in ARMS, "training receipt must belong to one arm/seed")
                training_costs[cell] += cost
        else:
            _require(event["scope"] == "episode", "episode event scope mismatch")
            cost_by_episode[owner] += cost
            categories[owner].add(event["category"])
            category_costs[event["category"]] += cost
            candidate_costs["selected" if event["selected"] else "unselected"] += cost
    _require(set(training_costs) == set(itertools.product(seeds, ARMS)), "missing training cost cell; unknown is not zero")
    for value in itertools.chain(outer_costs.values(), training_costs.values()):
        _number(value, "aggregate lifecycle cost", True)
    rows, panel, statuses = {}, {}, Counter()
    for row in bundle["rows"]:
        _require(row["id"] not in rows, "duplicate episode outcome")
        rows[row["id"]] = row
    _require(set(rows) == set(roster), "missing or unregistered outcomes, including failures")
    for eid, row in rows.items():
        _require(CATEGORIES <= categories[eid], "missing cost category; unknown is not zero")
        cost = _number(row["sealed_cost"], "sealed episode cost", True)
        _require(math.isclose(cost, cost_by_episode[eid], rel_tol=1e-10, abs_tol=1e-12), "seal/ledger mismatch")
        utility = _number(row["utility"], "utility")
        status = row["status"]
        _require(status in ("completed",) + FAILURES, "unknown episode status")
        _require(status == "completed" or utility == penalties[status], "failure utility changed")
        entry = roster[eid]
        key = (entry["source_id"], entry["training_seed"], entry["replicate"], entry["arm"])
        panel[key] = utility - cost
        statuses[status] += 1
    return panel, {
        "episodes": len(rows), "unique_physical_events": len(events),
        "duplicate_receipt_retries": len(bundle["events"]) - len(events),
        "statuses": dict(statuses), "episode_cost": math.fsum(cost_by_episode.values()),
        "category_costs": dict(category_costs), "candidate_costs": dict(candidate_costs),
        "outer_costs_unamortized": dict(outer_costs),
        "outer_scope_coverage": {s: "recorded" if s in outer_costs else "unknown" for s in sorted(OUTER_SCOPES)},
        "whole_lifecycle_cost_known": OUTER_SCOPES <= set(outer_costs),
        "training_cost_by_seed_arm": [{"training_seed": seed, "arm": arm, "cost": value}
                                      for (seed, arm), value in sorted(training_costs.items())],
        "physical_capture_authenticated": False,
    }


def analyze(bundle, design_sha256, capture_sha256, bootstrap_replicates=2000, bootstrap_seed=731):
    """Crossed seed/source bootstrap, preserving all arms and within-cell repeats."""
    panel, audit = audit_panel(bundle, design_sha256, capture_sha256)
    design = bundle["design"]
    sources, seeds, repeats = (design[k] for k in ("sources", "training_seeds", "replicates"))
    gamma = _number(design["gamma"], "gamma", True)
    _require(type(bootstrap_replicates) is int and 0 <= bootstrap_replicates <= 10000, "bootstrap count")

    def summary(source_draw, seed_draw):
        values = {arm: [panel[s, t, r, arm] for s in source_draw for t in seed_draw for r in repeats] for arm in ARMS}
        ce = {arm: certainty_equivalent(value, gamma) for arm, value in values.items()}
        means = {arm: statistics.fmean(value) for arm, value in values.items()}
        return {"ce": ce, "mean": means, "ce_effects": effects(ce), "mean_effects": effects(means)}

    result = summary(sources, seeds)
    rng, samples = random.Random(bootstrap_seed), {k: [] for k in result["ce_effects"]}
    for _ in range(bootstrap_replicates):
        estimate = summary(rng.choices(sources, k=len(sources)), rng.choices(seeds, k=len(seeds)))
        for key, value in estimate["ce_effects"].items():
            samples[key].append(value)
    intervals = {}
    if bootstrap_replicates:
        for key, values in samples.items():
            values.sort()
            intervals[key] = [values[int(0.025 * (len(values) - 1))], values[math.ceil(0.975 * (len(values) - 1))]]
    return {
        "schema": "hepta.factorial-analysis.v1", "stratum": design["stratum"],
        "design_sha256": design_sha256, "capture_sha256": capture_sha256,
        "gamma": gamma, "cost_unit": design["cost_unit"], "audit": audit, **result,
        "source_count": len(sources), "training_seed_count": len(seeds),
        "few_training_seeds": len(seeds) < 10,
        "training_budget_estimand": design["training_budget_estimand"],
        "training_budget_and_model_provenance_verified": False,
        "bootstrap": {"replicates": bootstrap_replicates, "seed": bootstrap_seed,
                      "unit": "crossed original source and training seed; all arms paired",
                      "ce_effect_percentile_95": intervals},
        "estimand": "CE of uniform empirical source/seed/replicate mixture within this stratum",
        "confirmation": False,
        "limitations": ["Finite-sample plug-in CE and unadjusted exploratory percentile intervals.",
                        "Few training seeds give weak seed-distribution uncertainty estimates.",
                        "No semantic quality, observer independence or honest physical capture certification.",
                        "Outer lifecycle cost is unamortized and excluded from per-episode returns.",
                        "Same total training budget and same component dose are different estimands; caps/doses require runner verification."],
    }


def historical_summary(matrix, protocol):
    """Recompute only descriptive contrasts from V3 summaries, without raw receipts."""
    _require(matrix["schema"] == "hepta.v3.readable-complete-matrix", "historical schema")
    expected = set(itertools.product(protocol["seeds"], protocol["widths"]))
    seen, result = set(), []
    mapping = {"00": "frozen.fixed", "10": "frozen.dynamic", "01": "joint.fixed", "11": "joint.dynamic"}
    for cell in matrix["cells"]:
        coordinate = (cell["seed"], cell["width"])
        _require(coordinate not in seen, "duplicate historical cell")
        seen.add(coordinate)
        expected_arms = {mode + "." + suffix for mode in protocol["modes"] for suffix in mapping.values()}
        _require(set(cell["arms"]) == expected_arms, "incomplete historical arm matrix")
        for mode in protocol["modes"]:
            arms = {key: cell["arms"][mode + "." + suffix] for key, suffix in mapping.items()}
            ce = {key: _number(value["population_ce_plugin"], "historical CE") for key, value in arms.items()}
            means = {key: _number(value["mean_net_return"], "historical mean") for key, value in arms.items()}
            result.append({"seed": cell["seed"], "width": cell["width"], "core": mode,
                           "ce": ce, "mean": means, "ce_effects": effects(ce), "mean_effects": effects(means),
                           "original_result_sha256": cell["original_result_sha256"],
                           "reported_failures": {key: value["failures"] for key, value in arms.items()}})
    _require(seen == expected, "incomplete historical seed/width matrix")
    return {"schema": "hepta.factorial-historical-summary.v1", "cells": result,
            "raw_trajectory_and_event_audit": False, "new_confidence_intervals": False,
            "confirmation": False, "training_benefit_established": False,
            "scope": "Descriptive differences of existing arm summaries; no global CE or pooled widths/cores.",
            "limitations": ["Inherited V3 cost/execution contract; no raw event reconciliation.",
                            "Fixed schedule was preregistered, not validation-tuned; old greedy is actor-logit argmax, not one-step VOI.",
                            "Old fixed and STOP paths still invoked policy() at each step.",
                            "Same update counts do not establish equal total training budget or equal component dose.",
                            "No new training, holdout evaluation, semantic qualification or scientific efficacy claim."]}


def _read_pinned(path, expected_sha):
    raw = Path(path).read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha, "input file SHA-256 mismatch")
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bundle")
    mode.add_argument("--historical-matrix")
    parser.add_argument("--design-sha256")
    parser.add_argument("--capture-sha256")
    parser.add_argument("--matrix-sha256")
    parser.add_argument("--protocol")
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    args = parser.parse_args()
    if args.bundle:
        if not args.design_sha256 or not args.capture_sha256:
            parser.error("--bundle requires independently retained --design-sha256 and --capture-sha256")
        result = analyze(json.loads(Path(args.bundle).read_text()), args.design_sha256, args.capture_sha256, args.bootstrap_replicates)
    else:
        if not args.matrix_sha256 or not args.protocol or not args.protocol_sha256:
            parser.error("--historical-matrix requires --matrix-sha256, --protocol and --protocol-sha256")
        result = historical_summary(_read_pinned(args.historical_matrix, args.matrix_sha256), _read_pinned(args.protocol, args.protocol_sha256))
        result.update(matrix_sha256=args.matrix_sha256, protocol_sha256=args.protocol_sha256)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
