"""Prospective regenerative-study inventory; no native authority or training.

Hashes bind submitted bytes, not truth, chronology or independent execution.
This version cannot register a study or produce an admission/adoption PASS.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


SCHEMA = "hcsn-regenerative-experiment-v1"
ORIGINAL_CAMPAIGN = "1a1acdd69f2-fc05-5757"
ORIGINAL_SOURCE = "f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b"
PHASES = ("training", "search", "evaluation", "deployment")
COMPONENTS = ("encoder", "core", "decoder", "state_storage")
COST_FIELDS = ("wall_seconds", "cpu_seconds", "peak_host_bytes", "peak_gpu_bytes",
               "energy_joules", "actual_charges")
UNIT_FIELDS = ("updates_submitted", "examples_submitted", "tokens_submitted")
TERMINAL_STATES = ("completed", "failed", "oom", "cancelled", "unresolved")
BINDINGS = ("source", "data", "encoder", "decoder", "evaluator", "objective",
            "meter", "power_plan", "runtime", "cost_scope")
ARM_EVIDENCE = ("executable_sha256", "capacity_receipt_sha256", "semantic_receipt_sha256")
COMMON_EVENT_FIELDS = ("kind", "attempt_id", "study_id", "plan_digest", "fit_id", "arm",
                       "training_seed", "source_digest", "phase", "components",
                       "native_receipt_sha256", "event_sha256")
TERMINAL_FIELDS = ("status", "units", "cost", "model_sha256")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fields(value, names, label):
    _require(isinstance(value, dict) and set(value) == set(names),
             label + " has missing or unknown fields")


def _integer(value, label, minimum=0):
    _require(type(value) is int and minimum <= value <= 2**53 - 1,
             label + " must be an exact nonnegative JSON integer")


def _number(value, label):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    _require(valid, label + " must be finite and nonnegative")


def _digest(value, label, nullable=False):
    if value is None and nullable:
        return
    _require(isinstance(value, str) and len(value) == 64
             and all(c in "0123456789abcdef" for c in value), label + " must be SHA256")


def canonical_digest(value):
    """Bind canonical JSON, rejecting nonfinite quantities."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    def reject(value):
        raise ValueError("Nonfinite JSON literal: " + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject)


def proposed_plan():
    """Return an UNREGISTERED proposal. Seeds are proposals, not power evidence."""
    variants = {
        "hx_dual": ("HX", "dual", "first_passage", True, True, "physical"),
        "smooth_dual": ("smooth", "dual", "first_passage", True, True, "physical"),
        "margin_only": ("HX", "margin", "first_passage", True, True, "physical"),
        "call_only": ("HX", "call", "first_passage", True, True, "physical"),
        "risk_only": ("HX", "risk", "first_passage", True, True, "physical"),
        "endpoint": ("HX", "dual", "endpoint", True, True, "physical"),
        "no_reset": ("HX", "dual", "first_passage", False, True, "physical"),
        "no_refractory": ("HX", "dual", "first_passage", True, False, "physical"),
        "uniform_tick": ("HX", "dual", "first_passage", True, True, "tick"),
    }
    arms = {}
    for name, (kernel, channels, risk, reset, refractory, clock) in variants.items():
        arms[name] = dict(kernel=kernel, channels=channels, risk=risk, reset=reset,
                          refractory=refractory, clock=clock, boundary="fixed",
                          active_parameters=None, persistent_state_bytes=None,
                          **dict.fromkeys(ARM_EVIDENCE))
    return {
        "schema": SCHEMA, "study_id": "regenerative-mechanisms-20261107-v1",
        "registration": "UNREGISTERED", "state": "prospective_configuration_only",
        "original_campaign": {"id": ORIGINAL_CAMPAIGN, "source": ORIGINAL_SOURCE,
                              "treatment": "read_only_separate_denominator", "expected_runs": 170},
        "model": {"state": "one_dimensional_log_diffusion", "generator": "constant_coefficient",
                  "boundary": "fixed", "reset_target": "fixed_positive_distance",
                  "refractory": "physical_time", "value_risk_survivor": "same_generator"},
        "bindings": dict.fromkeys(BINDINGS), "training_seeds": [1103, 2207, 3301],
        "episode_seeds": [4703, 5801], "arms": arms,
        "fit_budget": dict.fromkeys(UNIT_FIELDS), "search_budget": dict.fromkeys(UNIT_FIELDS),
        "total_cost_limits_per_fit": dict.fromkeys(COST_FIELDS),
        "minimum_useful_effect": None, "retention_margin": None,
        "conditional_boundary": {"status": "UNSUPPORTED_IN_THIS_CANDIDATE",
                                 "future_study_id": None,
                                 "required": "Qualified controlled generator or QVI boundary under a separate identity"},
    }


def validate_plan(plan):
    """Check the planned denominator; evidence hashes do not admit experiments."""
    template = proposed_plan()
    _fields(plan, template, "plan")
    for field in ("schema", "registration", "state", "original_campaign", "model", "conditional_boundary"):
        _require(plan[field] == template[field], "Unsupported or rebound plan field: " + field)
    study = plan["study_id"]
    _require(isinstance(study, str) and study and study != ORIGINAL_CAMPAIGN,
             "A new study needs its own identity")
    _fields(plan["bindings"], BINDINGS, "bindings")
    for name, digest in plan["bindings"].items():
        _digest(digest, "binding " + name, nullable=True)
    for name in ("training_seeds", "episode_seeds"):
        values = plan[name]
        _require(isinstance(values, list) and values, name + " is empty")
        for value in values:
            _integer(value, name)
        _require(len(set(values)) == len(values), name + " has duplicates")
    _require(len(plan["training_seeds"]) >= 3, "Three proposed fits are a structural floor, not a power analysis")
    expected = template["arms"]
    _fields(plan["arms"], expected, "arms")
    for name, arm in plan["arms"].items():
        _fields(arm, expected[name], "arm " + name)
        for field in ("kernel", "channels", "risk", "reset", "refractory", "clock", "boundary"):
            _require(type(arm[field]) is type(expected[name][field]) and arm[field] == expected[name][field],
                     "Ablation changes an unrelated mechanism: " + name + ":" + field)
        for field in ARM_EVIDENCE:
            _digest(arm[field], name + " " + field, nullable=True)
    for field in ("active_parameters", "persistent_state_bytes"):
        values = [arm[field] for arm in plan["arms"].values() if arm[field] is not None]
        for value in values:
            _integer(value, field, 1)
        _require(len(set(values)) <= 1, "Active parameter and state capacities must match: " + field)
    for name in ("fit_budget", "search_budget"):
        _fields(plan[name], UNIT_FIELDS, name)
        for field, value in plan[name].items():
            if value is not None:
                _integer(value, name + "." + field, 1 if name == "fit_budget" else 0)
    _fields(plan["total_cost_limits_per_fit"], COST_FIELDS, "total cost limits")
    for name, value in plan["total_cost_limits_per_fit"].items():
        if value is not None:
            _number(value, name)
    for name in ("minimum_useful_effect", "retention_margin"):
        if plan[name] is not None:
            _number(plan[name], name)
    return canonical_digest(plan)


def fit_roster(plan):
    """One identity per arm and training seed; episode seeds are never extra fits."""
    validate_plan(plan)
    return [{"fit_id": f"{arm}/train-{seed}", "arm": arm, "training_seed": seed}
            for arm in sorted(plan["arms"]) for seed in plan["training_seeds"]]


def seal_event(event):
    """Compute a local inventory checksum. This is deliberately not a signature."""
    body = {key: value for key, value in event.items() if key != "event_sha256"}
    return dict(body, event_sha256=canonical_digest(body))


def _events(plan, events, digest, roster):
    _require(isinstance(events, list), "Events must be a list")
    starts, terminals, hashes = {}, {}, set()
    for event in events:
        _require(isinstance(event, dict) and event.get("kind") in ("start", "terminal"), "Unknown event kind")
        _fields(event, COMMON_EVENT_FIELDS + (TERMINAL_FIELDS if event["kind"] == "terminal" else ()), "event")
        _require(event == seal_event(event), "Inventory event bytes differ from their checksum")
        _require(event["event_sha256"] not in hashes, "Duplicate inventory event")
        hashes.add(event["event_sha256"])
        _require(isinstance(event["attempt_id"], str) and event["attempt_id"], "Missing attempt identity")
        _require(event["study_id"] == plan["study_id"] and event["plan_digest"] == digest, "Foreign study or plan event")
        _require(isinstance(event["fit_id"], str), "Invalid fit identity")
        fit = roster.get(event["fit_id"])
        _require(fit is not None and event["arm"] == fit["arm"]
                 and type(event["training_seed"]) is int and event["training_seed"] == fit["training_seed"],
                 "Fit and training seed do not match")
        _require(event["source_digest"] is not None and event["source_digest"] == plan["bindings"]["source"],
                 "Source identity is absent or changed")
        _require(event["phase"] in PHASES, "Unknown cost phase")
        components = event["components"]
        _require(isinstance(components, list) and components and all(c in COMPONENTS for c in components)
                 and len(set(components)) == len(components), "Invalid included-component inventory")
        _digest(event["native_receipt_sha256"], "native receipt", nullable=True)
        target = starts if event["kind"] == "start" else terminals
        _require(event["attempt_id"] not in target, "Duplicate immutable " + event["kind"])
        target[event["attempt_id"]] = event
        if event["kind"] == "terminal":
            _require(event["status"] in TERMINAL_STATES, "Invalid terminal state")
            _fields(event["units"], UNIT_FIELDS, "submitted units")
            for field, value in event["units"].items():
                if value is not None:
                    _integer(value, field)
                elif event["phase"] == "training" and event["status"] == "completed":
                    raise ValueError("Completed training has unknown submitted units")
            _fields(event["cost"], COST_FIELDS, "cost; use null for unknown")
            for field, value in event["cost"].items():
                if value is not None:
                    _number(value, field)
            _digest(event["model_sha256"], "model", nullable=event["status"] != "completed" or event["phase"] == "search")
    _require(set(terminals) <= set(starts), "Terminal without original start")
    for attempt_id, terminal in terminals.items():
        for field in ("fit_id", "arm", "training_seed", "source_digest", "phase", "components"):
            _require(terminal[field] == starts[attempt_id][field], "Terminal rebinds " + field)
    return starts, terminals


def _cost_summary(terminals):
    known, unknown = {}, {}
    for field in COST_FIELDS:
        values = [e["cost"][field] for e in terminals if e["cost"][field] is not None]
        unknown[field] = sum(e["cost"][field] is None for e in terminals)
        known[field] = (max(values) if field.startswith("peak_") else sum(values)) if values else None
        if known[field] is not None:
            _number(known[field], "aggregate " + field)
    return {"known_totals_or_peak": known, "unknown_terminal_fields": unknown}


def audit_registry(plan, events, expected_plan_digest):
    """Retain all submitted starts/terminals, failures and unknown costs.

    Phase costs must cover disjoint intervals. Component labels disclose what is
    included in each total; component costs are not added a second time. These
    scope assertions and absence of omitted events require native verification.
    """
    digest = validate_plan(plan)
    _digest(expected_plan_digest, "retained plan")
    _require(digest == expected_plan_digest, "Plan differs from retained external pin")
    roster = {row["fit_id"]: row for row in fit_roster(plan)}
    starts, terminals = _events(plan, events, digest, roster)
    blockers = ["plan_UNREGISTERED", "native_owner_authentication_NOT_IMPLEMENTED",
                "inventory_completeness_unverified", "independent_fit_execution_unverified",
                "phase_cost_disjointness_unverified", "heldout_external_benefit_not_evaluated",
                "retention_not_evaluated", "deployment_latency_throughput_not_evaluated"]
    for name, value in plan["bindings"].items():
        if value is None:
            blockers.append("missing_binding:" + name)
    for name, arm in plan["arms"].items():
        blockers += ["missing_arm_evidence:" + name + ":" + k for k in
                     ("active_parameters", "persistent_state_bytes") + ARM_EVIDENCE if arm[k] is None]
    for name in ("fit_budget", "search_budget", "total_cost_limits_per_fit"):
        blockers += ["missing_budget:" + name + ":" + k for k, v in plan[name].items() if v is None]
    for name in ("minimum_useful_effect", "retention_margin"):
        if plan[name] is None:
            blockers.append("missing_success_criterion:" + name)
    outcomes, overruns, models = [], [], Counter()
    required_phases = set(PHASES) - ({"search"} if all(v == 0 for v in plan["search_budget"].values()) else set())
    for fit_id, fit in roster.items():
        owned = [x for x in starts.values() if x["fit_id"] == fit_id]
        finished = [terminals[x["attempt_id"]] for x in owned if x["attempt_id"] in terminals]
        trained = [x for x in finished if x["phase"] == "training"]
        completed = [x for x in trained if x["status"] == "completed"]
        models.update(x["model_sha256"] for x in completed)
        unresolved = [x["attempt_id"] for x in owned if x["attempt_id"] not in terminals]
        unresolved += [x["attempt_id"] for x in finished if x["status"] == "unresolved"]
        state = ("unresolved" if unresolved else "ambiguous" if len(completed) > 1 else
                 "completed" if completed else "failed" if trained else "not_started")
        if len(completed) > 1:
            blockers.append("multiple_successes_allow_selection:" + fit_id)
        missing_phases = sorted(required_phases - {x["phase"] for x in finished})
        missing_components = sorted(set(COMPONENTS) - {c for x in finished for c in x["components"]})
        if missing_phases or missing_components:
            blockers.append("incomplete_cost_coverage:" + fit_id)
        submitted = {}
        for phase, budget in (("training", plan["fit_budget"]), ("search", plan["search_budget"])):
            submitted[phase] = {}
            for unit in UNIT_FIELDS:
                values = [x["units"][unit] for x in finished if x["phase"] == phase]
                if any(value is None for value in values):
                    blockers.append("submitted_budget_unknown:" + fit_id + ":" + phase + ":" + unit)
                used = sum(value for value in values if value is not None)
                submitted[phase][unit] = {
                    "known_submitted": used if any(value is not None for value in values) else None,
                    "unknown_terminal_attempts": sum(value is None for value in values),
                }
                if budget[unit] is not None and used > budget[unit]:
                    overruns.append(dict(fit_id=fit_id, phase=phase, unit=unit, observed=used, limit=budget[unit]))
                if phase == "training" and completed and budget[unit] is not None:
                    if any(x["units"][unit] != budget[unit] for x in completed):
                        blockers.append("incomplete_frozen_budget:" + fit_id + ":" + unit)
        if len(completed) == 1:
            for terminal in finished:
                if terminal["phase"] in ("evaluation", "deployment") and terminal["status"] == "completed":
                    _require(terminal["model_sha256"] == completed[0]["model_sha256"], "Evaluation rebinds trained model")
        if any(x["phase"] in ("evaluation", "deployment") and x["status"] != "completed" for x in finished):
            blockers.append("evaluation_or_deployment_incomplete:" + fit_id)
        costs = _cost_summary(finished)
        for field, value in costs["known_totals_or_peak"].items():
            limit = plan["total_cost_limits_per_fit"][field]
            if value is not None and limit is not None and value > limit:
                overruns.append(dict(fit_id=fit_id, phase="all", unit=field, observed=value, limit=limit))
        outcomes.append(dict(**fit, state=state, started_attempts=len(owned),
                             unresolved_attempts=unresolved, missing_cost_phases=missing_phases,
                             missing_components=missing_components, costs=costs, submitted_units=submitted,
                             retained_adverse_attempts=[x["attempt_id"] for x in finished if x["status"] != "completed"]))
    if any(count > 1 for count in models.values()):
        blockers.append("trained_model_identity_reused")
    costs = _cost_summary(list(terminals.values()))
    missing_terminals = len(set(starts) - set(terminals))
    unresolved_count = sum(len(row["unresolved_attempts"]) for row in outcomes)
    missing_native = sum(e["native_receipt_sha256"] is None for e in events)
    if missing_native:
        blockers.append("missing_native_receipt_bindings")
    if any(row["state"] != "completed" for row in outcomes):
        blockers.append("independent_training_roster_incomplete")
    if unresolved_count:
        blockers.append("unresolved_started_attempts")
    if overruns:
        blockers.append("cumulative_budget_or_cost_overrun")
    if (not terminals or unresolved_count or any(costs["unknown_terminal_fields"].values())
            or any(row["missing_cost_phases"] or row["missing_components"] for row in outcomes)):
        blockers.append("complete_physical_cost_unknown")
    return {"schema": "hcsn-regenerative-registry-audit-v1", "study_id": plan["study_id"],
            "registration": "UNREGISTERED", "plan_digest": digest, "events_digest": canonical_digest(events),
            "status": "FAILED_BUDGET" if overruns else "HOLD", "expected_training_fits": len(roster),
            "episode_seeds_per_source": len(plan["episode_seeds"]), "fits": outcomes,
            "original_campaign_completion_credit": 0, "ndu_factorial_completion_credit": 0,
            "costs": dict(costs, unresolved_attempts=unresolved_count, missing_terminal_attempts=missing_terminals,
                          no_attempt_is_not_measured_zero=not starts,
                          scope="declared disjoint resource intervals; external completeness and meters unverified"),
            "overruns": overruns, "blockers": sorted(set(blockers)),
            "native_receipt_authentication": "NOT_IMPLEMENTED", "deployment_cost_gate": "HOLD",
            "scientific_benefit_established": False, "scaling_gate": "HOLD", "adoption_authorized": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--expected-plan-digest")
    args = parser.parse_args(argv)
    if args.draft:
        if any((args.plan, args.events, args.expected_plan_digest)):
            parser.error("--draft cannot audit input files")
        print(json.dumps(proposed_plan(), indent=2, sort_keys=True))
        return 0
    if not all((args.plan, args.events, args.expected_plan_digest)):
        parser.error("--plan, --events and --expected-plan-digest are required")
    try:
        report = audit_registry(strict_json(args.plan.read_text(encoding="utf-8")),
                                strict_json(args.events.read_text(encoding="utf-8")), args.expected_plan_digest)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 3 if report["status"] == "HOLD" else 2


if __name__ == "__main__":
    raise SystemExit(main())
