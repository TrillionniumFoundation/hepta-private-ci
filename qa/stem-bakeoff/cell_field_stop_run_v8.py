"""All98 original origins: one new proposal, two separately charged filters.

The historical unsuccessful intended actions were not retained. This experiment
generates a NEW risk-plus-effort proposal and holds it identical for both filters.
It neither reproduces those missing actions nor resumes the stopped policies.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import platform
import time

import numpy as np

from cell_field_filter_audit_v8 import actual_errors, audit_filter, audit_observer
from cell_field_filter_observer_v8 import CallObserver, array_hash
from cell_field_stop_inputs_v8 import (ORIGINS_SHA, PLANNING_SHA, canonical, digest, file_hash,
    load_origin, load_origin_manifest, load_planning, read, require, verify_source_freeze)


FILTERS = ("single_ray_v7", "joint_actual_old_v8")
PROPOSAL_KEYS = ("dt", "effort_price", "action_bound", "old_weight", "current_dispersion")


def portable(value):
    if isinstance(value, np.ndarray):
        return portable(value.tolist())
    if isinstance(value, np.generic):
        return portable(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return {"nonfinite_float": str(value)}
    if isinstance(value, dict):
        return {str(k): portable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [portable(v) for v in value]
    return value


def write_json(path, value, compressed=False):
    raw = canonical(portable(value))+b"\n"
    Path(path).write_bytes(gzip.compress(raw, mtime=0) if compressed else raw)


def call_observed(origin, data, function):
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    observer = CallObserver(origin, data["train"], data["old"])
    result, error = None, None
    try:
        with observer:
            result = function()
    except Exception as caught:
        error = {"type": type(caught).__name__, "message": str(caught)}
    return result, observer, {"cpu_ns": time.process_time_ns()-cpu,
        "wall_ns": time.perf_counter_ns()-wall, "error": error,
        "scope": "whole call including identical read-only observation; excludes independent replay and file serialization"}


def save_observation(directory, observer, extra_arrays, record):
    directory.mkdir(parents=True, exist_ok=False)
    arrays = {**observer.arrays(), **extra_arrays}
    np.savez_compressed(directory/"arrays.npz", **arrays)
    write_json(directory/"record.json.gz", {**record, "actual_call_observer": observer.record()}, True)
    return {name: {"bytes": (directory/name).stat().st_size, "sha256": file_hash(directory/name)}
        for name in ("arrays.npz", "record.json.gz")}


def run_origin(row, origin_directory, packages, cached_data, output, ordinal, proposal_fn, filter_functions):
    case = {key: row[key] for key in ("slot", "fit_id", "version", "task", "head", "seed", "policy",
        "configuration_index", "configuration", "committed_steps", "original_method", "attempted_horizon",
        "status", "origin_state_sha256", "original_old_anchors", "training_sha256", "current_panel_sha256", "old_panel_sha256")}
    case.update(original_status=case.pop("status"), original_intended_actions_retained=False,
        proposal_scope="new shared proposal for paired filters; not the missing historical intention",
        effective_relinearizations=0, original_relinearizations=row["configuration"]["relinearizations"],
        filter_order=list(FILTERS[ordinal % 2:]+FILTERS[:ordinal % 2]), filters={})
    target = output/row["slot"]
    target.mkdir(parents=True)
    try:
        key = row["version"], row["task"]
        if key not in cached_data:
            cached_data[key] = load_planning(packages, *key)
        data = cached_data[key]
        origin = load_origin(origin_directory, row, data)
        anchors = np.asarray(row["original_old_anchors"], dtype=np.float64)
        horizon = row["attempted_horizon"]
        args = {k: row["configuration"][k] for k in PROPOSAL_KEYS}
        proposal_state = origin.clone()
        proposal, observed, cost = call_observed(origin, data, lambda: proposal_fn(proposal_state, data["train"],
            data["current"], data["old"], anchors.copy(), method=row["original_method"], horizon=horizon, **args))
        proposal_audit, audit_error, arrays = None, None, {}
        try:
            if proposal is not None:
                arrays = {key: np.asarray(proposal[key]) for key in ("actions", "maps", "reference_states",
                    "reference_observations", "nominal_reference_actions")}
            proposal_audit = audit_observer(observed)
            require(proposal_state.digest() == origin.digest(), "proposal leaves complete origin unchanged")
            require(cost["error"] is None and proposal is not None and proposal["record"]["status"] == "qualified", "finite new proposal required")
            intended = np.asarray(proposal["actions"])
            require(intended.shape == (horizon, origin.parameter_count) and np.isfinite(intended).all()
                and np.all(np.abs(intended) <= args["action_bound"]/np.sqrt(origin.parameter_count)), "same original physical box")
            require(proposal["record"]["horizon"] == horizon and proposal["record"]["relinearizations"] == 0
                and proposal["record"]["predicted_old_constraints"] is False
                and proposal["record"]["actual_risk_backtracking_rollouts"] == 0, "frozen new proposal semantics")
            require(all(np.isfinite(v).all() for v in arrays.values()), "finite prediction/reference arrays")
        except Exception as error:
            audit_error = {"type": type(error).__name__, "message": str(error)}
        pins = save_observation(target/"proposal", observed, arrays, {"call": cost,
            "proposal": None if proposal is None else proposal.get("record"), "audit": proposal_audit, "audit_error": audit_error})
        case["proposal"] = {"call": cost, "audit": proposal_audit, "audit_error": audit_error, "files": pins,
            "actions_sha256": array_hash(arrays["actions"]) if "actions" in arrays else None}
        if cost["error"] or audit_error:
            raise ValueError("new proposal unavailable; both paired filter slots retained without fallback")
        intended = arrays["actions"].copy()
        for name in case["filter_order"]:
            branch_input, branch_actions = origin.clone(), intended.copy()
            result, observed, cost = call_observed(origin, data,
                lambda: filter_functions[name](branch_input, data["train"], data["old"], branch_actions,
                    anchors.copy(), horizon=horizon, dt=args["dt"], action_bound=args["action_bound"]))
            audit, audit_error, arrays = None, None, {}
            try:
                if result is not None:
                    arrays = {"accepted_actions": np.asarray(result["actions"]),
                        "returned_states": np.asarray([s.vector() for s in result["states"]]),
                        "returned_old_losses": np.asarray(result["old_losses"])}
                require(branch_input.digest() == origin.digest() and np.array_equal(branch_actions, intended),
                    "same unchanged original state and exact intended actions for both filters")
                require(cost["error"] is None and result is not None, "filter result available")
                audit, states = audit_filter(origin, data["train"], data["old"], intended, anchors, result, observed,
                    horizon=horizon, dt=args["dt"], action_bound=args["action_bound"], effort_price=args["effort_price"])
                require(np.array_equal(arrays["returned_states"], states), "saved raw return states match independent replay")
            except Exception as error:
                audit_error = {"type": type(error).__name__, "message": str(error)}
            raw = None if result is None else result["record"]
            receipts = None if result is None else result["receipts"]
            pins = save_observation(target/name, observed, arrays, {"call": cost, "filter": raw,
                "returned_receipts": receipts, "audit": audit, "audit_error": audit_error})
            actual = list(actual_errors(raw)) if raw is not None else []
            branch = {"status": raw["status"] if raw else "unavailable_execution_error", "call": cost,
                "audit": audit, "audit_error": audit_error, "actual_errors": actual, "files": pins,
                "proposal_actions_sha256": case["proposal"]["actions_sha256"],
                "qualified_safe_witness": bool(raw and raw["certified"] and audit and not audit_error and not actual and not cost["error"]),
                "counterfactual_proposal_plus_filter_cpu_ns": case["proposal"]["call"]["cpu_ns"]+cost["cpu_ns"],
                "actual_old_query_calls": len(observed.queries), "actual_optimizer_calls": len(observed.transitions),
                "prospective_safe_steps": None if raw is None else raw["prospective_safe_steps"]}
            case["filters"][name] = branch
    except Exception as error:
        case["case_error"] = {"type": type(error).__name__, "message": str(error)}
    for name in FILTERS:
        case["filters"].setdefault(name, {"status": "unavailable_input_or_proposal", "qualified_safe_witness": False,
            "actual_errors": [], "audit_error": case.get("case_error"), "call": None,
            "actual_old_query_calls": 0, "actual_optimizer_calls": 0})
    write_json(target/"case.json", case)
    return case


def summarize(cases):
    rows = []
    for horizon in (1, 8):
        group = [r for r in cases if r["attempted_horizon"] == horizon]
        paired = Counter(tuple(r["filters"][name]["qualified_safe_witness"] for name in FILTERS) for r in group)
        rows.append({"horizon": horizon, "registered_origins": len(group),
            "both_safe": paired[True, True], "joint_only_safe": paired[False, True],
            "single_ray_only_safe": paired[True, False], "neither_safe_or_unavailable": paired[False, False],
            "filter_statuses": {name: dict(Counter(r["filters"][name]["status"] for r in group)) for name in FILTERS}})
    flat = [row["filters"][name] for row in cases for name in FILTERS]
    failures = sum(bool(r["audit_error"] or r["actual_errors"] or (r["call"] and r["call"]["error"])) for r in flat)
    return {"registered_origins": 98, "observed_origins": len(cases), "registered_filter_slots": 196,
        "observed_filter_slots": len(flat), "by_horizon": rows,
        "integrity_status": "PASS" if len(flat) == 196 and failures == 0 and not any("case_error" in r for r in cases) else "FAIL",
        "all_joint_origins_certified": len(cases) == 98 and all(r["filters"][FILTERS[1]]["qualified_safe_witness"] for r in cases),
        "unavailable_filter_slots": sum(r["status"].startswith("unavailable") for r in flat),
        "proposal_actual_exception_origins": sum(bool(r.get("proposal", {}).get("call", {}).get("error")) for r in cases),
        "slots_with_actual_exception": sum(bool(r["actual_errors"] or (r["call"] and r["call"]["error"])) for r in flat),
        "slots_with_integrity_failure": sum(bool(r["audit_error"]) for r in flat),
        "source_errors": sum("case_error" in r for r in cases),
        "proposal_cpu_ns": sum(r.get("proposal", {}).get("call", {}).get("cpu_ns", 0) for r in cases),
        "filter_cpu_ns": {name: sum((r["filters"][name].get("call") or {}).get("cpu_ns", 0) for r in cases) for name in FILTERS},
        "old_constraint_queries": sum(r["actual_old_query_calls"] for r in flat),
        "observed_prospective_optimizer_calls": sum(r["actual_optimizer_calls"] for r in flat),
        "scientific_acceptance": False, "closed_loop32_completion_claimed": False,
        "scope": "paired local feasibility only; shared new proposal; conditional stopped origins are not independent samples"}


def run(protocol, source_freeze, origins, planning_packages, output):
    import scipy
    from threadpoolctl import threadpool_info
    protocol, source_freeze, origins, planning_packages, output = map(Path,
        (protocol, source_freeze, origins, planning_packages, output))
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    plan = read(protocol)
    freeze = verify_source_freeze(source_freeze, protocol)
    require(plan["schema"] == "hepta.cell-field-stop-filter-protocol.v8" and plan["frozen"] is True
        and plan["origins_manifest_sha256"] == ORIGINS_SHA and plan["planning_only_index_sha256"] == PLANNING_SHA
        and plan["filters"] == list(FILTERS) and plan["registered_origins"] == 98
        and plan["registered_filter_slots"] == 196, "frozen registered diagnostic required")
    runtime = {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
        "platform": platform.platform(), "threadpools": threadpool_info(),
        "threads": {name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")}}
    require(runtime["threads"] == {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        "frozen single-thread runtime required before any real-origin execution")
    manifest = load_origin_manifest(origins)
    require(not output.exists(), "new output directory; no hidden retries or replacement")
    output.mkdir(parents=True)
    (output/"protocol.json").write_bytes(protocol.read_bytes())
    (output/"source-freeze.json").write_bytes(source_freeze.read_bytes())
    write_json(output/"input-identities.json", {"origins_manifest_sha256": ORIGINS_SHA,
        "planning_only_index_sha256": PLANNING_SHA, "original_source_tags": manifest,
        "no_new_confirmation_labels": True})
    from cell_field_proposal_v8 import make_proposal
    from cell_field_repair_v7 import repair_sequence as single_ray
    from cell_field_safety_v8 import repair_sequence as joint
    functions = dict(zip(FILTERS, (single_ray, joint)))
    cases, cache = [], {}
    for ordinal, row in enumerate(manifest["rows"]):
        result = run_origin(row, origins, planning_packages, cache, output, ordinal, make_proposal, functions)
        cases.append(result)
        print(json.dumps({"completed_origins": len(cases), "slot": row["slot"],
            "horizon": row["attempted_horizon"], "statuses": {name: result["filters"][name]["status"] for name in FILTERS}}), flush=True)
    report = summarize(cases)
    require(len(cases) == 98 and len({r["slot"] for r in cases}) == 98, "all origins preserved")
    verify_source_freeze(source_freeze, protocol)
    require(file_hash(origins/"manifest.json") == ORIGINS_SHA, "original frozen origin list unchanged")
    report.update(schema="hepta.cell-field-stop-filter-diagnostic.v8", completed_at=datetime.now(timezone.utc).isoformat(),
        protocol_sha256=file_hash(protocol), source_freeze_sha256=file_hash(source_freeze), source_commit=freeze["source_commit"],
        cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-began,
        runtime=runtime,
        cost_scope="actual proposal/filter calls include observation; loading, independent replay and serialization charged in whole-run total only",
        no_new_confirmation_labels=True, original_stopped_policies_unchanged=True)
    write_json(output/"report.json", report)
    paths = {p.relative_to(output).as_posix(): {"bytes": p.stat().st_size, "sha256": file_hash(p)}
        for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output/"diagnostic-seal.json", {"schema": "hepta.cell-field-stop-filter-seal.v8",
        "protocol_sha256": file_hash(protocol), "source_freeze_sha256": file_hash(source_freeze), "files": paths,
        "registered_origins": 98, "registered_filter_slots": 196, "scientific_acceptance": False})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "source-freeze", "origins", "planning-packages", "output"):
        parser.add_argument("--"+name, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps(result))
