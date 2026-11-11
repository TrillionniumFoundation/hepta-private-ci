"""Readback checks for the actual strong-control request/parameter/cost population."""

import hashlib
import json

import numpy as np

from study_data import FrozenRun, canonical_bytes, make_data
from study_model import features, summarize
from strong_control import ARMS, adjudicate, budget, verify_training_cost


def audit_trial(run, plan, source_digest):
    if run["status"] != "completed":
        raise ValueError("only complete trials can be audited as completed")
    data = make_data(plan, run["seed"], run["scenario"])
    frozen = FrozenRun.freeze(plan, data, source_digest)
    if run["preregistration_digest"] != frozen.commitment or run["data"] != json.loads(frozen.manifest_json):
        raise ValueError("data or plan commitment mismatch")
    if set(run["arms"]) != set(ARMS):
        raise ValueError("arm denominator changed")
    parent = np.array(run["demand"]["parent_model"]["experts"][0]["weights"], dtype=np.float64)
    for name, arm in run["arms"].items():
        payload = arm["model"]
        weights = np.array(payload["weights"] if name == "unsplit_selective" else [
            value for expert in payload["experts"] for value in expert["weights"]], dtype=np.float64)
        if weights.shape != (12,) or not np.isfinite(weights).all() or weights[:6].tobytes() != parent.tobytes():
            raise ValueError("capacity or old-task retention mismatch")
        if arm["parameter_digest"] != hashlib.sha256(weights.tobytes()).hexdigest():
            raise ValueError("parameter digest mismatch")
        if arm["initial_parent_digest"] != hashlib.sha256(parent.tobytes()).hexdigest():
            raise ValueError("initial parent identity mismatch")
        if (arm["parameter_bytes"] != weights.nbytes
                or arm["budget"] != budget(plan, run["demand"]["propose_child"])
                or not verify_training_cost(run, arm, plan)):
            raise ValueError("training budget or executed ledger mismatch")
        for split in ("validation", "test"):
            batch = data[split]
            observation = arm["observations"][split]
            records = observation["records"]
            if observation["split"] != split or [r["id"] for r in records] != list(batch.ids):
                raise ValueError("request denominator changed")
            base = features(batch, "shared")
            if name == "unsplit_selective":
                gate = batch.task[:, None]
                predicted = np.column_stack((base * (1 - gate), base * gate)) @ weights
            else:
                predicted = np.empty(len(batch.ids), dtype=np.float64)
                for task in (0, 1):
                    rows = batch.task == task
                    predicted[rows] = base[rows] @ weights[task * 6:(task + 1) * 6]
            # Match the declared vector square kernel exactly; scalar **2 may differ by one ULP.
            squared_errors = (predicted - batch.y) ** 2
            for index, record in enumerate(records):
                if (record["task"] != int(batch.task[index]) or record["target"] != float(batch.y[index])
                        or record["status"] != "completed" or record["reason"] is not None
                        or record["prediction"] != float(predicted[index])
                        or record["squared_error"] != float(squared_errors[index])):
                    raise ValueError("request value differs from the saved model/data")
            for key, selected in (("summary", records),
                                  ("old_task", [r for r in records if r["task"] == 0]),
                                  ("new_task", [r for r in records if r["task"] == 1])):
                if canonical_bytes(observation[key]) != canonical_bytes(summarize(selected)):
                    raise ValueError("metric summary differs from full request population")
        if not arm["roundtrip_exact"]:
            raise ValueError("incomplete model readback")
    if run["decision"] != adjudicate(run, plan):
        raise ValueError("decision does not follow frozen gain/retention conditions")
    return {"verified_requests": len(ARMS) * sum(len(data[s].ids) for s in ("validation", "test")),
            "scientific_decision": run["decision"]["decision"], "production_authority": False}
