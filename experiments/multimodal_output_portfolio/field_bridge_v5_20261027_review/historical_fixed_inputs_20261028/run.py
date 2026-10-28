"""Separately registered, fixed-input CPU-dispatch diagnosis; no training/admission."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixed_inputs_common import (CASES, FIELDS, HERE, REPOSITORY, canonical, disk_record,
    LimitedCosts, configuration_identity, execution_guard, identity, imports_receipt, read, registration, require, setup_torch,
    sha, verify_inputs, write, write_bounded_summary)
from fixed_inputs_snapshot import prepare, torch_panels, verify_loaded_unchanged, verify_snapshot
from fixed_inputs_score import score_comparisons, score_panel, scoring_only_comparison


def remaining_bound(protocol, phase):
    storage = protocol["storage_bounds"]
    remaining = len(CASES) if phase == "prepare" else len(CASES) - CASES.index(phase)
    return (storage["snapshot_bytes"] if phase == "prepare" else 0) + (
        remaining * storage["per_case_bytes"] + storage["parent_metadata_bytes"])


def totals(resources):
    return {label: sum(value for name, value in resources.items() if name.endswith(suffix))
            for label, suffix in (("generator_panel_calls", "generator_calls"),
                ("generator_examples", "generator_examples"), ("observer_calls", "observer_calls"),
                ("observer_digit_examples", "observer_digit_examples"))}


def resource_summary(cases, preparation):
    resources = {}
    for item in cases:
        for name, value in (item.get("result") or {}).get("resources", {}).items():
            resources[name] = resources.get(name, 0) + value
    complete = all(item["resource_accounting_complete"] for item in cases) and (
        preparation is None or preparation["resource_accounting_complete"])
    observed = totals(resources)
    return resources, complete, observed, observed if complete else None


def validated_result(result):
    valid = isinstance(result, dict) and result.get("status") in ("COMPLETE", "FAIL")
    if valid:
        for key in ("resources", "independent_call_profile"):
            values = result.get(key)
            valid = valid and isinstance(values, dict) and all(isinstance(name, str)
                and type(value) is int and value >= 0 for name, value in values.items())
            if not valid:
                break
    if valid and "panels" in result:
        panels = result["panels"]
        valid = isinstance(panels, dict) and all(name in ("task", "clean") and isinstance(row, dict)
            and isinstance(row.get("vs_historical_raw"), dict)
            and type(row["vs_historical_raw"].get("full_sha256_and_bytes_exact")) is bool
            for name, row in panels.items())
    if valid and result["status"] == "COMPLETE" and result.get("phase") != "prepare":
        valid = isinstance(result.get("panels"), dict) and set(result["panels"]) == {"task", "clean"}
    return (result, None) if valid else (None, {"type": "InvalidResultSchema",
        "message": "Child RESULT status/resources/profile schema invalid; actual usage is unknown"})


def phase_child(args, protocol, sources, inputs, freeze):
    phase = "prepare" if args.phase == "prepare" else args.child_case
    require(phase == "prepare" or phase in CASES, "Missing inference case")
    parent_path = args.output / ("REGISTRATION.json" if phase == "prepare" else "START.json")
    require(sha(parent_path) == args.parent_record_sha256, "Parent record hash differs")
    parent = read(parent_path)
    require(parent["source_registration"] == sources and parent["protocol_sha256"] == sha(HERE / "PROTOCOL.json")
            and parent["cases"] == list(CASES), "Parent registration/scope differs")
    if phase != "prepare":
        require(identity(args.output / "prepare" / "RESULT.json") == parent["preparation_result"],
                "Preparation result identity differs")
        preparation = read(args.output / "prepare" / "RESULT.json")
        require(preparation["status"] == "COMPLETE" and preparation["snapshot"]["manifest"] == parent["input_manifest"]
                and preparation["snapshot"]["all_input_sha256"] == parent["all_input_sha256"], "Preparation binding differs")
    destination = args.output / phase
    destination.mkdir(exist_ok=False)
    storage = disk_record(args.output, remaining_bound(protocol, phase), protocol["storage_bounds"]["reserve_bytes"])
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    report = {"phase": phase, "status": "FAIL", "source_registration": sources,
        "protocol_sha256": sha(HERE / "PROTOCOL.json"), "scientific_status": "FAIL", "admission": False,
        "historical_raw_file_recovered": False, "new_holdout_access": False, "disk_before": storage,
        "parent_record_sha256": args.parent_record_sha256}
    write(destination / "START.json", report)
    violations, profile_counts, watch, resources = [], {}, {}, {}
    costs = None
    try:
        require(storage["passed"], "Insufficient allocatable disk plus registered reserve")
        report.update(setup_torch(protocol, phase))
        sys.setprofile(execution_guard(phase, violations, profile_counts, watch))
        if phase == "prepare":
            snapshot = prepare(args.output / "input_snapshot", inputs, protocol, sources)
            report.update(snapshot=snapshot, model_instances=0, model_calls=0)
            require(not profile_counts, "Preparation executed a model")
        else:
            import numpy as np
            from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
            from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.training_common import Costs
            from experiments.multimodal_output_portfolio.v6.neural import parameter_hash
            from experiments.multimodal_output_portfolio.v6.observer import METRIC

            require(protocol["utility_weights"] == METRIC["weights"] and tuple(METRIC["weights"]) == FIELDS,
                    "Frozen utility decomposition differs")
            snapshot, loaded = verify_snapshot(args.output / "input_snapshot", parent["input_manifest"],
                read(inputs["current_panel_identities"]), protocol, sources)
            require(snapshot["all_input_sha256"] == parent["all_input_sha256"], "Parent aggregate input hash differs")
            endpoint = torch_panels(loaded)
            expected = protocol["per_case_budget"]["unset" if phase.startswith("unset_") else "explicit"]
            costs = LimitedCosts(Costs(), expected)
            models, observers, assets = load_assets(args.assets, [17], ["reward", "audit"])
            model = models[17]
            watch.update(model=model, observers=list(observers.values()), call_limits={
                "generator_pipeline_started": expected["generator_panel_calls"],
                "generator_decode_calls": expected["generator_panel_calls"],
                "observer_forward_calls": expected["observer_calls"]})
            parameter_ids = {"model": parameter_hash(model), **{k: parameter_hash(v) for k, v in observers.items()}}
            require(parameter_ids == protocol["parameter_identities"] and model.hidden == protocol["latent_hidden"],
                    "Loaded model/observer parameters or hidden dimension differ")
            require(model.config == read(inputs["current_assets"])["models"]["17"]["config"], "Model configuration differs")
            configuration = configuration_identity(model, observers)
            report.update(parameter_identities=parameter_ids, configuration_identity=configuration, assets=assets,
                inference_model_roots=3, asset_loader_constructor_count=None,
                input_manifest=parent["input_manifest"], all_input_sha256=snapshot["all_input_sha256"])
            v3 = read(inputs["v3_protocol"])
            report["panels"] = {}
            for name in ("task", "clean"):
                score, files = score_panel(model, endpoint[name], observers, v3, costs, name, destination,
                    inputs["current_" + name + "_raw"], phase.startswith("unset_"))
                report["panels"][name] = score_comparisons(score, files, name, inputs, protocol, phase)
            final_parameters = {"model": parameter_hash(model), **{k: parameter_hash(v) for k, v in observers.items()}}
            final_configuration = configuration_identity(model, observers)
            report.update(final_parameter_identities=final_parameters,
                          final_configuration_sha256=final_configuration["sha256"])
            require(final_parameters == parameter_ids,
                    "Parameter state changed")
            require(final_configuration == configuration, "Model/observer configuration changed")
            verify_loaded_unchanged(loaded)
            verify_snapshot(args.output / "input_snapshot", parent["input_manifest"],
                            read(inputs["current_panel_identities"]), protocol, sources)
            require(totals(costs.snapshot()) == expected, "Actual case resource count differs")
            require(profile_counts == {"generator_pipeline_started": expected["generator_panel_calls"],
                                       "generator_decode_calls": expected["generator_panel_calls"],
                                       "observer_forward_calls": expected["observer_calls"]},
                    "Independent call profile differs from resource ledger")
        verify_inputs(protocol, args)
        require(registration(args.registered_commit) == sources, "Diagnostic source changed")
        report.update(imported_sources=imports_receipt(freeze, sources), status="COMPLETE")
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        sys.setprofile(None)
        if costs is not None:
            resources = costs.snapshot()
        report.update(resources=resources, actual_totals=totals(resources), forbidden_calls=violations,
            independent_call_profile=profile_counts, cpu_ns=time.process_time_ns() - cpu,
            wall_ns=time.perf_counter_ns() - started)
        write(destination / "RESULT.json", report)


def subprocess_phase(args, phase):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    environment.pop("ATEN_CPU_CAPABILITY", None)
    if phase in ("default", "avx2", "avx512"):
        environment["ATEN_CPU_CAPABILITY"] = phase
    parent_sha = sha(args.output / ("REGISTRATION.json" if phase == "prepare" else "START.json"))
    command = [sys.executable, "-I", "-B", str(HERE / "run.py"), "--registered-commit", args.registered_commit,
        "--assets", str(args.assets), "--run-root", str(args.run_root), "--first-attempt", str(args.first_attempt),
        "--output", str(args.output), "--phase", "prepare" if phase == "prepare" else "case",
        "--parent-record-sha256", parent_sha]
    if phase != "prepare":
        command.extend(["--child-case", phase])
    write(args.output / (phase + "_LAUNCH.json"), {"phase": phase, "command": command,
        "parent_record_sha256": parent_sha,
        "started_unix_ns": time.time_ns(), "ATEN_CPU_CAPABILITY": environment.get("ATEN_CPU_CAPABILITY")})
    code, launch_error, result_error = None, None, None
    with (args.output / (phase + ".stdout")).open("xb") as stdout, (args.output / (phase + ".stderr")).open("xb") as stderr:
        try:
            code = subprocess.run(command, env=environment, cwd=REPOSITORY, stdout=stdout, stderr=stderr).returncode
        except Exception as error:
            launch_error = {"type": type(error).__name__, "message": str(error)}
    path = args.output / phase / "RESULT.json"
    try:
        result = read(path) if path.exists() else None
    except Exception as error:
        result, result_error = None, {"type": type(error).__name__, "message": str(error)}
    if result_error is None:
        result, result_error = validated_result(result)
    accounted = result is not None
    return {"phase": phase, "exit_code": code, "resource_accounting_complete": accounted,
            "launch_error": launch_error, "result_read_error": result_error,
            "stdout": identity(args.output / (phase + ".stdout")),
            "stderr": identity(args.output / (phase + ".stderr")),
            "result_file": identity(path) if path.exists() else None,
            "result": result}


def completed(item):
    return item is not None and item["exit_code"] == 0 and item["result"] and item["result"]["status"] == "COMPLETE"


def parent(args, protocol, sources, inputs, freeze):
    require(os.environ.get("ATEN_CPU_CAPABILITY") is None, "Parent capability must be unset")
    require(all(os.environ.get(k) == v for k, v in protocol["fixed_environment"].items()), "Unregistered CPU environment")
    cpuinfo = Path("/proc/cpuinfo").read_text()
    flags = [set(line.split(":", 1)[1].split()) for line in cpuinfo.splitlines() if line.startswith("flags")]
    require(flags and all(set(protocol["required_host_flags"]) <= value for value in flags), "Unsupported host ISA")
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "CPUINFO.txt").open("x") as stream:
        stream.write(cpuinfo)
    write(args.output / "REGISTRATION.json", {"source_registration": sources,
        "protocol_sha256": sha(HERE / "PROTOCOL.json"), "first_attempt_summary": identity(inputs["first_attempt_summary"]),
        "cpuinfo_sha256": sha(args.output / "CPUINFO.txt"), "scientific_status": "FAIL", "admission": False,
        "new_holdout_access": False, "historical_raw_file_recovered": False, "cases": list(CASES)})
    preparation, cases, storage_checks, error, controls, scoring_only = None, [], [], None, None, None
    complete = False
    try:
        storage = disk_record(args.output, remaining_bound(protocol, "prepare"), protocol["storage_bounds"]["reserve_bytes"])
        storage_checks.append({"phase": "prepare", **storage})
        require(storage["passed"], "Insufficient allocatable disk before preparation")
        preparation = subprocess_phase(args, "prepare")
        require(completed(preparation), "Preparation failed; no inference cases launched")
        prepared = preparation["result"]["snapshot"]
        verify_snapshot(args.output / "input_snapshot", prepared["manifest"],
                        read(inputs["current_panel_identities"]), protocol, sources)
        write(args.output / "START.json", {"source_registration": sources,
            "protocol_sha256": sha(HERE / "PROTOCOL.json"), "preparation_result": preparation["result_file"],
            "input_manifest": prepared["manifest"], "all_input_sha256": prepared["all_input_sha256"],
            "cases": list(CASES), "scientific_status": "FAIL", "admission": False,
            "new_holdout_access": False, "historical_raw_file_recovered": False})
        for case in CASES:
            storage = disk_record(args.output, remaining_bound(protocol, case), protocol["storage_bounds"]["reserve_bytes"])
            storage_checks.append({"phase": case, **storage})
            require(storage["passed"], "Insufficient allocatable disk before case: " + case)
            item = subprocess_phase(args, case)
            item["registered_call_upper_bound"] = protocol["per_case_budget"]["unset" if case.startswith("unset_") else "explicit"]
            cases.append(item)
            directory = args.output / case
            used = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()) if directory.exists() else 0
            used += item["stdout"]["bytes"] + item["stderr"]["bytes"]
            require(used <= protocol["storage_bounds"]["per_case_bytes"], "Case output exceeded registered storage bound")
        verify_inputs(protocol, args)
        require(registration(args.registered_commit) == sources, "Diagnostic source changed")
        verify_snapshot(args.output / "input_snapshot", prepared["manifest"],
                        read(inputs["current_panel_identities"]), protocol, sources)
        complete = all(completed(item) for item in cases) and len(cases) == len(CASES)
        if complete:
            controls = all(identity(args.output / "unset_before" / (panel + suffix)) == identity(
                args.output / "unset_after" / (panel + suffix)) for panel in ("task", "clean")
                for suffix in (".npz", "_components.json.gz", "_forward_fields.json"))
            require(controls, "Repeated unset output bytes differ")
            scoring_only = scoring_only_comparison(args.output, inputs, protocol)
    except Exception as problem:
        error = {"type": type(problem).__name__, "message": str(problem)}
    resources, accounting_complete, observed_totals, actual = resource_summary(cases, preparation)
    if complete and error is None and actual != protocol["complete_budget"]:
        error = {"type": "ValueError", "message": "Complete experiment resource count differs"}
    matches = {panel: [item["phase"] for item in cases if (item.get("result") or {}).get("panels", {}).get(
        panel, {}).get("vs_historical_raw", {}).get("full_sha256_and_bytes_exact", False)] for panel in ("task", "clean")}
    summary = {"source_registration": sources, "preparation": preparation,
        "execution_complete": bool(complete), "diagnostic_interpretable": bool(complete and controls and error is None),
        "error": error, "cases": cases, "disk_checks": storage_checks, "observed_resources": resources,
        "observed_sealed_case_totals": observed_totals, "actual_totals": actual,
        "resource_accounting_complete": accounting_complete,
        "unknown_resource_cases": [item["phase"] for item in ([preparation] if preparation else []) + cases
                                   if not item["resource_accounting_complete"]],
        "first_attempt_actual_totals": protocol["first_attempt"]["actual_totals"],
        "unset_replicates_byte_exact": controls, "fixed_raw_mse_only_arithmetic": scoring_only,
        "newly_reconstructed_historical_raw_matching_cases": matches, "selected_capability": None,
        "scientific_status": "FAIL", "admission": False, "new_holdout_authorized": False,
        "historical_raw_file_recovered": False, "historical_gate_changed": False, "raw_upload_attempts": 0,
        "interpretation": "This fixed-input intervention cannot identify the historical CPU or repair scientific admission."}
    summary_storage = write_bounded_summary(args.output, summary, protocol["storage_bounds"]["parent_metadata_bytes"])
    require(complete and controls and error is None and summary_storage["full_summary_written"]
            and summary_storage["metadata_bound_satisfied"], "Incomplete or unstable fixed-input diagnosis; preserved SUMMARY.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registered-commit", required=True)
    for name in ("assets", "run-root", "first-attempt", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--phase", choices=("parent", "prepare", "case"), default="parent")
    parser.add_argument("--child-case", choices=CASES)
    parser.add_argument("--parent-record-sha256")
    args = parser.parse_args()
    for name in ("assets", "run_root", "first_attempt", "output"):
        setattr(args, name, getattr(args, name).resolve())
    require(not any(args.output.is_relative_to(p) or p.is_relative_to(args.output)
                    for p in (args.assets, args.run_root, args.first_attempt, REPOSITORY)), "Output overlaps protected inputs")
    protocol, sources = read(HERE / "PROTOCOL.json"), registration(args.registered_commit)
    inputs, freeze = verify_inputs(protocol, args)
    sys.path.insert(0, str(REPOSITORY))
    if args.phase == "parent":
        parent(args, protocol, sources, inputs, freeze)
    else:
        phase_child(args, protocol, sources, inputs, freeze)


if __name__ == "__main__":
    main()
