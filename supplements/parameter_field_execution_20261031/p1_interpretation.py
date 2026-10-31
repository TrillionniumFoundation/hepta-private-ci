"""Interpret already sealed B/C intervals; no fitting, bootstrap, scoring or I/O.

The caller must pass the original verified postseal analysis and separately scoped
evidence statuses. This module annotates existing comparisons and never replaces
their registered gates or grants adoption. Missing evidence is not a null effect.
"""

from copy import deepcopy
import math


OBSERVERS = ("reward", "audit")
B_EFFECTS = (
    "ordinary-frozen task", "field-ordinary task", "field-history task",
    "full-state-field task", "ordinary-frozen clean", "field-frozen clean",
    "full-state-frozen clean", "history-frozen clean",
    "fixed-taper-field task (secondary)", "fixed-taper-frozen clean (secondary)",
)
C_EFFECTS = (
    "interaction task", "dual field increment task", "ordinary field increment task",
    "dual-field minus ordinary-field task", "ordinary-baseline minus warmstart clean",
    "ordinary-field minus warmstart clean", "dual-baseline minus warmstart clean",
    "dual-field minus warmstart clean",
)
CONTEXT_STATUSES = {
    "integrity": {"passed", "failed", "unknown"},
    "activity": {"parameter_optimizer_change_observed", "whole_state_change_only",
                 "registered_inactive", "unknown"},
    "cost_coverage": {"complete", "partial", "unknown"},
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _effect(name, row):
    threshold = -.01 if "clean" in name else .001 if name == "field-ordinary task" else 0.
    result = {"threshold": threshold,
              "threshold_meaning": "registered retention margin" if "clean" in name
              else "registered minimum field gain" if name == "field-ordinary task"
              else "zero in the original contrast direction",
              "per_observer": {}, "status": "missing", "original_effect": deepcopy(row)}
    if row is None:
        return result
    _require(type(row) is dict, "Effect must be a mapping")
    for observer in OBSERVERS:
        point = row.get("point", {}).get(observer)
        interval = row.get("ci", {}).get(observer)
        if point is None or interval is None:
            result["per_observer"][observer] = "missing"
            continue
        _require(_finite(point) and type(interval) in (list, tuple) and len(interval) == 2
                 and all(_finite(v) for v in interval) and interval[0] <= interval[1],
                 "Malformed original point or interval: " + name + "/" + observer)
        result["per_observer"][observer] = (
            "above_threshold" if interval[0] > threshold else
            "below_threshold" if interval[1] < threshold else "inconclusive")
    states = set(result["per_observer"].values())
    if "missing" in states:
        result["status"] = "missing"
    elif states == {"above_threshold"}:
        result["status"] = "supported_both_observers"
    elif states == {"below_threshold"}:
        result["status"] = "below_threshold_both_observers"
    elif states == {"above_threshold", "below_threshold"}:
        result["status"] = "observer_conflict"
    else:
        result["status"] = "inconclusive"
    return result


def interpret(stage, formal_analysis=None, *, evidence_context=None):
    """Annotate original contrasts without new inference or benefit admission.

    Context entries have ``status`` and a nonempty ``scope`` when known; optional
    evidence references are retained. Their provenance is the caller's postseal
    responsibility. In particular, A calibration activity is not C deployment
    activity, and complete current costs are not complete historical costs.
    """
    _require(stage in ("B", "C"), "Only registered B/C analyses are supported")
    names = B_EFFECTS if stage == "B" else C_EFFECTS
    context = {}
    supplied = evidence_context or {}
    _require(type(supplied) is dict and set(supplied) <= set(CONTEXT_STATUSES),
             "Unknown evidence context category")
    for key, allowed in CONTEXT_STATUSES.items():
        item = deepcopy(supplied.get(key, {"status": "unknown", "scope": "not supplied"}))
        _require(type(item) is dict and item.get("status") in allowed
                 and type(item.get("scope")) is str and bool(item["scope"].strip()),
                 "Evidence needs an explicit status and scope: " + key)
        context[key] = item
    if formal_analysis is None:
        formal = {}
    else:
        _require(type(formal_analysis) is dict, "Analysis must be a mapping or None")
        formal = formal_analysis
        _require(formal.get("stage", stage) == stage, "Analysis stage differs")
        _require(formal.get("formal_family") == list(names), "Registered comparison family differs")
        _require(formal.get("seeds") == ([17, 29, 43] if stage == "B" else list(range(801, 809))),
                 "Registered fixed models or paired seeds differ")
        _require(formal.get("observers") == list(OBSERVERS), "Registered observers differ")
    original_effects = formal.get("effects", {})
    _require(type(original_effects) is dict and set(original_effects) <= set(names),
             "Unexpected effect; this supplement cannot expand the family")
    effects = {name: _effect(name, original_effects.get(name)) for name in names}
    missing = [name for name, effect in effects.items() if effect["status"] == "missing"]
    thresholds = deepcopy(formal.get("statistical_thresholds"))
    _require(thresholds is None or type(thresholds) is dict, "Malformed original gates")
    original_gate_status = "missing" if thresholds is None else "retained_without_redefinition"
    if stage == "C":
        dual = effects["dual field increment task"]["status"]
        ordinary = effects["ordinary field increment task"]["status"]
        interaction = effects["interaction task"]["status"]
        if "missing" in (dual, ordinary, interaction):
            relationship = "missing"
        elif interaction == "supported_both_observers":
            if dual == ordinary == "below_threshold_both_observers":
                relationship = "positive_interaction_with_two_negative_simple_effects_less_harm"
            elif dual == "supported_both_observers":
                relationship = "positive_interaction_and_positive_dual_increment"
            else:
                relationship = "positive_interaction_without_established_positive_dual_increment"
        elif dual == "supported_both_observers":
            relationship = "positive_dual_increment_without_established_positive_interaction"
        else:
            relationship = "no_joint_positive_interaction_and_dual_increment_established"
        scope = ("The interaction is dual increment minus ordinary increment. Its registered gate "
                 "does not require a positive dual increment. Separate simple-effect intervals, "
                 "the cross-architecture contrast, and all four own-warmstart retention intervals "
                 "remain visible. Non-significance is not equivalence.")
    else:
        relationship = "registered_directional_contrasts_reported_separately"
        scope = ("The full-current-state head is a learned estimator, not an information oracle; "
                 "history pays its H12 observation cost. A positive fixed-taper-field contrast "
                 "favors taper. The original field gate also requires nonnegative per-model "
                 "points and does not include taper or full-cost Pareto admission.")
    if context["integrity"]["status"] == "failed":
        status = "integrity_blocked"
    elif formal_analysis is None:
        status = "missing_analysis"
    elif missing or thresholds is None:
        status = "incomplete_analysis"
    elif context["integrity"]["status"] == "unknown":
        status = "integrity_not_established"
    else:
        status = "descriptive_complete"
    return {
        "schema": "hepta.parameter-field.p1-interpretation.1", "stage": stage, "status": status,
        "requires_verified_postseal_inputs": True, "effects": effects, "missing_effects": missing,
        "registered_statistical_thresholds": thresholds, "registered_gate_status": original_gate_status,
        "statistical_relationship": relationship, "interpretation_scope": scope,
        "evidence_context": context, "evidence_context_inferred_from_intervals": False,
        "observer_scope": "Both reported observers are checked; no new simultaneous cross-observer coverage claim.",
        "activity_scope": "Intended or accepted overrides alone do not prove parameter/optimizer change or benefit.",
        "cost_scope": "Keep supplied cost coverage scope; partial or unknown costs never become zero. No price or amortization horizon is fitted.",
        "adoption": "not_assessed", "unconditional_net_benefit": "not_assessed",
        "new_bootstrap_or_threshold": False, "new_independent_samples": 0,
        "new_training_scoring_refitting": False,
    }
