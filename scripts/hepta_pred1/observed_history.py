"""Recover a decision's exact retained history without rewriting old artifacts.

Snapshot, frozen decision and joined effect must all be supplied and pinned by
the caller. These checks establish structural consistency, never native owner,
clock, encoder, effect-observer or logging-policy authentication.
"""

from dataclasses import asdict
import math

from .native_ledger import Artifact, _require, _snapshot
from .observed_evaluation import UtilityContract, validate_forecast
from .owner_bridge import (
    model_row, observed_from_artifact, owner_information_digest, target_schema_digest,
)

MAX_HISTORY_STEPS = 256


def history_model_row(sample, decision, snapshot):
    """Bind all observed history, including arrival order, to one chosen action.

    A missing original snapshot is an error. The final row is never duplicated
    to manufacture a sequence. Evidence bounds and witnesses survive alongside
    the legacy complete-case target projection, including excluded observations.
    """
    _require(all(isinstance(a, Artifact) for a in (sample, decision, snapshot)),
             "three immutable source artifacts required")
    p, d, s = sample.payload, decision.payload, _snapshot(snapshot)
    observed = observed_from_artifact(sample)
    _require(d.get("schema") == "pred1-prospective-owner-decision-v1",
             "wrong frozen decision schema")
    _require(p["decision_digest"] == observed.sample_id == decision.digest,
             "sample decision binding differs")
    _require(p["snapshot_digest"] == d["snapshot_digest"] == snapshot.digest,
             "sample snapshot binding differs")
    _require(p["identity"] == d["identity"] == s["identity"], "owner identity differs")
    _require(observed.clock_id == d["clock_id"] == s["clock_id"], "history clock differs")
    _require(d["snapshot_cursor"] == s["cursor"], "history cursor differs")
    _require(d["input_cutoff"] == s["decision_at"] <= d["prediction_at"] <= d["decision_at"],
             "history cutoff differs")
    _require(not s["collection"]["rows"]["attempts"], "dispatch already visible at cutoff")
    _require(p["feature_names"] == d["feature_names"] == s["feature_names"],
             "history feature schema differs")
    _require(p["features"] == d["features"] == s["features"][-1],
             "retained final feature row differs")
    for key in ("task_group", "split", "chosen_action", "policy_id", "source",
                "prediction_at", "decision_at", "information_set_digest",
                "budget_contract_digest"):
        _require(getattr(observed, key) == d[key], "frozen decision field differs: " + key)
    actions = d["action_order"]
    _require(type(actions) is list and set(actions) == set(d["predictions"])
             and observed.chosen_action in actions, "frozen action panel differs")
    contract = UtilityContract(**d["utility_contract"])
    _require(contract.digest == observed.budget_contract_digest, "frozen utility contract differs")
    target = target_schema_digest(d["success_definition"], contract.cost_unit)
    _require(p["target_schema_sha256"] == d["target_schema_sha256"] == target
             and p["cost_unit"] == contract.cost_unit
             and p["success_definition"] == d["success_definition"], "target semantics differ")
    _require(owner_information_digest(snapshot, actions, contract, d["success_definition"])
             == observed.information_set_digest, "frozen information commitment differs")
    _require(validate_forecast(d["predictions"][observed.chosen_action])
             == validate_forecast(observed.prediction), "original chosen forecast differs")
    return {
        **model_row(sample),
        "history": s["features"],
        "history_binding": {
            "snapshot_sha256": snapshot.digest, "decision_sha256": decision.digest,
            "sample_sha256": sample.digest, "clock_id": s["clock_id"],
            "arrival_cursor": s["cursor"], "input_cutoff": s["decision_at"],
            "event_references": s["event_references"],
            "source_provenance_authenticated": False,
        },
        "evidence": asdict(observed.evidence),
    }


def summarize_history(history, feature_names):
    """A fixed small-MLP baseline: final row, all-row means and observed length.

    Both MLP and GRU receive the same frozen history. This declared lossy summary
    does not preserve order; a GRU comparison also tests that representation
    choice. No truncation, padding, held-out normalization or learned selection.
    Native snapshot schemas have at most 106 features, so this remains bounded.
    """
    _require(type(feature_names) is list and 1 <= len(feature_names) <= 127
             and len(set(feature_names)) == len(feature_names)
             and all(type(n) is str and 0 < len(n) <= 256 for n in feature_names),
             "invalid bounded history feature names")
    _require(type(history) is list and 1 <= len(history) <= MAX_HISTORY_STEPS,
             "need 1..256 observed history rows")
    for row in history:
        _require(type(row) is list and len(row) == len(feature_names)
                 and all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1
                         for x in row), "invalid numerical history")
    length = len(history)
    means = [math.fsum(row[i] for row in history) / length for i in range(len(feature_names))]
    values = history[-1] + means + [length / MAX_HISTORY_STEPS]
    names = ["last:" + name for name in feature_names]
    names += ["mean:" + name for name in feature_names] + ["observed_length/256"]
    return values, names


def summary_model_row(row, feature_names):
    """Keep the full input/evidence commitment while exposing the fixed summary."""
    values, _ = summarize_history(row["history"], feature_names)
    _require(row["features"] == row["history"][-1], "summary last row differs")
    return {**row, "features": values}
