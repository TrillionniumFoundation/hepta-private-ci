"""Freeze a prospective choice, then join a separately supplied effect witness.

All provenance remains operator-declared. Hashes bind bytes and identities;
they cannot authenticate an owner, observer, clock or randomized assignment.
The bridge never dispatches an action or manufactures labels from settlement.
"""

from dataclasses import asdict
from hashlib import sha256
from time import monotonic, perf_counter, process_time

from .contracts import Evidence, ObservationStatus
from .native_ledger import (
    Artifact,
    _canonical,
    _collection,
    _digest,
    _require,
    _snapshot,
    _text,
    _time,
)
from .observed_evaluation import (
    ObservedDecision, UtilityContract, observed_to_dict, validate_forecast,
)


def target_schema_digest(success_definition, cost_unit):
    """Bind quality meaning and continuous physical units across all readbacks."""
    _text(success_definition)
    _text(cost_unit)
    return sha256(_canonical({"success_definition": success_definition,
                              "duration_unit": "seconds", "cost_unit": cost_unit})).hexdigest()


def owner_information_digest(snapshot, actions, contract, success_definition):
    """Hash actual frozen numerical inputs, ordered legal actions and semantics.

    Exact equality is deliberately conservative, including measured timing
    features. This is not proof of equal external environments or task replicas.
    """
    p = _snapshot(snapshot)
    _require(type(actions) is list and 1 <= len(actions) <= 64 and len(set(actions)) == len(actions), "invalid legal action set")
    for action in actions:
        _text(action)
        _require("action:" + action in p["feature_names"], "action is outside frozen feature schema")
    return sha256(_canonical({
        "feature_names": p["feature_names"], "features": p["features"],
        "actions": actions, "budget_contract_digest": contract.digest,
        "target_schema_sha256": target_schema_digest(success_definition, contract.cost_unit),
    })).hexdigest()


def freeze_owner_decision(
    path, snapshot_path, *, predictions, chosen_action, policy_id, model_sha256,
    task_group, split, information_set_digest, contract, prediction_at, decision_at,
    success_definition, source="fixture", inference_meter=None, expected_snapshot_sha256=None,
):
    """Commit the prediction and chosen action before this identity is dispatched.

    snapshot.decision_at is the input cutoff; decision_at is the later actual
    choice time after inference. Both use the same host monotonic clock.
    """
    snapshot = Artifact.read(snapshot_path)
    if expected_snapshot_sha256 is not None:
        _require(snapshot.digest == expected_snapshot_sha256, "inference snapshot bytes changed")
    p = _snapshot(snapshot)
    _require(isinstance(contract, UtilityContract), "explicit utility contract required")
    target_digest = target_schema_digest(success_definition, contract.cost_unit)
    _require(not p["collection"]["rows"]["attempts"], "attempt already visible; not prospective")
    _digest(model_sha256)
    _digest(information_set_digest)
    _text(policy_id)
    _text(task_group)
    _require(split in ("train", "dev", "confirm"), "invalid split")
    _require(source in ("fixture", "declared_owner"), "invalid observation source")
    _time(prediction_at)
    _time(decision_at)
    _require(p["decision_at"] <= prediction_at <= decision_at, "prediction cutoff/order differs")
    _require(type(predictions) is dict and 1 <= len(predictions) <= 64, "bounded candidate predictions required")
    _require(chosen_action in predictions, "chosen action has no prediction")
    actual_information = owner_information_digest(snapshot, list(predictions), contract, success_definition)
    _require(information_set_digest == actual_information, "declared information differs from frozen numeric inputs")
    for action, prediction in predictions.items():
        _text(action)
        validate_forecast(prediction)
    artifact = Artifact.make({
        "schema": "pred1-prospective-owner-decision-v1",
        "identity": p["identity"], "snapshot_digest": snapshot.digest,
        "snapshot_cursor": p["cursor"], "clock_id": p["clock_id"],
        "input_cutoff": p["decision_at"], "prediction_at": prediction_at,
        "decision_at": decision_at, "predictions": predictions,
        "action_order": list(predictions), "inference_meter": inference_meter,
        "chosen_action": chosen_action, "policy_id": policy_id,
        "model_sha256": model_sha256, "task_group": task_group, "split": split,
        "information_set_digest": information_set_digest,
        "information_scope": "exact frozen numeric history and ordered legal actions, target and budget",
        "utility_contract": asdict(contract), "budget_contract_digest": contract.digest,
        "success_definition": success_definition, "target_schema_sha256": target_digest,
        "feature_names": p["feature_names"], "features": p["features"][-1],
        "source": source, "source_provenance_authenticated": False,
        "scope": "prospective one-step choice; action execution remains with the owner",
    })
    artifact.save(path)
    return artifact


def predict_owner_choice(path, snapshot_path, checkpoint_path, *, expected_sha256,
                         task_group, split, contract, inference_cost, source="fixture"):
    """Actually load/score/freeze one panel; the native owner retains execution.

    Input snapshot and clock must belong to this process's host clock domain.
    The host supplies a nonnegative charge in contract.cost_unit; it is not an
    automatic energy or financial-cost measurement.
    """
    from .observed_models import ObservedModel
    from .observed_policy import choose_fixed1

    started_at, wall, cpu = monotonic(), perf_counter(), process_time()
    snapshot = Artifact.read(snapshot_path)
    p = _snapshot(snapshot)
    _require(p["decision_at"] <= started_at, "snapshot is from a future clock")
    model = ObservedModel.load(checkpoint_path, expected_sha256=expected_sha256)
    _require(model.metadata["feature_names"] == p["feature_names"] and
             model.metadata["feature_encoding"] == "last_observed_row", "model feature schema differs")
    _require(model.metadata["cost_unit"] == contract.cost_unit, "model cost unit differs")
    predictions = {action: model.predict(p["features"][-1], action) for action in model.metadata["action_ids"]}
    prediction_at = monotonic()
    elapsed = perf_counter() - wall
    choice = choose_fixed1(predictions, contract, preparation_seconds=elapsed, preparation_cost=inference_cost)
    meter = {"started_at": started_at, "wall_seconds": elapsed,
             "process_cpu_seconds": process_time() - cpu, "declared_resource_cost": inference_cost,
             "head_calls": len(predictions), "horizon": 1, "physical_cost_complete": False,
             "scope": "snapshot/checkpoint read and validation plus one panel; excludes freeze serialization"}
    return freeze_owner_decision(
        path, snapshot_path, predictions=predictions, chosen_action=choice["chosen_action"],
        policy_id=model.metadata["kind"] + ":Fixed1", model_sha256=expected_sha256,
        task_group=task_group, split=split,
        information_set_digest=owner_information_digest(snapshot, list(predictions), contract, model.metadata["success_definition"]),
        contract=contract, prediction_at=prediction_at, decision_at=monotonic(),
        success_definition=model.metadata["success_definition"], source=source, inference_meter=meter,
        expected_snapshot_sha256=snapshot.digest,
    )


def join_owner_effect(path, decision_path, owner_collection, effect):
    """Join independent effect evidence; owner settlement never supplies a label.

    effect is an immutable host/observer artifact. A cancel request without
    execution remains an unexecuted observation, not a failed action.
    """
    decision = Artifact.read(decision_path)
    p = decision.payload
    _require(p.get("schema") == "pred1-prospective-owner-decision-v1", "wrong decision schema")
    _require(type(p["action_order"]) is list and len(set(p["action_order"])) == len(p["action_order"])
             and set(p["action_order"]) == set(p["predictions"]), "retained action order differs")
    c = _collection(owner_collection)
    _require(isinstance(effect, Artifact), "immutable effect artifact required")
    e = effect.payload
    required = {
        "schema", "target_domain", "decision_digest", "snapshot_digest", "identity",
        "clock_id", "chosen_action", "executed_action", "executed_at", "execution_ref",
        "observer_ref", "evidence", "costs", "full_wall_seconds", "source",
        "target_schema_sha256",
    }
    _require(set(e) == required and e["schema"] == "pred1-independent-effect-v1", "effect fields differ")
    _require(e["target_domain"] == "independent_task_effect", "owner settlement is not task effect")
    _require(e["target_schema_sha256"] == p["target_schema_sha256"] == target_schema_digest(p["success_definition"], p["utility_contract"]["cost_unit"]), "effect target definition differs")
    _require(p["identity"] == c["identity"] == e["identity"], "effect owner identity differs")
    _require(p["clock_id"] == c["clock_id"] == e["clock_id"], "effect clock differs")
    _require(e["decision_digest"] == decision.digest and e["snapshot_digest"] == p["snapshot_digest"], "effect decision binding differs")
    _require(c["cursor"] > p["snapshot_cursor"] and c["available_at"] >= p["decision_at"], "owner readback is not later")
    _require(e["chosen_action"] == p["chosen_action"] and e["source"] == p["source"], "effect action/source differs")
    _text(e["observer_ref"])
    evidence = Evidence(**e["evidence"])
    _require(evidence.source.value == "real", "native bridge requires declared real evidence")
    _require(p["decision_at"] <= evidence.observed_at, "effect predates decision")
    if e["executed_action"] is None:
        _require(e["executed_at"] is None and e["execution_ref"] is None, "unexecuted action has execution facts")
        _require(evidence.observation_status != ObservationStatus.TERMINAL, "unexecuted action cannot have terminal effect")
        _require(evidence.time_kind.value == "unobserved" and evidence.nonoccurrence_witness is None, "unexecuted action has no effect-time origin")
    else:
        _require(e["executed_action"] == p["chosen_action"], "executed action differs from choice")
        _require(bool(c["rows"]["attempts"]), "executed action lacks native dispatch attempt")
        _text(e["execution_ref"])
        _time(e["executed_at"])
        _require(p["decision_at"] <= e["executed_at"] <= evidence.observed_at, "execution is outside the observed interval")
        if evidence.time_lower is not None:
            _require(e["executed_at"] + evidence.time_lower <= evidence.observed_at, "effect duration exceeds receipt arrival")
    contract = UtilityContract(**p["utility_contract"])
    _require(contract.digest == p["budget_contract_digest"], "utility contract changed")
    meter = p["inference_meter"]
    if meter is not None:
        _require(type(meter) is dict, "invalid inference receipt")
        for name in ("started_at", "wall_seconds", "process_cpu_seconds", "declared_resource_cost"):
            _time(meter[name])
        _require(meter["started_at"] <= p["prediction_at"], "inference clock differs")
        if e["full_wall_seconds"] is not None:
            _require(e["full_wall_seconds"] >= evidence.observed_at - meter["started_at"], "full wall omits measured inference and waiting")
        if e["costs"]["inference"] is not None:
            _require(e["costs"]["inference"] >= meter["declared_resource_cost"], "full ledger omits declared inference charge")
    observed = ObservedDecision(
        sample_id=decision.digest, task_group=p["task_group"], split=p["split"],
        policy_id=p["policy_id"], chosen_action=p["chosen_action"],
        executed_action=e["executed_action"], execution_ref=e["execution_ref"],
        decision_at=p["decision_at"], prediction_at=p["prediction_at"], clock_id=p["clock_id"],
        information_set_digest=p["information_set_digest"], budget_contract_digest=p["budget_contract_digest"],
        prediction=p["predictions"][p["chosen_action"]], evidence=evidence,
        full_wall_seconds=e["full_wall_seconds"], costs=e["costs"], source=p["source"],
    )
    artifact = Artifact.make({
        "schema": "pred1-observed-owner-effect-v1", "observed": observed_to_dict(observed),
        "decision_digest": decision.digest, "snapshot_digest": p["snapshot_digest"],
        "owner_collection_digest": owner_collection.digest, "effect_digest": effect.digest,
        "feature_names": p["feature_names"], "features": p["features"],
        "success_definition": p["success_definition"], "cost_unit": contract.cost_unit,
        "target_schema_sha256": p["target_schema_sha256"],
        "identity": p["identity"], "observer_ref": e["observer_ref"],
        "source_provenance_authenticated": False,
        "scope": "structurally bound operator-declared effect; no counterfactual labels",
    })
    artifact.save(path)
    return artifact


def observed_from_artifact(artifact):
    """Read a retained joined sample; no reclassification of source provenance."""
    p = artifact.payload
    _require(p.get("schema") == "pred1-observed-owner-effect-v1", "wrong observed sample schema")
    row = p["observed"]
    return ObservedDecision(**{**row, "evidence": Evidence(**row["evidence"])})


def model_row(artifact):
    """Keep continuous labels and unknowns for train-only model admission."""
    observation = observed_from_artifact(artifact)
    evidence = observation.evidence
    executed = observation.executed_action == observation.chosen_action and observation.execution_ref is not None
    status = evidence.observation_status.value
    if status == "verified_ongoing":
        status = "right_censored"
    elif status not in ("terminal", "cancel_requested"):
        status = "unknown"
    return {
        "sample_id": observation.sample_id, "task_group": observation.task_group,
        "split": observation.split, "action_id": observation.chosen_action,
        "features": artifact.payload["features"], "source": observation.source,
        "outcome_quality": evidence.outcome if executed else None,
        "duration_seconds": evidence.time_lower if executed and evidence.time_kind.value == "exact" else None,
        "action_cost": evidence.final_cost if executed else None,
        "outcome_status": status if executed or status == "cancel_requested" else "unknown",
        "time_status": evidence.time_kind.value if executed and evidence.time_kind.value in ("exact", "interval") else "unobserved",
        "cost_status": "observed" if executed and evidence.final_cost is not None else "unknown",
    }
