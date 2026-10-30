"""Normalize three LIF cost scopes using explicit pointers to original receipts.

This is an on-demand stdlib adapter, not another analysis watcher. Supply a
bindings JSON only after the original analysis outer receipt and final watcher
snapshot exist. It verifies the successful 18-pair analysis, preserves source
hashes and field pointers, and never infers a cost from an ambiguously named
timer. The independent supervisor window is metadata for an external explicit
extra scope, not a fourth core scope or a repeated child-tree charge.
"""

import argparse
import json
import math
from pathlib import Path
import time
import traceback
import uuid

from .archive_closure import file_hash, json_pointer, read_json, require, safe_relative, write_new


PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
CORE_SCOPES = ("lif_scheduler", "lif_analysis", "lif_analysis_watcher")


def original_path(relative):
    safe_relative(relative)
    path = ROOT / relative if relative.startswith("experiments/hcsn_distributional_v2/") else PACKAGE / relative
    require(path.resolve().is_relative_to(PACKAGE) and not path.is_symlink(), "Expected an original v2 receipt")
    return path


def normalize(bindings_path, output):
    bindings_path, output = Path(bindings_path).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    require(not (output / "RECEIPTS.json").exists() and not (output / "EXECUTION.json").exists(),
            "Successful cost normalization is immutable")
    attempt = uuid.uuid4().hex
    started = time.perf_counter()
    error, status = None, "failed"
    sources = {name: file_hash(PACKAGE / name) for name in ("lif_cost_receipts.py", "archive_closure.py")}
    try:
        bindings = read_json(bindings_path)
        require(bindings["schema"] == "hcsn-lif-cost-bindings.v1", "Wrong bindings schema")
        selected = {scope["scope_id"]: scope for scope in bindings["scopes"]}
        require(set(selected) == set(CORE_SCOPES) and len(bindings["scopes"]) == 3, "Expected exactly three explicit core bindings")
        protocol_sha = file_hash(PACKAGE / "LIF_SUPPLEMENT001_PROTOCOL.json")
        study = PACKAGE / "results/lif_supplement001"
        completion = read_json(study / "COMPLETE.json")
        require(completion["status"] == "completed" and completion["expected"] == completion["completed"] == 18
                and not completion["failures"] and completion["protocol_sha256"] == protocol_sha,
                "LIF searches have not all completed successfully")
        analysis_path = PACKAGE / "results/lif_analysis001/ANALYSIS.json"
        analysis = read_json(analysis_path)
        require(analysis["status"] == "passed" and analysis["expected_pairs"] == analysis["valid_pairs"] == 18
                and analysis["protocol_sha256"] == protocol_sha
                and analysis["parent_protocol_sha256"] == file_hash(PACKAGE / "CONTENT002_PROTOCOL.json"),
                "LIF 18-pair analysis is not successful")
        scopes = []
        for scope_id in CORE_SCOPES:
            binding = selected[scope_id]
            path = original_path(binding["receipt"])
            original = read_json(path)
            value = json_pointer(original, binding["field"])
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "Invalid original CPU measurement")
            success = json_pointer(original, binding["success_field"])
            require(type(success) is type(binding["success_value"]) and success == binding["success_value"],
                    "Original receipt has not reached its successful terminal condition")
            kind = "process_self_cpu_through_receipt" if scope_id == "lif_analysis_watcher" else "complete_process_tree_wait4"
            require(binding["measurement_kind"] == kind, "Wrong measurement scope")
            if scope_id == "lif_scheduler":
                require(path.resolve() == (study / "SCHEDULER_EXECUTION.json").resolve()
                        and binding["field"] == "/complete_child_cpu_seconds"
                        and binding["success_field"] == "/exit_code" and binding["success_value"] == 0,
                        "Scheduler binding must name its actual complete wait4 tree")
                require(original["protocol_sha256"] == protocol_sha
                        and value == original["child_user_cpu_seconds"] + original["child_system_cpu_seconds"],
                        "Scheduler CPU components or protocol differ")
            elif scope_id == "lif_analysis":
                require(binding["success_value"] == 0, "Analyzer outer process did not exit successfully")
            else:
                require(binding["success_value"] not in ("waiting_for_both_complete_studies", "running", "waiting", "blocked", "failed"),
                        "An active watcher heartbeat cannot be normalized as final")
            scopes.append(dict(scope_id=scope_id, receipt=str(path.relative_to(ROOT)), receipt_sha256=file_hash(path),
                field=binding["field"], cpu_seconds=value, measurement_kind=kind, scope=binding["scope"],
                success_field=binding["success_field"], success_value=binding["success_value"]))
        scheduler_path = study / "SCHEDULER_EXECUTION.json"
        scheduler = read_json(scheduler_path)
        window = scheduler["outer_supervisor_self_window_cpu_seconds"]
        require(type(window) in (int, float) and math.isfinite(window) and window >= 0, "Invalid independent supervisor window")
        extra = dict(scope_id="lif_scheduler_supervisor_window", receipt=str(scheduler_path.relative_to(ROOT)),
            receipt_sha256=file_hash(scheduler_path), field="/outer_supervisor_self_window_cpu_seconds", cpu_seconds=window,
            measurement_kind="partial_process_body_timer",
            scope="Independent outer supervisor self CPU measured over its recorded window; not whole-process CPU, not part of the scheduler child tree; counted only through the separately declared extra-cost scope")
        result = dict(schema="hcsn-lif-cost-receipts.v1", status="completed", protocol_sha256=protocol_sha,
            source_sha256=sources, bindings_sha256=file_hash(bindings_path), scopes=scopes,
            additional_measured_windows=[extra], analysis=dict(path=str(analysis_path.relative_to(ROOT)), sha256=file_hash(analysis_path)),
            containment="Three disjoint core scopes: complete scheduler tree, complete analyzer child, final analysis-watcher self CPU through receipt. Worker/candidate/training/body clocks remain nested and are not added.")
        for scope in scopes:
            require(file_hash(ROOT / scope["receipt"]) == scope["receipt_sha256"], "Original receipt changed while normalizing")
        for name, expected in sources.items():
            require(file_hash(PACKAGE / name) == expected, "Normalization source changed during execution")
        write_new(output / "RECEIPTS.json", result)
        status = "completed"
        print(json.dumps(dict(status=status, scopes={scope["scope_id"]: scope["cpu_seconds"] for scope in scopes},
                              additional_window=window, receipts_sha256=file_hash(output / "RECEIPTS.json"))), flush=True)
        return result
    except BaseException:
        error = traceback.format_exc()
        raise
    finally:
        receipt_path = output / ("EXECUTION.json" if status == "completed" else "FAILED_EXECUTION_" + attempt + ".json")
        write_new(receipt_path, dict(schema="hcsn-lif-cost-normalizer-execution.v1", status=status,
            own_cpu_seconds_through_receipt=time.process_time(), wall_seconds=time.perf_counter()-started,
            source_sha256=sources, error=error, bindings_path=str(bindings_path),
            scope="This on-demand adapter process only; no child processes or watcher loop. Core training/analysis measurements are referenced original receipts, not repeated execution. Final receipt serialization/exit remains outside cutoff."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PACKAGE / "results/lif_cost_receipts001")
    args = parser.parse_args()
    normalize(args.bindings, args.output)
