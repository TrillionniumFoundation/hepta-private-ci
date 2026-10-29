"""Paired reference-tail labels and a fixed, independent reconstruction audit.

Every branch starts from the complete in-memory parent state. Persisted branch
evidence is a deterministic reconstruction recipe, hashes and traces; only the
declared warmstarts and endpoints are literal archived tensor checkpoints.
"""

import gzip
import io
import json

import numpy as np

from .architecture_features import FIELD_NAMES, measure
from .architecture_state import digest
from .heads import fit_head, head_metadata


def transition_identity(receipt):
    keys = ("start", "end", "action", "multiplier", "schedule", "before", "candidate",
            "after", "accepted", "guard_delta", "guard_values", "guard_output_sha256",
            "clock_advances", "microsteps")
    return digest({key: receipt[key] for key in keys})


def tail(context, model, optimizer, start, action, schedule):
    trace = []
    for clock in range(start, context.plan.steps, context.plan.macro_steps):
        chosen = action if clock == start else context.plan.baseline
        trace.append(context.block(model, optimizer, clock, chosen, schedule))
    terminal = context.snapshot(model, optimizer)
    scored = context.hard(model, context.probe, "reference_tail")
    return {
        "action": action, "terminal_state_sha256": digest(terminal),
        "terminal_value": scored["mean"], "terminal_values": scored["values"].tolist(),
        "terminal_output_sha256": scored["output_sha256"],
        "transition_sha256": [transition_identity(item) for item in trace],
        "trace": trace,
    }


def build_instance(context, model, optimizer, warmstart, store, destination):
    """Return all 48 rows for one dev architecture/seed, without fitting early."""
    rows, plan = [], context.plan
    context.work.phase = "bank"
    for schedule_index, schedule in enumerate(plan.bank_schedules):
        for prefix in ("baseline", "balanced"):
            context.restore(model, optimizer, warmstart)
            prefix_actions, prefix_hashes = [], []
            for decision, clock in enumerate(range(0, plan.steps, plan.macro_steps)):
                context.resource_check()
                parent = context.snapshot(model, optimizer)
                feature, current, feature_receipt = measure(context, model, optimizer, clock, schedule)
                branches = []
                for action in range(len(plan.multipliers)):
                    context.restore(model, optimizer, parent)
                    branches.append(tail(context, model, optimizer, clock, action, schedule))
                baseline = np.asarray(branches[plan.baseline]["terminal_values"])
                advantages = [float((np.asarray(branch["terminal_values"]) - baseline).mean())
                              for branch in branches]
                if advantages[plan.baseline] != 0.:
                    raise AssertionError("Baseline tail does not cancel itself")
                context.restore(model, optimizer, parent)
                next_action = plan.baseline if prefix == "baseline" else (schedule_index + decision) % 4
                prefix_transaction = context.block(model, optimizer, clock, next_action, schedule)
                if transition_identity(prefix_transaction) != branches[next_action]["transition_sha256"][0]:
                    raise AssertionError("Independent prefix transaction differs from its matching branch")
                row = {
                    "schema": "hepta.fullstudy.C.branch-row.1", "seed": context.seed,
                    "mode": model.config["mode"], "schedule": schedule,
                    "schedule_index": schedule_index, "prefix": prefix, "decision": decision,
                    "clock": clock, "context_sha256": context.identity,
                    "warmstart_state_sha256": digest(warmstart), "parent_state_sha256": digest(parent),
                    "prefix_actions": list(prefix_actions), "prefix_transition_sha256": list(prefix_hashes),
                    "feature": feature.tolist(), "feature_receipt": feature_receipt,
                    "current_value": current["mean"], "advantages": advantages,
                    "branches": branches, "prefix_transaction": prefix_transaction,
                    "fit": schedule_index < 3, "calibration": schedule_index == 3,
                    "prefix_branch_replay_verified": True,
                    "branch_tensor_archive": False,
                }
                name = f"{destination}/schedule-{schedule}-{prefix}-step-{clock:03}.json.gz"
                artifact = store.json_gzip(name, row)
                rows.append({key: row[key] for key in
                             ("seed", "mode", "schedule", "prefix", "decision", "clock", "feature",
                              "advantages", "fit", "calibration", "parent_state_sha256")} | {"artifact": artifact})
                prefix_actions.append(next_action)
                prefix_hashes.append(transition_identity(prefix_transaction))
    expected = len(plan.bank_schedules) * 2 * plan.steps // plan.macro_steps
    if len(rows) != expected:
        raise AssertionError("Incomplete architecture development instance")
    store.json_gzip(destination + "/ROWS.json.gz", {"rows": rows, "complete": True})
    return rows


def fit_architecture(rows, plan, store, destination):
    expected = len(plan.development_seeds) * len(plan.bank_schedules) * 2 * plan.steps // plan.macro_steps
    if len(rows) != expected or {row["seed"] for row in rows} != set(plan.development_seeds):
        raise ValueError("Architecture head requires every declared development instance")
    features = np.asarray([row["feature"] for row in rows], dtype=np.float64)
    advantages = np.asarray([row["advantages"] for row in rows], dtype=np.float64)
    fit = np.asarray([row["fit"] for row in rows], dtype=bool)
    calibration = np.asarray([row["calibration"] for row in rows], dtype=bool)
    head = fit_head(features, advantages, fit, calibration, baseline=plan.baseline)
    arrays = {key: value for key, value in head.items() if isinstance(value, np.ndarray)}
    buffer = io.BytesIO()
    np.savez_compressed(buffer, features=features, advantages=advantages, fit=fit,
                        calibration=calibration, **arrays)
    artifact = store.bytes(destination + "/HEAD_AND_BANK.npz", buffer.getvalue())
    metadata = {"schema": "hepta.fullstudy.C.field-head.1", "head": head_metadata(head),
                "field_names": list(FIELD_NAMES), "array_artifact": artifact,
                "row_artifacts": [row["artifact"] for row in rows],
                "mode": rows[0]["mode"], "complete": True, "outcome_selected": False}
    store.json(destination + "/HEAD.json", metadata)
    return head, metadata


def read_row(path):
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def replay_registered_row(context, model, optimizer, warmstart, row, store, destination):
    """Called with a newly loaded model/optimizer/context, independently of bank state."""
    plan = context.plan
    if (row["schedule"] != 7000 or row["prefix"] != "balanced" or row["decision"] != 2
            or row["context_sha256"] != context.identity):
        raise ValueError("Replay row is not the prespecified context and audit target")
    context.work.phase = "replay_audit"
    before_work = context.work.snapshot()
    context.restore(model, optimizer, warmstart)
    if digest(warmstart) != row["warmstart_state_sha256"]:
        raise ValueError("Independent warmstart differs from branch recipe")
    actual_prefix = []
    for decision, action in enumerate(row["prefix_actions"]):
        receipt = context.block(model, optimizer, decision * plan.macro_steps, action, row["schedule"])
        actual_prefix.append(transition_identity(receipt))
    if actual_prefix != row["prefix_transition_sha256"]:
        raise AssertionError("Independent reconstruction prefix transition differs")
    if digest(context.snapshot(model, optimizer)) != row["parent_state_sha256"]:
        raise AssertionError("Independent reconstruction parent state differs")
    actual = tail(context, model, optimizer, row["clock"], 1, row["schedule"])
    expected = row["branches"][1]
    keys = ("terminal_state_sha256", "terminal_value", "terminal_values",
            "terminal_output_sha256", "transition_sha256")
    if digest({key: actual[key] for key in keys}) != digest({key: expected[key] for key in keys}):
        raise AssertionError("Independent reconstruction candidate/tail differs")
    result = {"complete": True, "passed": True, "seed": context.seed,
              "mode": row["mode"], "schedule": row["schedule"], "prefix": row["prefix"],
              "decision": row["decision"], "action": 1,
              "parent_state_sha256": row["parent_state_sha256"],
              "terminal_state_sha256": actual["terminal_state_sha256"],
              "prefix_transition_sha256": actual_prefix, "tail": actual,
              "work_before": before_work, "work_after": context.work.snapshot()}
    store.json_gzip(destination, result)
    return result
