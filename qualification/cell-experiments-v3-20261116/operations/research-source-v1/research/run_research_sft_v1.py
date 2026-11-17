"""Bounded, post-failure authored-target research; never native qualification.

Default preflight reads retained evidence only. Real fits require --mode run.
All four plans precede every fit; all six arms retain the original budgets.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import signal
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_sft_contract_v1 as contract

io = inputs = None


def configure(directory):
    global io, inputs
    h = contract.bind_helpers(directory)
    io, inputs = h.io, h.inputs
    return h


def schedule():
    return contract.helpers().runner.schedule()


def prepare(root, source, readiness_directory, output, mode, diagnostic_path, diagnostic_sha):
    """Only read verified retained evidence; zero model or verifier executions."""
    root, source, readiness_directory, output, diagnostic_path = map(
        Path, (root, source, readiness_directory, output, diagnostic_path))
    h = contract.helpers()
    io.require(mode in ("preflight", "run"), "explicit research preparation mode required")
    io.workspace_guard(root, source, readiness_directory, output, diagnostic_path,
                       h.directory, Path(__file__).resolve().parent)
    protected = (source, readiness_directory, h.directory, Path(__file__).resolve().parent,
                 diagnostic_path.parent)
    io.require(source != readiness_directory
               and all(not output.is_relative_to(path) and not path.is_relative_to(output)
                       for path in protected),
               "output must be separate from frozen source, helpers and prior evidence")
    output.mkdir(parents=True, exist_ok=False)
    before = io.usage()
    io.write_new(output / "STARTED.json", {
        "schema": "hepta.research-sft-operation.v1", "mode": mode,
        "started_at_ns": time.time_ns(), "budget": io.BUDGET, **contract.SCOPE})
    try:
        source_manifest = io.read(root / "operations/QWEN_SOURCE_02.json", io.SOURCE_MANIFEST_SHA)
        io.require(not inputs.FORBIDDEN.intersection(source_manifest["files"]),
                   "confirmation source is forbidden")
        io.verify_inventory(source, source_manifest["files"], exact=True)
        io.bootstrap(source)
        context = contract.load_context(root, source, readiness_directory)
        io.runtime_guard(io.RUNTIME_ROOT, context["runtime"])
        contract.diagnostic_guard(diagnostic_path, diagnostic_sha)
        io.write_new(output / "INPUTS.json", context)
        freeze = io.sealed({
            "schema": "hepta.research-sft-freeze.v1", "status": "REFERENCE_ADMITTED",
            "profile": contract.PROFILE, "admission_policy": contract.ADMISSION,
            "operation_id": "research-authored-sft-" + io.digest({
                "output": str(output), "started": time.time_ns()}),
            "created_at_ns": time.time_ns(), "artifact_root": str(root),
            "workspace_root": str(root), "runtime_root": str(io.RUNTIME_ROOT),
            "source": str(source), "helper_directory": str(h.directory),
            "output": str(output), "readiness_directory": str(readiness_directory),
            "inputs_path": str(output / "INPUTS.json"),
            "inputs_sha256": io.file_hash(output / "INPUTS.json"),
            "parent_digest": io.digest(context["parent"]),
            "parent_readiness_digest": io.digest(context["readiness"]),
            "parent_successful_A_tasks": context["gate"]["successful_A_tasks"],
            "reference_admission_digest": io.digest(context["research_admission"]),
            "baseline_result_sha256": contract.PARENT03_RESULT_SHA,
            "baseline_freeze_sha256": contract.PARENT03_FREEZE_SHA,
            "source_inventory": context["source_inventory"],
            "helper_inventory": dict(contract.HELPERS04),
            "research_inventory": contract.research_inventory(),
            "readiness_inventory": context["readiness_inventory"],
            "runtime": context["runtime"], "budget": io.BUDGET,
            "schedule": schedule(), "fitting_modes": io.FIT_MODES,
            "fit_plans_must_precede_all_fits": True,
            "diagnostic_freeze": {"path": str(diagnostic_path), "sha256": diagnostic_sha},
            "reference_rechecks": "12 correction checks plus 24 fit checks; not student experience",
            "controlled_reuse": "actual parent03 A raw steps; zero new calls for reused observations",
            "retrieval_rule": "verified authored A only; frozen retrieve; no same task/lineage",
            "selection": "no winner; exposed B is descriptive development only",
            **contract.SCOPE})
        contract.guard(freeze)
        io.write_new(output / "FREEZE.json", freeze)
        io.write_new(output / "PREFLIGHT.json", io.sealed({
            "schema": "hepta.research-sft-preflight.v1", "status": freeze["status"],
            "mode": mode, "freeze_digest": io.digest(freeze),
            "parent_successful_A_tasks": freeze["parent_successful_A_tasks"],
            "fit_attempts_started": 0, "model_loads": 0, "new_model_calls": 0,
            "new_reference_calls": 0, "cost": io.cost(before), **contract.SCOPE}))
        return context, freeze, before
    except BaseException as error:
        io.write_new(output / "PREPARATION_FAILED.json", {
            "status": "FAILED_PRESERVED", "error": repr(error),
            "traceback": traceback.format_exc(), "model_loads": 0,
            "fit_attempts_started": 0, "new_model_calls": 0, "new_reference_calls": 0,
            "cost": io.cost(before), "automatic_retry": False, **contract.SCOPE})
        raise


def child(freeze, entry, extra, deadline):
    output = Path(freeze["output"])
    contract.guard(freeze)
    remaining = deadline - time.monotonic()
    io.require(remaining > 0, "frozen operation wall budget exhausted")
    seconds = min(entry["wall_seconds"], remaining)
    name = entry["arm"] + "-" + entry["phase"]
    job = io.sealed({
        "schema": "hepta.research-sft-job.v1", "schedule_entry": entry,
        "freeze_path": str(output / "FREEZE.json"),
        "freeze_sha256": io.file_hash(output / "FREEZE.json"),
        "worker_wall_seconds": seconds, **extra, **contract.SCOPE})
    job_path = output / "jobs" / (name + ".json")
    io.write_new(job_path, job)
    command = [
        freeze["runtime"]["python"], "-I", "-B",
        str(Path(__file__).parent / "research_sft_execution_v1.py"),
        "--helper-directory", freeze["helper_directory"], "--job", str(job_path)]
    exited = io.launch(command, output / "processes" / name, seconds)
    result_path = output / "workers" / name / "RESULT.json"
    result, error, identity = None, None, None
    if result_path.is_file() and not result_path.is_symlink():
        identity = {"path": str(result_path), "sha256": io.file_hash(result_path),
                    "bytes": result_path.stat().st_size}
    if exited["exit_code"] == 0:
        try:
            result = io.read(result_path)
            io.verify_receipt(result)
            contract.scope_guard(result)
            expected_status = "RESEARCH_PLANS_FROZEN" if entry["phase"] == "collect" else "COMPLETE"
            io.require(result.get("schema") == "hepta.research-sft-worker.v1"
                       and result.get("status") == expected_status
                       and result["job_digest"] == io.digest(job)
                       and result["freeze_digest"] == io.digest(freeze)
                       and (result["arm"], result["phase"]) == (entry["arm"], entry["phase"])
                       and result["pid"] == exited["pid"], "child result identity differs")
        except Exception as problem:
            result, error = None, repr(problem)
    return {
        "arm": entry["arm"], "phase": entry["phase"], "exit": exited,
        "retained_result_identity": identity, "result_error": error,
        "result_path": str(result_path) if result is not None else None,
        "result_sha256": identity["sha256"] if result is not None else None,
        "result": result}


def cold_comparison(primary, cold):
    return {**contract.helpers().runner.cold_comparison(primary, cold), **contract.SCOPE}


def raw_ledger(output, children, *, operation_complete=False):
    """Retained known subtotals survive missing/corrupt files; unknown is not zero."""
    workers = Path(output) / "workers"
    errors, gaps = [], []

    def identity(path, problem):
        item = {"path": str(path), "error": str(problem), "sha256": None, "bytes": None}
        try:
            item.update(sha256=io.file_hash(path), bytes=path.stat().st_size)
        except Exception as unavailable:
            item["identity_error"] = repr(unavailable)
        return item

    def read_objects(pattern):
        paths = sorted(workers.rglob(pattern))
        values = {}
        for path in paths:
            try:
                row = io.read(path)
                io.require(type(row) is dict, "object receipt required")
                values[path] = row
            except Exception as problem:
                errors.append(identity(path, repr(problem)))
        return paths, values

    request_paths, requests = read_objects("request-*.json")
    output_paths, raw_outputs = read_objects("output-*.json")
    step_paths, raw_steps = read_objects("step-*.json")
    reference_request_paths, reference_requests = read_objects("REFERENCE_REQUEST.json")
    reference_paths, raw_references = read_objects("REFERENCE.json")
    outputs, steps, references = {}, {}, {}
    for path, row in raw_outputs.items():
        try:
            io.require(all(type(row.get(key)) is int and row[key] >= 0
                           for key in ("input_tokens", "output_tokens")), "invalid token measurement")
            io.require(row["input_tokens"] <= io.BUDGET["max_input_tokens"]
                       and row["output_tokens"] <= io.BUDGET["max_new_tokens"],
                       "per-call token budget exceeded")
            io.require(type(row.get("answer")) is str, "raw answer is absent")
            outputs[path] = row
        except Exception as problem:
            errors.append(identity(path, repr(problem)))
    for path, row in raw_steps.items():
        try:
            io.verify_receipt(row)
            request_path = path.with_name(path.name.replace("step-", "request-", 1))
            output_path = path.with_name(path.name.replace("step-", "output-", 1))
            io.require(request_path in requests and output_path in outputs,
                       "step lacks readable request/output")
            io.require(row.get("request_sha256") == io.digest(requests[request_path])
                       and row.get("output") == outputs[output_path], "step and raw files disagree")
            io.require(row.get("verification") is None or type(row["verification"]) is dict,
                       "invalid verification receipt")
            steps[path] = row
        except Exception as problem:
            errors.append(identity(path, repr(problem)))
    for path, row in raw_references.items():
        try:
            request = reference_requests.get(path.parent / "REFERENCE_REQUEST.json")
            io.require(request is not None and row.get("record_id") == request.get("record_id")
                       and row.get("answer_sha256") == request.get("answer_sha256")
                       and type(row.get("success")) is bool
                       and isinstance(row.get("receipt_sha256"), str),
                       "reference lacks a bound retained request or receipt")
            references[path] = row
        except Exception as problem:
            errors.append(identity(path, repr(problem)))

    for path in request_paths:
        out = path.with_name(path.name.replace("request-", "output-", 1))
        step = path.with_name(path.name.replace("request-", "step-", 1))
        if path not in requests or out not in outputs or step not in steps:
            gaps.append({"request": str(path), "output_available": out in outputs,
                         "step_available": step in steps})
    for path in output_paths:
        request = path.with_name(path.name.replace("output-", "request-", 1))
        if request not in requests:
            gaps.append({"orphan_output": str(path)})
    for path in reference_request_paths:
        if path not in reference_requests or path.parent / "REFERENCE.json" not in references:
            gaps.append({"reference_request_without_readable_completion": str(path)})
    for path in reference_paths:
        if path.parent / "REFERENCE_REQUEST.json" not in reference_requests:
            gaps.append({"orphan_reference": str(path)})

    training_steps = []
    for path in sorted(workers.rglob("STEPS.jsonl")):
        try:
            io.require(not path.is_symlink() and path.is_file(),
                       "regular nonsymlink training log required")
            raw_file = path.read_bytes()
        except Exception as problem:
            errors.append(identity(path, repr(problem)))
            continue
        seen = set()
        for line_number, raw in enumerate(raw_file.splitlines(keepends=True), 1):
            try:
                io.require(raw.endswith(b"\n"), "incomplete durable JSONL line")
                row = json.loads(raw)
                io.require(type(row) is dict and type(row.get("step")) is int
                           and 1 <= row["step"] <= io.BUDGET["fit_steps_per_arm"]
                           and row["step"] not in seen, "invalid or duplicated optimizer-step receipt")
                io.require(all(type(row.get(k)) is int and row[k] >= 0
                               for k in ("input_tokens", "supervised_tokens", "padded_positions")),
                           "invalid training token receipt")
                io.require(0 < row["supervised_tokens"] <= row["input_tokens"]
                           <= row["padded_positions"] == io.BUDGET["sequence_tokens"],
                           "training sequence or token budget changed")
                io.require(type(row.get("loss")) in (int, float) and math.isfinite(row["loss"]),
                           "nonfinite step loss")
                seen.add(row["step"])
                training_steps.append(row)
            except Exception as problem:
                errors.append({**identity(path, repr(problem)), "line_number": line_number,
                               "line_sha256": hashlib.sha256(raw).hexdigest(), "line_bytes": len(raw)})
        if seen and seen != set(range(1, max(seen) + 1)):
            gaps.append({"training_steps_not_contiguous": str(path), "observed_steps": sorted(seen)})

    verified = sum(row["verification"] is not None for row in steps.values())
    input_subtotal = sum(row["input_tokens"] for row in outputs.values()) if outputs else None
    output_subtotal = sum(row["output_tokens"] for row in outputs.values()) if outputs else None
    padded_subtotal = sum(row["padded_positions"] for row in training_steps) if training_steps else None
    complete = (
        operation_complete is True and len(children) == len(schedule())
        and all(row.get("result") is not None and row["exit"]["exit_code"] == 0 for row in children)
        and not errors and not gaps)
    checks = (
        ("request_intents", len(request_paths), "maximum_model_calls"),
        ("completed_outputs", len(outputs), "maximum_model_calls"),
        ("generated_tokens_measured", output_subtotal or 0, "maximum_generated_tokens"),
        ("student_verifier_receipts", verified, "maximum_evaluation_verifier_calls"),
        ("reference_intents", len(reference_request_paths), "maximum_reference_rechecks"),
        ("reference_completions", len(references), "maximum_reference_rechecks"),
        ("optimizer_step_receipts", len(training_steps), "maximum_training_steps"),
        ("padded_positions_measured", padded_subtotal or 0, "maximum_padded_training_positions"))
    violations = [{"counter": name, "observed": value, "maximum": io.BUDGET[bound]}
                  for name, value, bound in checks if value > io.BUDGET[bound]]
    complete = complete and not violations
    return {
        "schema": "hepta.research-sft-retained-ledger.v1",
        "persisted_requests": len(request_paths), "readable_requests": len(requests),
        "persisted_output_files": len(output_paths), "completed_output_receipts": len(outputs),
        "model_calls": len(outputs) if complete else None,
        "calls_without_completed_output_receipt": sum(
            path.with_name(path.name.replace("request-", "output-", 1)) not in outputs
            for path in request_paths),
        "input_tokens_measured_subtotal": input_subtotal,
        "output_tokens_measured_subtotal": output_subtotal,
        "input_tokens": input_subtotal if complete else None,
        "output_tokens": output_subtotal if complete else None,
        "student_verification_receipts": verified,
        "student_verifier_calls": verified if complete else None,
        "authored_reference_request_files": len(reference_request_paths),
        "authored_reference_receipts": len(references),
        "reference_calls": len(references) if complete else None,
        "reference_batch_summaries_counted_again": False,
        "completed_training_step_receipts": len(training_steps),
        "training_steps": len(training_steps) if complete else None,
        "padded_training_positions_measured_subtotal": padded_subtotal,
        "failed_attempt_measurement_complete": complete,
        "measurement_errors": errors, "measurement_gaps": gaps,
        "budget_violations": violations, "global_totals_unknown": not complete,
        "controlled_reuse_adds_model_calls": 0, "controlled_reuse_adds_verifier_calls": 0,
        "cold_outputs_are_repeated_observations": True,
        "scope": "new retained worker files; prior readiness costs excluded and separately linked",
        "unknown_generation_before_request_or_after_output_is_not_inferred_zero": True,
        **contract.SCOPE}


def fit_counts(output):
    started, completed, errors = [], [], []
    for arm in io.FIT_MODES:
        directory = Path(output) / "workers" / (arm + "-primary") / "research-model"
        if (directory / "STARTED.json").exists():
            started.append(arm)
        if (directory / "TRAINING.json").exists():
            try:
                row = io.read(directory / "TRAINING.json")
                contract.scope_guard(row)
                io.require(row.get("schema") == "hepta.research-authored-sft-training.v1"
                           and row.get("status") == "COMPLETE" and row.get("steps") == 64,
                           "incomplete research training receipt")
                completed.append(arm)
            except Exception as problem:
                errors.append({"arm": arm, "error": repr(problem)})
    return {
        "fit_attempts_started": len(started), "fit_attempt_arms": started,
        "fits_completed": len(completed), "completed_fit_arms": completed,
        "fit_counter_errors": errors,
        "started_definition": "durable train entry; does not imply any optimizer update"}


def run(context, freeze, before):
    output = Path(freeze["output"])
    deadline = time.monotonic() + max(
        0, io.BUDGET["operation_wall_seconds"] - (time.perf_counter() - before["wall"]))
    children, comparisons = [], {}
    try:
        collection = child(freeze, freeze["schedule"][0], {}, deadline)
        children.append(collection)
        io.require(collection["result"] is not None
                   and collection["result"]["status"] == "RESEARCH_PLANS_FROZEN",
                   "correction/four-plan preparation failed; no fits launched")
        for arm in io.ARMS:
            primary_entry = next(row for row in freeze["schedule"]
                                 if row["arm"] == arm and row["phase"] == "primary")
            if arm in io.FIT_MODES:
                extra = {**collection["result"]["plans"][arm],
                         "collection_result_sha256": collection["result_sha256"]}
            else:
                path = Path(freeze["readiness_directory"]) / "parent.json"
                extra = {"manifest_path": str(path), "manifest_sha256": io.file_hash(path)}
            primary = child(freeze, primary_entry, extra, deadline)
            children.append(primary)
            if primary["result"] is None:
                comparisons[arm] = {"status": "BLOCKED",
                                    "reason": "primary failed; preserved without retry", **contract.SCOPE}
                continue
            identity = primary["result"]["manifest"]
            cold_entry = next(row for row in freeze["schedule"]
                              if row["arm"] == arm and row["phase"] == "cold")
            cold = child(freeze, cold_entry, {
                "manifest_path": identity["path"], "manifest_sha256": identity["sha256"],
                "primary_manifest": identity, "primary_pid": primary["result"]["pid"],
                "primary_result_sha256": primary["result_sha256"]}, deadline)
            children.append(cold)
            comparisons[arm] = cold_comparison(primary["result"], cold["result"]) if cold["result"] else {
                "status": "BLOCKED", "reason": "cold failed; preserved without retry", **contract.SCOPE}
        contract.guard(freeze)
        complete = len(children) == len(freeze["schedule"]) and all(row["result"] for row in children)
        ledger = raw_ledger(output, children, operation_complete=complete)
        io.require(not ledger["budget_violations"], "retained evidence exceeds a frozen budget")
        counts = fit_counts(output)
        complete = complete and ledger["failed_attempt_measurement_complete"] and not counts["fit_counter_errors"]
        result = io.sealed({
            "schema": "hepta.research-sft-result.v1",
            "status": "RESEARCH_COMPLETE_UNQUALIFIED" if complete else "RESEARCH_PARTIAL_UNQUALIFIED",
            "freeze_digest": io.digest(freeze), **counts,
            "children": children, "cold_comparisons": comparisons, "ledger": ledger,
            "cost": {**io.cost(before),
                     "scope": "whole coordinator plus completed children; nested figures are not additive"},
            "prior_readiness_digest": io.digest(context["readiness"]),
            "prior_readiness_cost_included": False,
            "prior_readiness_operation": {
                "path": str(Path(freeze["readiness_directory"]) / "RESULT.json"),
                "sha256": contract.PARENT03_RESULT_SHA,
                "cost": context["parent_operation"].get("cost"),
                "cost_missing_is_unknown": True},
            "E1_E2_scope": "post-failure descriptive old-B and A-retention comparisons only",
            "no_positive_capability_conclusion_from_completion": True, **contract.SCOPE})
        io.write_new(output / "RESULT.json", result)
        return result
    except BaseException as error:
        ledger = raw_ledger(output, children, operation_complete=False)
        io.write_new(output / "FAILED.json", {
            "status": "FAILED_PRESERVED", "error": repr(error),
            "traceback": traceback.format_exc(), "children": children,
            "cold_comparisons": comparisons, "ledger": ledger,
            "cost": io.cost(before), "automatic_retry": False,
            "partial_files_preserved": True, **fit_counts(output), **contract.SCOPE})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact-root", "source", "readiness-directory", "output",
                 "helper-directory", "diagnostic-freeze"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--diagnostic-freeze-sha256", required=True)
    parser.add_argument("--mode", choices=("preflight", "run"), default="preflight")
    args = parser.parse_args()
    configure(args.helper_directory)

    def interrupted(signum, _frame):
        raise KeyboardInterrupt("research coordinator interrupted: " + str(signum))

    signal.signal(signal.SIGTERM, interrupted)
    context, freeze, before = prepare(
        args.artifact_root, args.source, args.readiness_directory, args.output,
        args.mode, args.diagnostic_freeze, args.diagnostic_freeze_sha256)
    result = run(context, freeze, before) if args.mode == "run" else {
        "status": freeze["status"], "mode": "preflight", "fit_attempts_started": 0}
    print(io.canonical({"status": result["status"], "output": str(args.output),
                        **contract.SCOPE}).decode(), flush=True)


if __name__ == "__main__":
    main()
