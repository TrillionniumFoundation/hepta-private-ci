"""Read-only CI and nested resource accounting for the skill maintenance audit."""

from collections import Counter
import copy
from pathlib import Path

from audit_longrun_resume import audit_resource_samples
from audit_skill_longrun_support import distribution, identity, load


def audit_monitor(context):
    paths, check = context["paths"], context["check"]
    resource = load(paths.run / "resource.json")
    check("monitor_registered_roots", [paths.resolve(root) for root in resource["roots"]] == [paths.run])
    check("monitor_registered_command", any(str(value).endswith("/skill_longrun/manager.py")
                                            for value in resource["command"]))
    check("one_uninterrupted_monitor_window", resource["termination_signal"] is None
          and resource["monitor_error"] is None and resource["launch_error"] is None
          and not resource["timed_out_or_sample_cap"])
    view = copy.deepcopy(resource)
    for stream in ("stdout", "stderr"):
        view[stream]["path"] = str(paths.resolve(resource[stream]["path"]))
    audited = audit_resource_samples(paths.run / "resource-samples.jsonl", view, check, "skill", True)
    errors, storage_errors = Counter(), Counter()
    with (paths.run / "resource-samples.jsonl").open() as stream:
        import json
        for line in stream:
            row = json.loads(line)
            errors.update(item["error"] for item in row["process_errors"])
            storage_errors.update(item["error"] for item in row["storage"].get("errors", []))
    check("resource_error_classification", sum(errors.values()) + sum(storage_errors.values())
          == resource["sample_error_count"])
    window = resource["wall_ns_through_observation_close"]
    audited["coverage"] = {
        name: {"observed_ns": value["observed_interval_ns"], "unknown_ns": value["unobserved_interval_ns"],
               "observed_fraction": value["observed_interval_ns"] / window,
               "sampled_byte_ns_estimate": value["sampled_byte_ns_estimate"],
               "observed_peak_bytes": resource["peaks_of_sequential_sample_sums"][name]}
        for name, value in resource["integrals"].items()}
    audited["error_classification"] = {"process": dict(errors), "storage": dict(storage_errors)}
    return resource, audited


def audit_ci(context, summary, freeze, resource):
    paths, check = context["paths"], context["check"]
    if paths.bundle is None:
        return None
    bundle = paths.bundle
    preparation, result = load(bundle / "PREPARATION.json"), load(bundle / "CI_RESULT.json")
    hardware, source = load(bundle / "HARDWARE.json"), load(bundle / "CI_SOURCE.json")
    dependency, request = load(bundle / "DEPENDENCIES_AND_INITIALIZATION.json"), load(bundle / "REQUEST.json")
    check("ci_request", set(request) == {"schema", "request_id", "protocol_sha256", "initial_archive_sha256"}
          and request["schema"] == "hepta.memory.skill-longrun-request.v1"
          and request["protocol_sha256"] == context["protocol_sha"]
          and request["initial_archive_sha256"] == "ac5a13169fcad61eda46ee4e42c67e5549c82da48a32c1121e9727baa2ee706f")
    check("ci_source_identity", source["commit"] == result["source_commit"] == hardware["environment"]["GITHUB_SHA"]
          and source["tree"] == result["source_tree"]
          and source["protocol"] == identity(context["protocol_path"])
          and source["request"] == identity(paths.checkout / "qualification/memory-cell-adapters/skill_longrun/RUN_REQUEST.json"))
    check("ci_workflow_identity", source["workflow"]["path"] == ".github/workflows/memory-adapter-skill-longrun.yml"
          and {key: source["workflow"][key] for key in ("bytes", "sha256")}
          == identity(paths.checkout / source["workflow"]["path"]))
    check("ci_preparation_bindings", preparation == result["preparation"]
          and request == preparation["request"] == result["request"]
          and result["result"] == identity(paths.run / "RESULT.json")
          and result["resource"] == identity(paths.run / "resource.json"))
    check("ci_scope", result["scope"] == preparation["scope"] == "skill"
          and result["native_runtime_executed"] is False and result["full_cost_exact"] is False
          and result["semantic_run_costs_replaced"] is False and result["scientific_superiority_claimed"] is False
          and result["same_hardware_as_semantic_run_claimed"] is False
          and hardware["same_hardware_as_semantic_run_claimed"] is False)
    check("ci_historical_clock_separated", preparation["historical_trainer_monotonic_compared_to_runner_clock"] is False)
    check("ci_no_held_or_encoder_execution", preparation["held_json_parsed_or_supplied_to_training"] is False
          and preparation["encoder_weights_downloaded_or_reencoded"] is False and result["encoder_reexecuted"] is False)
    check("ci_dependencies", dependency["torch"] == "2.8.0+cpu" and dependency["numpy"] == "2.3.5"
          and not dependency["training_executed"] and not dependency["prediction_executed"] and not dependency["encoder_executed"])
    check("ci_initialization_probe", load(bundle / "initial-checkpoint-identities.stdout") == dependency)
    check("ci_initialization_inventory", [row["seed"] for row in dependency["initializations"]] == [731, 732, 733])
    for row in dependency["initializations"]:
        manifest = context["manifests"][str(paths.run / "inputs" / f"seed-{row['seed']}")]
        check("ci_trained_initial_identity:" + str(row["seed"]),
              row["initial_checkpoint_sha256"] == manifest["parameter_sha256"]
              and row["architecture"] == manifest["config"] and row["base_encoder_sha"] == context["encoder_sha"]
              and row["parameter_counts"] == {"adapter": 3072, "head": 10780, "total": 13852, "trainable": 13852})
    processes = {}
    for path in sorted(bundle.glob("*.process.json")):
        name, process = path.name.removesuffix(".process.json"), load(path)
        processes[name] = process
        check("ci_wrapper_process:" + name, process["exit_code"] == 0 and not process["timed_out"]
              and process["wall_ns"] == process["exited_monotonic_ns"] - process["started_monotonic_ns"]
              and process["completed_child_cpu_seconds"] >= 0)
        for kind in ("stdout", "stderr"):
            check("ci_wrapper_stream:" + name + ":" + kind,
                  identity(bundle / (name + "." + kind)) == process[kind])
    expected = {name: value for name, value in processes.items() if name not in ("lifecycle-monitor", "source-unchanged")}
    check("ci_preparation_process_inventory", sorted(expected.values(), key=lambda p: p["started_monotonic_ns"])
          == sorted(preparation["processes"], key=lambda p: p["started_monotonic_ns"]))
    check("ci_preparation_cpu_sum", abs(sum(p["completed_child_cpu_seconds"] for p in expected.values())
          - preparation["completed_children_cpu_seconds"]) < 0.000001)
    ordered = sorted(processes.values(), key=lambda p: p["started_monotonic_ns"])
    check("ci_wrapper_process_order", all(a["exited_monotonic_ns"] <= b["started_monotonic_ns"]
                                          for a, b in zip(ordered, ordered[1:])))
    monitor = processes["lifecycle-monitor"]
    check("ci_monitor_clock_binding", monitor == result["lifecycle_launcher"]
          and preparation["completed_at_monotonic_ns"] <= monitor["started_monotonic_ns"]
          <= resource["started_monotonic_ns"] < resource["child_spawned_monotonic_ns"] < freeze["created_ns"]
          and resource["observations_ended_monotonic_ns"] <= monitor["exited_monotonic_ns"])
    check("ci_preparation_before_freeze", processes["initial-checkpoint-identities"]["exited_monotonic_ns"]
          <= preparation["completed_at_monotonic_ns"] < freeze["created_ns"])
    check("ci_horizon", result["completed_cycles"] == summary["completed_cycles"] == 192
          and result["completed_fit_phases"] == summary["phase_count"] == 216 and result["fresh_reader_processes"] == 219)
    check("ci_source_unchanged", result["source_unchanged"] and processes["source-unchanged"]["exit_code"] == 0)
    if (bundle / "JOB_START.json").exists():
        marker = load(bundle / "JOB_START.json")
        check("ci_job_start_clock", marker["boot_id"] == hardware["boot_id"]
              and marker["monotonic_ns"] <= ordered[0]["started_monotonic_ns"])
    manager_cpu = sum(resource["child_exit_rusage"][key] for key in ("ru_utime", "ru_stime"))
    worker_cpu = sum(p["cpu_seconds"] for p in context["processes"].records)
    check("ci_nested_cpu_scopes", monitor["completed_child_cpu_seconds"] + 0.000001 >= manager_cpu
          and manager_cpu + 0.000001 >= worker_cpu)
    wrapper_cpu = result["wrapper_own_cpu_ns"] / 1e9 + sum(p["completed_child_cpu_seconds"] for p in processes.values())
    return {"source_commit": source["commit"], "source_tree": source["tree"],
            "ci_result": identity(bundle / "CI_RESULT.json"), "source_identity": identity(bundle / "CI_SOURCE.json"),
            "hardware": hardware, "dependencies": {key: dependency[key] for key in ("torch", "numpy", "python", "platform")},
            "preparation_wall_ns": preparation["wall_ns"],
            "preparation_child_cpu_seconds": preparation["completed_children_cpu_seconds"],
            "all_fit_and_reader_process_cpu_seconds": worker_cpu,
            "manager_and_waited_descendants_kernel_cpu_seconds": manager_cpu,
            "monitor_launcher_cpu_seconds_including_manager_tree": monitor["completed_child_cpu_seconds"],
            "monitor_launcher_wall_ns": monitor["wall_ns"],
            "wrapper_and_children_cpu_seconds_without_double_counting": wrapper_cpu,
            "wrapper_wall_ns": result["wrapper_wall_ns"], "wrapper_own_cpu_ns": result["wrapper_own_cpu_ns"],
            "checkout_and_python_setup_cpu_seconds": None, "upload_cpu_seconds": None,
            "full_cost_exact": False,
            "overlap_warning": "Fit/read costs are nested inside manager, manager inside launcher, launcher inside wrapper. Do not add these totals.",
            "origin_authentication": "This verifies downloaded contents and internal source bindings. GitHub origin/ZIP authentication is a separate retained receipt."}


def cost_summary(context, resource, ci):
    fits, readers = context["fit_records"], context["read_records"]
    timing = {}
    for name, entries in (("fit", fits), ("reader", readers)):
        timing[name + "_process_wall_ns"] = distribution([entry[0]["wall_ns"] for entry in entries])
        timing[name + "_process_cpu_seconds"] = distribution([entry[0]["cpu_seconds"] for entry in entries])
        timing[name + "_body_wall_ns"] = distribution([entry[1]["process_body_wall_ns"] for entry in entries])
        timing[name + "_body_cpu_ns"] = distribution([entry[1]["process_body_cpu_ns"] for entry in entries])
    timing["checkpoint_load_wall_ns"] = distribution([row[1]["model_load_wall_ns"] for row in readers])
    for arm in ("parameter", "exact_sql"):
        timing[arm + "_eight_workflow_loop_ns"] = distribution([
            next(value["read_wall_ns"] for value in row[1]["arms"] if value["arm"] == arm) for row in readers])
    for name in ("wall_seconds", "cpu_seconds"):
        timing["fit_method_" + name] = distribution([row[1]["training"][name] for row in fits])
    return {"timing": timing, "nested_ci_cost_scopes": ci,
            "resource_kernel_child_exit_rusage": resource["child_exit_rusage"],
            "resource_monitor_rusage_before_final_receipt": resource["monitor_rusage_before_final_receipt"],
            "full_cost_exact": False,
            "latency_boundary": "Both arms share each fresh reader in fixed parameter-then-SQL order; per-arm loops are not independent cold deployments."}
