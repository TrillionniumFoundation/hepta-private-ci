"""Replay synthetic observations and verify frozen source, data and cost populations."""

from dataclasses import asdict
import hashlib
import math
from pathlib import Path

import numpy as np

from study_cost import audit_cost, audit_stages, expected_events, total_cost
from study_data import ARMS, SOURCE_FILES, digest, make_data
from study_model import Model, features, predict_routed, summarize


def audit_observation(observation, manifest):
    records = observation["records"]
    if [r["id"] for r in records] != manifest["ids"] or len(records) != manifest["requests"]:
        raise ValueError("original request denominator or identities changed")
    if digest([[r["id"], r["task"], r["target"]] for r in records]) != manifest["target_digest"]:
        raise ValueError("evaluation targets or task membership changed")
    for row in records:
        if row["status"] == "completed":
            prediction, target, loss = row["prediction"], row["target"], row["squared_error"]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (prediction, target, loss)):
                raise ValueError("completed request lacks a finite independent observation")
            if not math.isclose(loss, (prediction - target) ** 2, rel_tol=1e-12, abs_tol=1e-15):
                raise ValueError("loss does not match observed prediction and target")
        elif row["status"] in ("failed", "incomplete"):
            if row["squared_error"] is not None or not row["reason"]:
                raise ValueError("uncompleted requests cannot receive an invented zero loss")
        else:
            raise ValueError("unknown outcome status")
    expected = {"summary": summarize(records),
                "old_task": summarize([r for r in records if r["task"] == 0]),
                "new_task": summarize([r for r in records if r["task"] == 1])}
    if any(observation[k] != value for k, value in expected.items()):
        raise ValueError("summary does not preserve the observed population")


def audit_predictions(observation, batch, payload):
    if payload is None:
        if any(r["status"] == "completed" for r in observation["records"]):
            raise ValueError("missing model cannot claim completed predictions")
        return
    model = Model.restore(payload)
    if not any(row["status"] == "completed" for row in observation["records"]):
        return
    if model.router == "shared":
        assignments = np.zeros(len(batch.ids), dtype=np.int64)
    elif model.router == "task":
        assignments = batch.task
    else:
        assignments = np.array([hashlib.sha256((model.salt + "/" + i).encode()).digest()[0] % 2 for i in batch.ids])
    predictions, _ = predict_routed(batch, model, assignments)
    for row, prediction in zip(observation["records"], predictions, strict=True):
        if row["status"] == "completed" and not math.isclose(row["prediction"], float(prediction), rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("reported prediction was not produced by the committed model")


def audit_demand(evidence, data, plan, incumbent_payload):
    if evidence["parent_model"] != incumbent_payload:
        raise ValueError("monitoring did not observe the actual frozen incumbent")
    if evidence.get("failure") is not None:
        if any(evidence.get(k) for k in ("persistent_demand", "negative_transfer_observed", "propose_child")):
            raise ValueError("failed demand diagnosis cannot propose a child")
        for name in ("before", "probe"):
            audit_observation(evidence[name], data["monitor"].manifest())
            audit_predictions(evidence[name], data["monitor"], None)
        return False
    for name, payload in (("before", evidence["parent_model"]), ("probe", evidence["probe_model"])):
        audit_observation(evidence[name], data["monitor"].manifest())
        audit_predictions(evidence[name], data["monitor"], payload)
    parent = Model.restore(incumbent_payload).experts[0]
    rows = data["train"].task == 1
    phi = features(data["train"], "shared", rows)
    gradient = phi.T @ (phi @ parent.weights - data["train"].y[rows]) / rows.sum()
    expected_probe = parent.weights - plan.learning_rate * gradient
    probe = Model.restore(evidence["probe_model"])
    if probe.router != "shared" or probe.experts[0].mode != "shared" or not np.array_equal(probe.experts[0].weights, expected_probe):
        raise ValueError("negative-transfer probe differs from its frozen training intervention")
    window_mse = []
    records = evidence["before"]["records"]
    for window in range(plan.monitoring_windows):
        selected = [r for j, r in enumerate(records) if r["task"] == 1 and data["monitor"].window[j] == window]
        window_mse.append(summarize(selected)["mse"])
        if len(selected) != plan.monitor_per_task_per_window:
            raise ValueError("monitoring window population changed")
    before = evidence["before"]["old_task"]["mse"]
    after = evidence["probe"]["old_task"]["mse"]
    regression = None if before is None or after is None else after - before
    persistent = all(m is not None and m >= plan.policy.persistent_window_mse for m in window_mse)
    negative = regression is not None and regression >= plan.policy.negative_transfer_mse_increase
    expected = {
        "window_new_task_mse": window_mse, "window_requests": plan.monitor_per_task_per_window,
        "old_task_probe_mse_increase": regression, "persistent_demand": persistent,
        "negative_transfer_observed": negative, "propose_child": persistent and negative,
        "training_evidence_splits": ["pretrain", "train", "monitor"],
    }
    if any(evidence[key] != value for key, value in expected.items()):
        raise ValueError("demand diagnosis was not derived from the frozen raw observations")
    return persistent and negative


def audit_migration(arm, validation):
    migration = arm["migration"]
    if migration["requests"] != len(validation.ids):
        raise ValueError("migration omitted planned validation requests")
    if migration["parameter_digest"] != arm["model_digest"]:
        raise ValueError("migration source is not the evaluated model")
    audit_observation(migration["after"], validation.manifest())
    if migration.get("failure") is not None or arm["model"] is None:
        if migration["exact_validation_behavior"]:
            raise ValueError("failed migration cannot claim successful behavior")
        audit_predictions(migration["after"], validation, None)
        return
    if migration["roundtrip_digest"] != digest(migration["roundtrip_model"]):
        raise ValueError("migration parameters do not match their digest")
    audit_predictions(migration["after"], validation, migration["roundtrip_model"])
    planned = len(validation.ids)
    complete = all(observation["summary"]["requested"] == planned
                   and observation["summary"]["completed"] == planned
                   for observation in (arm["validation"], migration["after"]))
    matches = (complete and migration["parameter_digest"] == migration["roundtrip_digest"]
               and migration["after"]["records"] == arm["validation"]["records"])
    if migration["exact_validation_behavior"] != matches:
        raise ValueError("migration conclusion disagrees with actual post-migration behavior")


def audit_run(run, plan, source_digest):
    # A self-consistent rewritten manifest is insufficient: regenerate from the frozen equations.
    data = make_data(plan, run["seed"], run["scenario"])
    if run["data"] != {s: b.manifest() for s, b in data.items()}:
        raise ValueError("data manifest differs from the preregistered experiment")
    expected_commitment = digest({"plan": asdict(plan), "source": source_digest, "data": run["data"]})
    if run["preregistration_digest"] != expected_commitment:
        raise ValueError("plan/source/data commitment changed")
    if set(run["arms"]) != set(ARMS):
        raise ValueError("a preregistered comparison arm is missing or replaced")
    incumbent = run["incumbent_model"]
    if incumbent is not None:
        model = Model.restore(incumbent)
        if model.router != "shared" or model.experts[0].mode != "shared" or model.salt:
            raise ValueError("incumbent differs from the frozen parent family")
    proposal = audit_demand(run["demand_evidence"], data, plan, incumbent)
    incumbent_digest = None if incumbent is None else digest(incumbent)
    if (run["incumbent_digest_before_training"] != incumbent_digest
            or run["incumbent_digest_after_training"] != incumbent_digest):
        raise ValueError("incumbent changed during candidate training")
    audit_cost(run["shared_ledger"], frozenset(("train",)))
    audit_stages(run["shared_ledger"], expected_events("shared", None, data, plan, proposal, run["seed"]))
    for name in ARMS:
        arm = run["arms"][name]
        payload = arm["model"]
        expected_router = ("random" if name == "random_grouping" else "task"
                           if name == "fixed_experts" or name == "demand_specialization" and proposal else "shared")
        expected_modes = ["expanded" if name == "expanded_monolith" else "shared"] * (1 if expected_router == "shared" else 2)
        if payload is None:
            if not arm["failure"] or arm["model_digest"] is not None or arm["expert_instances"] != 0:
                raise ValueError("unavailable learner has no explicit failed state")
        else:
            if (payload["router"] != expected_router or [m["mode"] for m in payload["experts"]] != expected_modes
                    or payload["salt"] != (f"precommitted-random/{run['seed']}" if expected_router == "random" else "")):
                raise ValueError("arm differs from its preregistered model/router family")
            if digest(payload) != arm["model_digest"] or arm["expert_instances"] != len(payload["experts"]):
                raise ValueError("model bytes or population do not match their commitment")
            if name == "frozen_incumbent" and payload != incumbent:
                raise ValueError("frozen comparison arm changed the incumbent")
            if name == "demand_specialization" and payload["experts"][0] != incumbent["experts"][0]:
                raise ValueError("differentiation overwrote its compatible parent")
        for split in ("validation", "test"):
            audit_observation(arm[split], run["data"][split])
            audit_predictions(arm[split], data[split], payload)
        audit_migration(arm, data["validation"])
        audit_cost(arm["ledger"])
        audit_stages(arm["ledger"], expected_events(name, payload, data, plan, proposal, run["seed"]))
        if arm["cost"] != total_cost(run["shared_ledger"] + arm["ledger"]):
            raise ValueError("cost totals omit or alter an instrumented stage")
    if run["execution_order"] != ["freeze_plan_and_data", "pretrain_incumbent", "diagnose_train_and_monitor",
                                  "train_all_arms", "validate_all_arms", "snapshot_and_migrate_all_arms", "test_all_arms"]:
        raise ValueError("evaluation preceded completion of all training")


def audit_source(report):
    directory = Path(__file__).resolve().parent
    actual = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    if report["source_files"] != actual or report["source_digest"] != digest(actual):
        raise ValueError("source manifest does not match the executed local files")
