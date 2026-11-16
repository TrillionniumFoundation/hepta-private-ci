"""Audit a fixed old-first portfolio using sealed paired diagnostic branches.

This is a post hoc, instrumented cost counterfactual, not an executed controller.
No solver or optimizer is called; every selected complete trajectory is checked
against its observed physical transition ledger and original zero-slack panels.
"""

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import os
import sys
import time

import numpy as np

from audit_stop_filter_v8 import (
    FILTERS, PROTOCOL, array_hash, canonical, digest, inventory, read, require, sha,
)


AUDIT_SHA = "4f36837be760f54641f6e41fffb15ccb1758b9df273625a8f9ef9950190b85a4"


def check_selected(origin, panels, anchors, original, raw, arrays):
    """Bind returned receipts to observed transitions; recompute actual losses."""
    from cell_learning_models import normalize_features
    record = raw["filter"]
    horizon = original["attempted_horizon"] if record["certified"] else 0
    actions = arrays["accepted_actions"]
    vectors, losses = arrays["returned_states"], arrays["returned_old_losses"]
    receipts = raw["returned_receipts"]
    require(actions.shape == (horizon, origin.parameter_count)
        and vectors.shape == (horizon+1, 3*origin.parameter_count)
        and losses.shape == (horizon+1, 4) and len(receipts) == horizon,
        "selected entire atomic path with complete receipts")
    require(record["threshold_slack"] == 0. and record["original_old_anchors"] == anchors.tolist()
        and np.isfinite(actions).all() and np.isfinite(vectors).all()
        and np.all(np.abs(actions) <= original["configuration"]["action_bound"]/np.sqrt(origin.parameter_count)),
        "selected original action box and zero-slack thresholds")
    dt = original["configuration"]["dt"]
    states = []
    prepared = [(normalize_features(x), y) for x, y in panels]
    for k, vector in enumerate(vectors):
        state = origin.clone()
        state.set_vector(vector)
        state.step_count += k
        actual = np.asarray([state.head.loss_gradients(x, y, 0.)[0] for x, y in prepared])
        require(np.array_equal(actual, losses[k]) and np.all(actual <= anchors),
            "every selected initial/future actual old loss satisfies all original anchors")
        states.append(state)
    require(np.array_equal(vectors[0], origin.vector())
        and [state.digest() for state in states] == raw["audit"]["state_sha256"]
        and states[-1].digest() == record["returned_state_sha256"],
        "selected complete states bind original audit commitment")
    transitions = raw["actual_call_observer"]["transitions"]
    matched = []
    for k, receipt in enumerate(receipts):
        require(receipt["previous_state_sha256"] == states[k].digest()
            and receipt["state_sha256"] == states[k+1].digest()
            and receipt["intervention_sha256"] == array_hash(dt*actions[k]),
            "selected receipt binds full-state chain and actual scaled action")
        candidates = [i for i, observed in enumerate(transitions)
            if observed["receipt"] == receipt and observed["error"] is None
            and observed["before_metadata"] == states[k]._metadata()
            and observed["after_metadata"] == states[k+1]._metadata()
            and np.array_equal(arrays["advance_before_vectors"][i], vectors[k])
            and np.array_equal(arrays["advance_after_vectors"][i], vectors[k+1])
            and np.array_equal(arrays["advance_interventions"][i], dt*actions[k])]
        require(bool(candidates), "selected exact action/state/receipt occurred in original observed physical ledger")
        matched.append(candidates[0])
    penalty = float(.5*dt*original["configuration"]["effort_price"]*np.square(actions).sum())
    require(penalty == raw["audit"]["parameter_action_penalty"], "exact original physical action price")
    return {"accepted_steps": horizon, "state_sha256": [s.digest() for s in states],
        "receipt_sha256": digest(receipts), "matched_transition_indices": matched,
        "actual_old_losses_recomputed": 4*len(states),
        "maximum_future_old_excess": float((losses[1:]-anchors).max()) if horizon else None,
        "minimum_future_old_excess": float((losses[1:]-anchors).min()) if horizon else None,
        "parameter_action_penalty": penalty, "actions_sha256": array_hash(actions)}


def grouped(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    result = []
    for key, values in sorted(groups.items()):
        result.append({**dict(zip(keys, key)), "origins": len(values),
            "safe": sum(v["safe"] for v in values), "selected_filters": dict(Counter(v["selected_filter"] for v in values)),
            "fallback_calls": sum(v["fallback_needed"] for v in values),
            **{name: sum(v[name] for v in values) for name in
               ("proposal_cpu_ns", "filter_cpu_ns", "pipeline_cpu_ns", "pipeline_wall_ns",
                "old_query_calls", "optimizer_calls", "accepted_steps")},
            "maximum_future_old_excess": max((v["maximum_future_old_excess"] for v in values if v["safe"]), default=None)})
    return result


def audit_portfolio(workspace, root, audit, output):
    workspace, root, audit, output = map(Path, (workspace, root, audit, output))
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    require(not output.exists() and root not in output.parents, "new output outside sealed execution")
    require(os.environ.get("OPENBLAS_NUM_THREADS") == os.environ.get("OMP_NUM_THREADS") == "1", "same numeric runtime")
    require(sha(audit) == AUDIT_SHA, "independently audited paired branch evidence")
    verified = read(audit)
    require(verified["status"] == "PASS" and verified["filter_slots"] == 196
        and verified["protocol_sha256"] == PROTOCOL, "complete paired qualification")
    seal = read(root/"diagnostic-seal.json")
    seal_sha = sha(root/"diagnostic-seal.json")
    require(seal_sha == verified["diagnostic_seal_sha256"], "exact same complete attempt")
    inventory(root, seal)
    source = workspace/"hepta-repo-v8/qa/stem-bakeoff"
    freeze = read(root/"source-freeze.json")
    for name, pin in freeze["source_hashes"].items():
        require(sha(source/name) == pin, "unchanged frozen execution source")
    sys.path.insert(0, str(source))
    from cell_field_stop_inputs_v8 import load_origin, load_origin_manifest, load_planning
    original_root = workspace/"pft-development-v8/stop-origins"
    originals = load_origin_manifest(original_root)["rows"]
    by_slot = {(row["slot"], row["filter"]): row for row in verified["all196_rows"]}
    require(len(by_slot) == 196 and len(originals) == 98
        and set(by_slot) == {(r["slot"], name) for r in originals for name in FILTERS}, "exact original all98 paired census")
    datasets, rows = {}, []
    for original in originals:
        slot = original["slot"]
        old, joint = (by_slot[slot, name] for name in FILTERS)
        fallback = not old["safe"]
        selected = FILTERS[1] if fallback else FILTERS[0]
        selected_row = joint if fallback else old
        directory = root/slot
        raw = read(directory/selected/"record.json.gz")
        with np.load(directory/selected/"arrays.npz", allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in archive.files}
        key = original["version"], original["task"]
        if key not in datasets:
            datasets[key] = load_planning(workspace/"pft-development-v7b/planning-only", *key)
        data = datasets[key]
        origin = load_origin(original_root, original, data)
        require(raw["filter"]["certified"] == selected_row["safe"], "fixed-order choice uses original certificate only")
        qualification = check_selected(origin, data["old"], np.asarray(original["original_old_anchors"]), original, raw, arrays)
        case = read(directory/"case.json")
        proposal = case["proposal"]["call"]
        paid_names = FILTERS if fallback else FILTERS[:1]
        paid = [read(directory/name/"record.json.gz") for name in paid_names]
        filter_cpu = sum(item["call"]["cpu_ns"] for item in paid)
        filter_wall = sum(item["call"]["wall_ns"] for item in paid)
        query_count = sum(len(item["actual_call_observer"]["old_queries"]) for item in paid)
        transition_count = sum(len(item["actual_call_observer"]["transitions"]) for item in paid)
        rows.append({"slot": slot, "policy": original["policy"], "horizon": original["attempted_horizon"],
            "original_status": original["status"], "configuration_index": original["configuration_index"],
            "selected_filter": selected, "safe": selected_row["safe"], "fallback_needed": fallback,
            "old_status": old["status"], "joint_status": joint["status"],
            "origin_state_sha256": origin.digest(), "selected_raw_record_sha256": sha(directory/selected/"record.json.gz"),
            "selected_arrays_sha256": sha(directory/selected/"arrays.npz"),
            "proposal_cpu_ns": proposal["cpu_ns"], "filter_cpu_ns": filter_cpu,
            "pipeline_cpu_ns": proposal["cpu_ns"]+filter_cpu,
            "pipeline_wall_ns": proposal["wall_ns"]+filter_wall,
            "old_query_calls": query_count, "optimizer_calls": transition_count,
            **qualification})
    summary = grouped(rows, ())[0]
    summary.pop("maximum_future_old_excess", None)
    result = {"schema": "hepta.fixed-order-filter-counterfactual.v8", "status": "PASS",
        "source_sha256": sha(__file__), "independent_paired_audit_sha256": AUDIT_SHA,
        "diagnostic_seal_sha256": seal_sha, "protocol_sha256": PROTOCOL,
        "rule": "Use complete single_ray_v7 sequence if certified; otherwise use complete joint_actual_old_v8 sequence from the SAME origin and SAME intended array; never splice paths.",
        "post_hoc_counterfactual": True, "executed_portfolio_controller": False,
        "summary": summary, "by_horizon": grouped(rows, ("horizon",)),
        "by_policy": grouped(rows, ("policy",)), "by_original_status": grouped(rows, ("original_status",)),
        "by_configuration": grouped(rows, ("configuration_index",)), "all98_selected_rows": rows,
        "actual_old_losses_recomputed": sum(r["actual_old_losses_recomputed"] for r in rows),
        "actual_selected_receipts_bound": sum(r["accepted_steps"] for r in rows),
        "new_optimizer_calls": 0, "new_solver_calls": 0,
        "cost_scope": "Instrumented counterfactual: original proposal once + original old-filter whole-call cost + original joint whole-call cost only when old rejected. The source experiment ran both branches in alternating order. Cache/order effects and portfolio dispatch overhead are NOT newly measured. Independent audits and infrastructure retry costs are reported separately.",
        "old_query_count_scope": "Filter calls only; shared proposal queries are outside this counterfactual filter workload.",
        "retained_attempt1_inventory_sha256": verified["retained_first_attempt_inventory_sha256"],
        "scientific_acceptance": False, "closed_loop32_completion_claimed": False,
        "independent_holdout_retention_claimed": False,
        "audit_cpu_ns": time.process_time_ns()-cpu, "audit_wall_ns": time.perf_counter_ns()-wall}
    inventory(root, seal)
    require(sha(root/"diagnostic-seal.json") == seal_sha, "sealed original files unchanged")
    output.write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("workspace", "root", "audit", "output"):
        parser.add_argument("--"+key, required=True)
    result = audit_portfolio(**vars(parser.parse_args()))
    print(canonical({key: result[key] for key in ("status", "summary", "by_horizon", "audit_cpu_ns")}).decode())
