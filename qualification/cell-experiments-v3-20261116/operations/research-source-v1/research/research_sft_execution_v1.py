"""One research-only worker: shadow, authored fit, or exposed-task regression."""

import argparse
import copy
import gc
import os
from pathlib import Path
import signal
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_sft_contract_v1 as contract

io = inputs = panel_measurement = None


def configure(directory):
    global io, inputs, panel_measurement
    h = contract.bind_helpers(directory)
    io, inputs, panel_measurement = h.io, h.inputs, h.execution.panel_measurement
    return h


class WorkerDeadline(BaseException):
    """Preserve worker failures even if a model/backend outlasts its budget."""


def corrected(original, observed, mode, directory):
    """One saved reference recheck per correction, separate from model experience."""
    from cell_experiments import data, protocol_v3 as protocol
    from cell_experiments.repo_interaction_v2 import corrected_record

    io.require(mode in ("shadow", "controlled") and original["split"] == "train",
               "A-only explicit correction mode required")
    if mode == "shadow":
        io.require(all(step["verification"] is None and step["executed"] is False
                       and step["semantic_measurement"] == "unmeasured" for step in observed["steps"]),
                   "executed observations cannot be relabeled shadow")
    record = corrected_record(original, observed, mode)
    io.require(all(event.get("trainable") is False for event in record["trajectory"]
                   if event["actor"] == "student"), "student actions cannot become targets")
    protocol.require_prepared(record)
    # Same binding as protocol.verify_reference, with its single verifier call
    # saved before admission so even a failing reference receipt is retained.
    receipt = contract.recheck_reference(record, directory)
    io.require(inputs.semantic(record, record["final_answer"], receipt)["business_success"] is True,
               "authored correction reference failed business verification")
    record["protocol_reference_receipt"] = receipt
    record["verified_outcome"] = {"success": True, "receipt_sha256": receipt["receipt_sha256"],
                                  "verifier_name": "repo_patch", "verifier_version": "1"}
    data.validate_record(record)
    io.write_new(Path(directory) / "RECORD.json", record)
    return data._parse(data.canonical(record))


def collect(context, freeze, output):
    from cell_experiments import causal_probe_v3 as probe
    from cell_experiments import data, repo_execution, repo_interaction_v3 as interaction

    a = context["records"][:6]
    contract.reference_admission(a, context, "trajectory")
    repo_execution.load_catalog("open")
    predictor = probe.Predictor(context["parent"], freeze["artifact_root"])
    observations = []
    try:
        io.require(predictor.model_digest == data.digest(context["parent"])
                   and predictor.generation_digest == context["generation_digest"],
                   "shadow parent/generation differs from actual readiness")
        for index, record in enumerate(a):
            observations.append(interaction.attempts(
                predictor, record, output / "shadow" / str(index), maximum=1, execute=False))
    finally:
        predictor.close()
    # No previous executed attempt is relabeled as a fresh shadow prediction.
    controlled = context["gate"]["controlled_observations"]
    io.write_new(output / "CONTROLLED_REUSE.json", {
        "source_readiness_directory": freeze["readiness_directory"],
        "source_readiness_digest": data.digest(context["readiness"]),
        "observations": controlled, "new_model_calls": 0, "new_verifier_calls": 0,
        "repeated_observation": True, **contract.SCOPE})
    cohorts = {"final_answer": a, "trajectory": a}
    for mode, observed_rows in (("shadow", observations), ("controlled", controlled)):
        cohorts[mode + "_correction"] = [corrected(
            row, observed, mode, output / "corrections" / mode / str(index))
            for index, (row, observed) in enumerate(zip(a, observed_rows))]
    # Freeze all four plans before any fit starts. This also checks A authorization
    # and actual authored-reference admission; source hashes are part of each plan.
    plans = {}
    for arm, mode in io.FIT_MODES.items():
        io.write_new(output / (arm + ".records.json"), cohorts[arm])
        plans[arm] = contract.make_plan(
            cohorts[arm], context, mode, freeze["operation_id"] + "/" + arm)
        io.write_new(output / (arm + ".plan.json"), plans[arm])
    io.write_new(output / "PLANS.json", plans)
    steps = [step for row in observations for step in row["steps"]]
    return {"status": "RESEARCH_PLANS_FROZEN", "plans_digest": data.digest(plans),
            "plans": {arm: {"records_path": str(output / (arm + ".records.json")),
                            "records_sha256": io.file_hash(output / (arm + ".records.json")),
                            "plan_path": str(output / (arm + ".plan.json")),
                            "plan_sha256": io.file_hash(output / (arm + ".plan.json"))}
                      for arm in io.FIT_MODES},
            "new_model_calls": len(steps), "shadow_execute": False,
            "new_student_verifier_calls": 0, "new_reference_rechecks": 12,
            "input_tokens": sum(step["output"]["input_tokens"] for step in steps),
            "output_tokens": sum(step["output"]["output_tokens"] for step in steps),
            "controlled_reused_model_calls": sum(len(row["steps"]) for row in controlled),
            "controlled_new_model_calls": 0, "controlled_new_verifier_calls": 0,
            "correction_origin": "authored A references; student events trainable=False"}


def evaluate(context, freeze, manifest, output, arm, phase):
    from cell_experiments import causal_probe_v3 as probe
    import research_sft_train_v1 as train
    from cell_experiments import data, repo_execution, repo_interaction_v3 as interaction

    output.mkdir(parents=True, exist_ok=False)
    parent = context["parent"]
    io.require(manifest.get("runtime") == parent["runtime"]
               and (manifest == parent or manifest.get("base_manifest") == parent),
               "evaluation must use the same base and frozen generation settings")
    repo_execution.load_catalog("open")
    torch, _ = probe._libraries()
    # train() locals release their tensors only after its finally block returns.
    # Reclaim those now-unused allocations before the unchanged 4 GiB check.
    gc.collect()
    torch.cuda.empty_cache()
    probe.check_device(torch, parent["runtime"])
    torch.cuda.reset_peak_memory_stats(0)
    before = io.usage()
    predictor = train.load_predictor(manifest, freeze["artifact_root"])
    panels = context["panels"]
    shown_panels = context["retrieval_panels"] if arm == "retrieval" else panels
    io.write_new(output / "ORIGINAL_PANELS.json", panels)
    io.write_new(output / "SHOWN_PANELS.json", shown_panels)
    io.write_new(output / "MODEL_LOADED.json", {
        "model_digest": predictor.model_digest, "generation_digest": predictor.generation_digest,
        "generation": predictor.generation.to_dict(), "pid": os.getpid(),
        "device": predictor.device_report, "phase": phase,
        "process_cold_relative_to_primary": phase == "cold"})
    rows, panel_measurements = [], {}
    try:
        io.require(predictor.model_digest == data.digest(manifest)
                   and predictor.generation_digest == context["generation_digest"],
                   "loaded evaluation model or generation differs")
        for panel, records in panels.items():
            directory = output / panel
            directory.mkdir(exist_ok=False)
            panel_rows, panel_before = [], io.usage()
            io.write_new(directory / "STARTED.json", {
                "panel": panel, "arm": arm, "phase": phase, "started_at_ns": time.time_ns(),
                "model_digest": data.digest(manifest), "original_records_digest": data.digest(records),
                "shown_records_digest": data.digest(shown_panels[panel]),
                "usage_before": panel_before, "maximum_attempts": 2,
                "includes_model_load_or_close": False, "nested_scopes_are_not_additive": True})
            try:
                for index, (original, shown) in enumerate(zip(records, shown_panels[panel])):
                    observed = interaction.attempts(predictor, shown, directory / str(index),
                                                    maximum=2, execute=True)
                    evidence = [inputs.semantic(shown, step["output"]["answer"], step["verification"])
                                for step in observed["steps"]]
                    io.require(observed["success"] is (evidence[-1]["business_success"] is True),
                               "business result lacks actual original/control evidence")
                    panel_rows.append({**observed, "panel": panel,
                                       "original_task_digest": data.digest(original),
                                       "shown_task_digest": data.digest(shown), "business_evidence": evidence})
                measurement = panel_measurement(directory, io.cost(panel_before), panel_rows, len(records))
                measurement.update(status="COMPLETE", panel=panel, arm=arm, phase=phase, **contract.SCOPE)
                measurement = io.sealed(measurement)
                io.write_new(directory / "MEASUREMENT.json", measurement)
                panel_measurements[panel] = measurement
                rows.extend(panel_rows)
            except BaseException as error:
                measurement = panel_measurement(directory, io.cost(panel_before), panel_rows, len(records))
                io.write_new(directory / "FAILED.json", io.sealed({
                    **measurement, "status": "FAILED_PRESERVED", "panel": panel,
                    "arm": arm, "phase": phase, "error": repr(error),
                    "traceback": traceback.format_exc(), "automatic_retry": False, **contract.SCOPE}))
                raise
    finally:
        predictor.close()
    steps = [step for row in rows for step in row["steps"]]
    calls = [evidence["completed_original_calls"] for row in rows for evidence in row["business_evidence"]]
    measured = [count for count in calls if type(count) is int]
    result = io.sealed({
        "schema": "hepta.research-sft-evaluation.v1", "status": "COMPLETE",
        "arm": arm, "phase": phase, "pid": os.getpid(), "model_digest": data.digest(manifest),
        "generation_digest": context["generation_digest"], "maximum_attempts": 2,
        "max_new_tokens": 384, "original_panels_digest": data.digest(panels),
        "shown_panels_digest": data.digest(shown_panels),
        "retrieval_bindings": context["retrieval_bindings"] if arm == "retrieval" else None,
        "rows": rows, "successful_tasks": sum(row["success"] for row in rows),
        "panel_measurements": panel_measurements,
        "by_panel": {panel: {"tasks": len(records),
                              "successful_tasks": sum(row["success"] for row in rows if row["panel"] == panel),
                              "first_attempt_successes": sum(row["first_attempt_success"] for row in rows if row["panel"] == panel)}
                     for panel, records in panels.items()},
        "model_calls": len(steps), "verifier_calls": len(steps),
        "executed_attempts": sum(step["executed"] for step in steps),
        "completed_original_calls": sum(measured) if len(measured) == len(calls) else None,
        "completed_original_calls_measured_subtotal": sum(measured) if measured else None,
        "completed_original_calls_missing_attempts": len(calls) - len(measured),
        "input_tokens": sum(step["output"]["input_tokens"] for step in steps),
        "output_tokens": sum(step["output"]["output_tokens"] for step in steps),
        "output_cap_hits": sum(step["output"]["hit_output_limit"] for step in steps),
        "cost": {**io.cost(before), "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
                 "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(0),
                 "scope": "this evaluation including load/close and completed verifier children"},
        "repeated_exposed_tasks": True, "cold_is_repeat_of_primary": phase == "cold", **contract.SCOPE})
    io.write_new(output / "EVALUATION.json", result)
    return result


def run_job(job_path):
    job = io.read(job_path)
    io.verify_receipt(job)
    contract.scope_guard(job)
    io.require(job.get("schema") == "hepta.research-sft-job.v1", "separate research job required")
    freeze = io.read(job["freeze_path"], job["freeze_sha256"])
    io.verify_receipt(freeze)
    io.require(freeze["schema"] == "hepta.research-sft-freeze.v1"
               and freeze["status"] == "REFERENCE_ADMITTED" and freeze["profile"] == contract.PROFILE,
               "valid separate research reference admission required")
    io.require(job["schedule_entry"] in freeze["schedule"], "job is outside frozen schedule")
    seconds = job["worker_wall_seconds"]
    io.require(type(seconds) in (int, float) and 0 < seconds <= job["schedule_entry"]["wall_seconds"],
               "worker timeout exceeds frozen stage budget")
    arm, phase = job["schedule_entry"]["arm"], job["schedule_entry"]["phase"]
    output = io.safe_path(freeze["output"], "workers/" + arm + "-" + phase)
    output.mkdir(parents=True, exist_ok=False)
    before = io.usage()
    io.write_new(output / "STARTED.json", {"job": job, "pid": os.getpid(), "started_at_ns": time.time_ns(), **contract.SCOPE})
    def deadline(_signum, _frame):
        raise WorkerDeadline("worker wall budget exhausted")
    signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        contract.guard(freeze)
        io.bootstrap(freeze["source"])
        context = io.read(freeze["inputs_path"], freeze["inputs_sha256"])
        io.require(context["gate"]["successful_A_tasks"] == freeze["parent_successful_A_tasks"]
                   and io.digest(contract.reference_admission(context["records"][:6], context, "trajectory"))
                   == freeze["reference_admission_digest"],
                   "bound parent A gate changed")
        from cell_experiments import data
        import research_sft_train_v1 as train

        if phase == "collect":
            result = collect(context, freeze, output)
        else:
            training_receipt = None
            if phase == "primary" and arm in io.FIT_MODES:
                collection = io.read(Path(freeze["output"]) / "workers/corrections-collect/RESULT.json",
                                     job["collection_result_sha256"])
                io.verify_receipt(collection)
                io.require(collection["status"] == "RESEARCH_PLANS_FROZEN"
                           and collection["freeze_digest"] == data.digest(freeze)
                           and all(job.get(key) == value for key, value in collection["plans"][arm].items()),
                           "fit inputs differ from the complete frozen four-arm plan bundle")
                collection_directory = Path(freeze["output"]) / "workers/corrections-collect"
                bundle = io.read(collection_directory / "PLANS.json")
                io.require(set(bundle) == set(io.FIT_MODES)
                           and data.digest(bundle) == collection["plans_digest"],
                           "all four plans must already be retained before every fit")
                for planned_arm, binding in collection["plans"].items():
                    io.require(Path(binding["plan_path"]) == collection_directory / (planned_arm + ".plan.json")
                               and Path(binding["records_path"]) == collection_directory / (planned_arm + ".records.json"),
                               "plan inputs escaped the retained collection")
                    retained = io.read(binding["plan_path"], binding["plan_sha256"])
                    io.read(binding["records_path"], binding["records_sha256"])
                    io.require(retained == bundle[planned_arm]
                               and retained["operation_id"] == freeze["operation_id"] + "/" + planned_arm,
                               "fit plan differs from the original four-plan bundle")
                records = io.read(job["records_path"], job["records_sha256"])
                plan = io.read(job["plan_path"], job["plan_sha256"])
                io.require(plan["mode"] == io.FIT_MODES[arm]
                           and plan["training"]["steps"] == 64
                           and plan["training"]["sequence_tokens"] == io.BUDGET["sequence_tokens"],
                           "fit mode or budget changed")
                _, training_receipt = train.train(records, context["parent"], freeze["artifact_root"],
                                                  plan, output / "research-model", context)
                manifest_path = output / "research-model/manifest.json"
            else:
                if phase == "cold":
                    primary = io.read(Path(freeze["output"]) / "workers" / (arm + "-primary/RESULT.json"),
                                      job["primary_result_sha256"])
                    io.verify_receipt(primary)
                    io.require(primary["freeze_digest"] == data.digest(freeze)
                               and primary["manifest"] == job["primary_manifest"]
                               and primary["pid"] == job["primary_pid"],
                               "cold job differs from its actual completed primary worker")
                manifest_path = Path(job["manifest_path"])
                io.read(manifest_path, job["manifest_sha256"])
            manifest = io.read(manifest_path)
            if arm in ("parent", "retrieval"):
                io.require(manifest == context["parent"], "baseline differs from the frozen parent")
            identity = {"path": str(manifest_path), "sha256": io.file_hash(manifest_path),
                        "model_digest": data.digest(manifest)}
            io.write_new(output / "MODEL_IDENTITY.json", identity)
            evaluation = evaluate(context, freeze, manifest, output / "evaluation", arm, phase)
            io.require(io.file_hash(manifest_path) == identity["sha256"], "manifest changed during evaluation")
            result = {"status": "COMPLETE", "manifest": identity, "evaluation": evaluation,
                      "training": training_receipt, "new_model_calls": evaluation["model_calls"],
                      "new_student_verifier_calls": evaluation["verifier_calls"],
                      "new_reference_rechecks": len(context["records"][:6]) if training_receipt else 0,
                      "repeated_observation": phase == "cold",
                      "primary_pid": job.get("primary_pid"),
                      "cold_manifest_exactly_matches_primary": phase == "cold" and identity == job["primary_manifest"]}
            if phase == "cold":
                io.require(result["cold_manifest_exactly_matches_primary"]
                           and os.getpid() != job["primary_pid"], "cold regression must use a separate process and exact manifest")
        contract.guard(freeze)
        result = io.sealed({"schema": "hepta.research-sft-worker.v1", **result,
                            "arm": arm, "phase": phase, "pid": os.getpid(),
                            "job_digest": data.digest(job), "freeze_digest": data.digest(freeze),
                            "worker_cost": io.cost(before), "completed_at_ns": time.time_ns(), **contract.SCOPE})
        io.write_new(output / "RESULT.json", result)
        return result
    except BaseException as error:
        io.write_new(output / "FAILED.json", {"status": "FAILED_PRESERVED", "error": repr(error),
                     "traceback": traceback.format_exc(), "cost": io.cost(before),
                     "automatic_retry": False, "partial_files_preserved": True,
                     "arm": arm, "phase": phase, **contract.SCOPE})
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--helper-directory", type=Path, required=True)
    args = parser.parse_args()
    configure(args.helper_directory)
    result = run_job(args.job)
    print(io.canonical({"arm": result["arm"], "phase": result["phase"], "status": result["status"]}).decode(), flush=True)


if __name__ == "__main__":
    main()
