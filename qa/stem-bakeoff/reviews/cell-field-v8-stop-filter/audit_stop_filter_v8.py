"""Post-seal independent196-slot arithmetic and actual zero-slack recheck.

No proposal/filter/Adam transition is rerun: the producer already independently
replayed every observed query and transition. This checker validates its sealed
raw ledger, complete census, costs, pairing and every returned old-panel loss.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np


PROTOCOL = "6342a84f7582a8bce9334f12500f904f01e64c9f4451cb27b6bc7d3cf5414851"
FILTERS = ("single_ray_v7", "joint_actual_old_v8")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def array_hash(value):
    value = np.ascontiguousarray(value)
    return digest(canonical([value.dtype.str, list(value.shape)])+value.tobytes())


def inventory(root, seal):
    found = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file() and p.name != "diagnostic-seal.json"}
    require(set(found) == set(seal["files"]), "exact sealed result file census")
    for name, path in found.items():
        pin = seal["files"][name]
        require(not path.is_symlink() and path.stat().st_size == pin["bytes"] and sha(path) == pin["sha256"], "sealed bytes: "+name)


def verify_ledger(record, arrays, original, train_sha):
    observer = record["actual_call_observer"]
    require(not observer["overflow"] and not observer["observation_errors"] and not observer["actual_head_errors"]
        and observer["raw_old_panel_calls"] == 0, "complete normalized query observation")
    queries, transitions = observer["old_queries"], observer["transitions"]
    require(observer["normalized_old_panel_calls"] == len(queries)
        and observer["actual_advance_calls"] == len(transitions), "actual query and transition census")
    require(len(arrays["advance_before_vectors"]) == len(arrays["advance_after_vectors"])
        == len(arrays["advance_interventions"]) == len(transitions), "all prospective physical vectors retained")
    for query in queries:
        require(query["panel"] in range(4) and query["l2"] == 0. and np.isfinite(query["loss"])
            and array_hash(arrays["query_parameter_points"][query["point"]]) == query["parameter_sha256"], "exact finite observed query parameter identity")
    for i, row in enumerate(transitions):
        before = digest(canonical(row["before_metadata"])+bytes.fromhex(array_hash(arrays["advance_before_vectors"][i])))
        after = digest(canonical(row["after_metadata"])+bytes.fromhex(array_hash(arrays["advance_after_vectors"][i])))
        require(before == row["before_state_sha256"] and after == row["after_state_sha256"]
            and row["dataset_sha256"] == train_sha and row["indices"] is None and row["mask"] is None
            and row["error"] is None, "complete observed prospective state identity")
        receipt = row["receipt"]
        require(receipt["previous_state_sha256"] == before and receipt["state_sha256"] == after
            and receipt["intervention_sha256"] == array_hash(arrays["advance_interventions"][i]), "prospective receipt binds complete vectors and actual intervention")
        before_meta, after_meta = row["before_metadata"], row["after_metadata"]
        require(after_meta == {**before_meta, "step_count": before_meta["step_count"]+1}, "full-batch metadata changes only the optimizer clock")
    return len(queries), len(transitions)


def aggregate(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    result = []
    for key, values in sorted(groups.items()):
        safe = [r for r in values if r["safe"]]
        result.append({**dict(zip(keys, key)), "slots": len(values), "safe": len(safe),
            "statuses": dict(Counter(r["status"] for r in values)),
            "actual_errors": sum(r["actual_error"] for r in values),
            "filter_cpu_ns": sum(r["filter_cpu_ns"] for r in values),
            "counterfactual_pipeline_cpu_ns": sum(r["pipeline_cpu_ns"] for r in values),
            "old_query_calls": sum(r["old_query_calls"] for r in values),
            "optimizer_calls": sum(r["optimizer_calls"] for r in values),
            "accepted_steps": sum(r["accepted_steps"] for r in values),
            "maximum_certified_old_excess": max((r["maximum_future_old_excess"] for r in safe), default=None)})
    return result


def audit(workspace, root, output):
    workspace, root, output = map(Path, (workspace, root, output))
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    require(os.environ.get("OPENBLAS_NUM_THREADS") == os.environ.get("OMP_NUM_THREADS") == "1", "same registered numeric thread settings")
    source = workspace/"hepta-repo-v8/qa/stem-bakeoff"
    sys.path.insert(0, str(source))
    from cell_field_stop_inputs_v8 import load_origin, load_origin_manifest, load_planning
    from cell_learning_models import normalize_features
    origins = workspace/"pft-development-v8/stop-origins"
    packages = workspace/"pft-development-v7b/planning-only"
    seal_sha, seal = sha(root/"diagnostic-seal.json"), read(root/"diagnostic-seal.json")
    require(sha(root/"protocol.json") == seal["protocol_sha256"] == PROTOCOL, "exact frozen diagnostic protocol")
    inventory(root, seal)
    freeze, report = read(root/"source-freeze.json"), read(root/"report.json")
    require(freeze["source_commit"] == "bdaed1dc94adc1c52dfbc0ac9a0f1ebc6299f9af" and len(freeze["source_hashes"]) == 111,
        "exact111 frozen execution sources")
    for name, pin in freeze["source_hashes"].items():
        require(sha(source/name) == pin, "execution source unchanged")
    manifest = load_origin_manifest(origins)
    original_rows = manifest["rows"]
    require({p.relative_to(root).as_posix() for p in root.glob("config*/*/*/case.json")}
        == {r["slot"]+"/case.json" for r in original_rows}, "all98 original slots, no subset or extra case")
    datasets, rows, pairs, costs = {}, [], [], Counter()
    stored_queries, stored_transitions, actual_loss_checks = 0, 0, 0
    for ordinal, original in enumerate(original_rows):
        directory = root/original["slot"]
        case = read(directory/"case.json")
        for key in ("slot", "fit_id", "version", "task", "head", "seed", "policy", "configuration_index",
                    "configuration", "committed_steps", "original_method", "attempted_horizon", "origin_state_sha256",
                    "original_old_anchors", "training_sha256", "current_panel_sha256", "old_panel_sha256"):
            require(case[key] == original[key], "unchanged origin and original source/configuration tags: "+key)
        require(case["original_status"] == original["status"] and case["filter_order"] == list(FILTERS[ordinal%2:]+FILTERS[:ordinal%2])
            and case["effective_relinearizations"] == 0 and case["original_relinearizations"] == original["configuration"]["relinearizations"]
            and set(case["filters"]) == set(FILTERS) and "case_error" not in case, "complete fixed paired execution order")
        key = original["version"], original["task"]
        if key not in datasets:
            datasets[key] = load_planning(packages, *key)
        data = datasets[key]
        origin = load_origin(origins, original, data)
        panels = [(normalize_features(x), y) for x, y in data["old"]]
        anchors = np.asarray(original["original_old_anchors"])
        proposal_raw = read(directory/"proposal/record.json.gz")
        with np.load(directory/"proposal/arrays.npz", allow_pickle=False) as archive:
            proposal_arrays = {name: archive[name] for name in archive.files}
        intended = proposal_arrays["actions"]
        require(array_hash(intended) == case["proposal"]["actions_sha256"]
            and proposal_raw["call"] == case["proposal"]["call"] and not proposal_raw["call"]["error"]
            and proposal_raw["audit"]["status"] == "PASS" and not proposal_raw["audit_error"], "one identical qualified shared proposal")
        q, t = verify_ledger(proposal_raw, proposal_arrays, original, original["training_sha256"])
        stored_queries += q; stored_transitions += t
        costs["proposal_cpu_ns"] += proposal_raw["call"]["cpu_ns"]
        costs["producer_replay_cpu_ns"] += proposal_raw["audit"]["cpu_ns"]
        pair = {"slot": original["slot"], "horizon": original["attempted_horizon"], "original_status": original["status"]}
        for name in FILTERS:
            raw, summary = read(directory/name/"record.json.gz"), case["filters"][name]
            with np.load(directory/name/"arrays.npz", allow_pickle=False) as archive:
                arrays = {key: archive[key] for key in archive.files}
            record, observed = raw["filter"], raw["actual_call_observer"]
            q, t = verify_ledger(raw, arrays, original, original["training_sha256"])
            stored_queries += q; stored_transitions += t
            require(record["status"] == summary["status"] and raw["call"] == summary["call"]
                and raw["audit"] == summary["audit"] and not raw["call"]["error"]
                and not raw["audit_error"] and not summary["actual_errors"] and raw["audit"]["status"] == "PASS",
                "all196 finite/error-free integrity outcomes retained")
            require(record["verified_optimizer_steps"] == t == summary["actual_optimizer_calls"]
                and record["panel_head_evaluations"] == q == summary["actual_old_query_calls"], "actual recorded workload independently counted")
            batches = sum(len(step["trials"]) if name == FILTERS[0] else step["panel_batches"] for step in record["step_records"])
            require(q == 4+4*batches and record["committed_optimizer_steps"] == 0, "all four-constraint query batches and diagnostic-only commits")
            for k, step in enumerate(record["step_records"]):
                if name == FILTERS[0]:
                    require(step["trials"][0]["action_sha256"] == digest(intended[k].tobytes()), "same new intended action reaches legacy filter")
                else:
                    require(np.array_equal(np.asarray(step["intended_action"]), intended[k]), "same new intended action reaches joint filter")
            safe = record["certified"]
            require(safe == (record["status"] == "certified") == summary["qualified_safe_witness"]
                and record["status"] in ("certified", "rejected", "unresolved"), "typed safe and failed outcomes")
            h = original["attempted_horizon"] if safe else 0
            actions, vectors, values = arrays["accepted_actions"], arrays["returned_states"], arrays["returned_old_losses"]
            require(actions.shape == (h, origin.parameter_count) and vectors.shape == (h+1, 3*origin.parameter_count)
                and values.shape == (h+1, 4) and np.isfinite(vectors).all() and np.isfinite(values).all(), "atomic actual returned path")
            bound = original["configuration"]["action_bound"]/np.sqrt(origin.parameter_count)
            require(np.all(np.abs(actions) <= bound) and record["threshold_slack"] == 0.
                and record["original_old_anchors"] == anchors.tolist(), "original box and zero-slack anchors unchanged")
            for k, vector in enumerate(vectors):
                state = origin.clone(); state.set_vector(vector); state.step_count += k
                actual = np.asarray([state.head.loss_gradients(x, y, 0.)[0] for x, y in panels])
                require(np.array_equal(actual, values[k]) and np.all(actual <= anchors)
                    and state.digest() == raw["audit"]["state_sha256"][k], "independent actual old loss and complete returned-state identity")
                actual_loss_checks += 4
            require(safe or np.array_equal(vectors[0], origin.vector()), "failed block adopts no prospective prefix")
            maximum = None if not h else float((values[1:]-anchors).max())
            require(maximum == raw["audit"]["maximum_future_old_excess"], "recomputed zero-slack path maximum")
            counterfactual = proposal_raw["call"]["cpu_ns"]+raw["call"]["cpu_ns"]
            require(counterfactual == summary["counterfactual_proposal_plus_filter_cpu_ns"]
                and raw["call"]["cpu_ns"] >= record["cpu_ns"] > 0, "separately charged actual whole filter call")
            costs[name+"_cpu_ns"] += raw["call"]["cpu_ns"]
            costs["producer_replay_cpu_ns"] += raw["audit"]["cpu_ns"]
            pair[name] = safe
            rows.append({"slot": original["slot"], "filter": name, "horizon": original["attempted_horizon"],
                "original_status": original["status"], "policy": original["policy"], "configuration_index": original["configuration_index"],
                "version": original["version"], "task": original["task"], "head": original["head"], "seed": original["seed"],
                "status": record["status"], "safe": safe, "actual_error": False, "accepted_steps": h,
                "filter_cpu_ns": raw["call"]["cpu_ns"], "pipeline_cpu_ns": counterfactual,
                "old_query_calls": q, "optimizer_calls": t, "maximum_future_old_excess": maximum,
                "prospective_safe_steps": record["prospective_safe_steps"],
                "action_difference_l2": raw["audit"]["action_difference_l2"],
                "parameter_penalty": float(.5*original["configuration"]["dt"]*original["configuration"]["effort_price"]*np.square(actions).sum())})
        pairs.append(pair)
    require(len(rows) == 196 and report["integrity_status"] == "PASS" and report["observed_filter_slots"] == 196, "complete independent196-slot census")
    require(report["proposal_cpu_ns"] == costs["proposal_cpu_ns"]
        and all(report["filter_cpu_ns"][name] == costs[name+"_cpu_ns"] for name in FILTERS), "all producer timing sums independently match")
    for horizon in (1, 8):
        actual = next(v for v in report["by_horizon"] if v["horizon"] == horizon)
        subset = [r for r in pairs if r["horizon"] == horizon]
        counted = Counter((r[FILTERS[0]], r[FILTERS[1]]) for r in subset)
        require(actual["registered_origins"] == len(subset) and actual["both_safe"] == counted[True, True]
            and actual["joint_only_safe"] == counted[False, True] and actual["single_ray_only_safe"] == counted[True, False]
            and actual["neither_safe_or_unavailable"] == counted[False, False], "independent paired horizon counts")
    prior = read(workspace/"pft-development-v8/stop-attempt1-interruption.json")
    prior_cost = prior["recoverable_recorded_costs"]
    lower = sum(prior_cost.values())
    result = {"schema": "hepta.cell-field-stop-independent-audit.v8", "status": "PASS", "auditor_sha256": sha(__file__),
        "complete_attempt": str(root), "diagnostic_seal_sha256": seal_sha, "protocol_sha256": PROTOCOL,
        "source_commit": freeze["source_commit"], "source_files": 111, "original_origins": 98, "filter_slots": 196,
        "retained_actual_query_records_checked": stored_queries, "retained_prospective_optimizer_records_checked": stored_transitions,
        "actual_returned_old_losses_recomputed": actual_loss_checks, "new_optimizer_or_solver_calls": 0,
        "by_filter_horizon": aggregate(rows, ("filter", "horizon")),
        "by_filter_original_status": aggregate(rows, ("filter", "original_status")),
        "by_filter_policy": aggregate(rows, ("filter", "policy")),
        "by_filter_configuration": aggregate(rows, ("filter", "configuration_index")),
        "paired": pairs, "all196_rows": rows, "complete_attempt_costs": dict(costs),
        "complete_attempt_whole_run_cpu_ns": report["cpu_ns"], "complete_attempt_whole_run_wall_ns": report["wall_ns"],
        "retained_first_attempt_inventory_sha256": sha(workspace/"pft-development-v8/stop-attempt1-interruption.json"),
        "retained_first_attempt_cost_lower_bounds": prior_cost,
        "both_attempts_total_cpu_lower_bound_ns": report["cpu_ns"]+lower,
        "both_attempts_total_cpu_exact_known": False,
        "cost_scope": "complete retry measured total plus recoverable disjoint attempt1 call/replay costs; attempt1 unrecorded interrupted/preparation/I/O cost remains unknown",
        "scientific_acceptance": False, "closed_loop32_completion_claimed": False,
        "audit_cpu_ns": time.process_time_ns()-cpu, "audit_wall_ns": time.perf_counter_ns()-wall}
    inventory(root, seal)
    require(sha(root/"diagnostic-seal.json") == seal_sha, "sealed original retry unchanged after independent audit")
    require(not output.exists(), "new independent audit output")
    output.write_bytes(canonical(result)+b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("workspace", "root", "output"):
        parser.add_argument("--"+key, required=True)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("status", "original_origins", "filter_slots", "by_filter_horizon", "audit_cpu_ns")}, sort_keys=True))
