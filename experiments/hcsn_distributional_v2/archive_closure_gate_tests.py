"""Targeted review-gate and LIF cost-adapter checks; synthetic metadata only."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .archive_closure import ClosureAudit, PACKAGE, file_hash, job_id, read_json, require, write_new


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = output / "synthetic_fixture"
    package = root / "experiments/hcsn_distributional_v2"
    package.mkdir(parents=True)
    source = output / "source"
    source.mkdir()
    original = PACKAGE / "results/archive_closure_tests001/synthetic_fixture/experiments/hcsn_distributional_v2"

    def copy(relative, where=original):
        destination = package / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(where / relative, destination)

    for name in ("evidence_bundle.py", "seal_bundle.py", "content_checkpoint_archives.py", "content_analysis.py",
                 "lif_supplement_analysis.py", "archive_closure.py", "lif_cost_receipts.py", "archive_closure_gate_tests.py"):
        copy(name, PACKAGE)
        shutil.copyfile(PACKAGE / name, source / name)
    old_archive = root / "experiments/hcsn_free_boundary_v1/archive.py"
    old_archive.parent.mkdir(parents=True)
    shutil.copyfile(PACKAGE.parent / "hcsn_free_boundary_v1/archive.py", old_archive)
    for relative in ("CONTENT002_PROTOCOL.json", "LIF_SUPPLEMENT001_PROTOCOL.json", "results/content002/COMPLETE.json",
            "results/content002/SCHEDULER_EXECUTION.json", "results/lif_supplement001/COMPLETE.json",
            "results/content_checkpoint_archives/COMPLETE.json", "results/content_analysis002/ANALYSIS.json",
            "results/lif_analysis001/ANALYSIS.json"):
        copy(relative)
    for study in ("content002", "lif_supplement001"):
        for row in read_json(package / "results" / study / "COMPLETE.json")["records"]:
            prefix = "results/" + study + "/runs/" + job_id(row["job"])
            for name in ("EXECUTION.json", "IDENTITY.json"):
                copy(prefix + "/" + name)
    main_sha = file_hash(package / "CONTENT002_PROTOCOL.json")
    lif_sha = file_hash(package / "LIF_SUPPLEMENT001_PROTOCOL.json")
    analysis_path = package / "results/content_analysis002/ANALYSIS.json"
    analysis = read_json(analysis_path)
    analysis["common_initialization_mismatches"] = []
    analysis_path.write_text(json.dumps(analysis))
    log = package / "results/content_analysis002.log"
    log.write_text("SYNTHETIC main analysis stdout\n")
    write_new(package / "results/content_analysis002/EXECUTION.json", dict(returncode=0, protocol_sha256=main_sha,
        analyzer_sha256=analysis["analyzer_sha256"], stdout_sha256=file_hash(log),
        main_scheduler_receipt_sha256=file_hash(package / "results/content002/SCHEDULER_EXECUTION.json")))
    scheduler_path = package / "results/lif_supplement001/SCHEDULER_EXECUTION.json"
    write_new(scheduler_path, dict(exit_code=0, protocol_sha256=lif_sha, complete_child_cpu_seconds=2.25,
        child_user_cpu_seconds=2.0, child_system_cpu_seconds=.25, outer_supervisor_self_window_cpu_seconds=.002,
        synthetic_fixture=True))
    outer = package / "results/lif_analysis001/ANALYSIS_OUTER_EXECUTION.json"
    write_new(outer, dict(exit_code=0, complete_child_cpu_seconds=.75, protocol_sha256=lif_sha, synthetic_fixture=True))
    watcher = package / "results/lif_supplement001/ANALYSIS_WATCHER.json"
    write_new(watcher, dict(status="waiting_for_both_complete_studies", own_cpu_seconds=.05,
                           protocol_sha256=lif_sha, synthetic_fixture=True))
    bindings = dict(schema="hcsn-lif-cost-bindings.v1", scopes=[])
    for scope_id, path, field, success_field, success_value, kind in (
            ("lif_scheduler", scheduler_path, "/complete_child_cpu_seconds", "/exit_code", 0, "complete_process_tree_wait4"),
            ("lif_analysis", outer, "/complete_child_cpu_seconds", "/exit_code", 0, "complete_process_tree_wait4"),
            ("lif_analysis_watcher", watcher, "/own_cpu_seconds", "/status", "completed", "process_self_cpu_through_receipt")):
        bindings["scopes"].append(dict(scope_id=scope_id, receipt=str(path.relative_to(root)), field=field,
            success_field=success_field, success_value=success_value, measurement_kind=kind, scope="Synthetic disjoint cost fixture"))
    binding_path = output / "BINDINGS.json"
    write_new(binding_path, bindings)
    destination = package / "results/lif_cost_receipts001"
    child_receipts = []

    def adapter(label, expected_code):
        command = [sys.executable, "-m", "experiments.hcsn_distributional_v2.lif_cost_receipts",
                   "--bindings", str(binding_path), "--output", str(destination)]
        started = time.perf_counter()
        process_log = output / (label + ".log")
        with process_log.open("x") as stream:
            child = subprocess.Popen(command, cwd=root, env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1"),
                                     stdout=stream, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        receipt = dict(label=label, returncode=child.returncode, cpu_seconds_including_children=usage.ru_utime+usage.ru_stime,
                       wall_seconds=time.perf_counter()-started, log_sha256=file_hash(process_log),
                       scope="Nested synthetic adapter child; included in full gate-test outer wait4 receipt")
        child_receipts.append(receipt)
        write_new(output / (label + "_EXECUTION.json"), receipt)
        require(child.returncode == expected_code, "Unexpected adapter exit code")

    adapter("active_watcher_rejected", 1)
    require(not (destination / "RECEIPTS.json").exists() and len(list(destination.glob("FAILED_EXECUTION_*.json"))) == 1,
            "Failed attempt published normalization or failed to retain its receipt")
    watcher.write_text(json.dumps(dict(status="completed", own_cpu_seconds=.08, protocol_sha256=lif_sha, synthetic_fixture=True)))
    adapter("final_receipts_accepted", 0)
    normalized_path = destination / "RECEIPTS.json"
    normalized = read_json(normalized_path)
    require(len(normalized["scopes"]) == 3 and len(normalized["additional_measured_windows"]) == 1,
            "Core and independent partial-window scopes were mixed")
    _, _, _, proofs = ClosureAudit(package).prerequisites()
    required = {"lif_scheduler", "main_analysis_execution", "main_analysis_process_log", "lif_normalized_cost_receipts",
                "lif_scheduler_cost_original", "lif_analysis_cost_original", "lif_analysis_watcher_cost_original"}
    require(required <= set(proofs), "New prerequisite proofs are incomplete")
    checks = []

    def reject(label, path, update, expected):
        prior = path.read_bytes()
        value = json.loads(prior)
        update(value)
        path.write_text(json.dumps(value))
        try:
            try:
                ClosureAudit(package).prerequisites()
            except ValueError as error:
                require(expected in str(error), "Unexpected targeted gate rejection")
                checks.append(dict(check=label, rejected=True, reason=str(error)))
            else:
                raise RuntimeError("Broken prerequisite accepted: " + label)
        finally:
            path.write_bytes(prior)

    reject("cross-arm initialization mismatch", analysis_path,
           lambda value: value.update(common_initialization_mismatches=[dict(task="synthetic", seed=0)]),
           "cross-arm common-initialization mismatches")
    reject("LIF exit_code wins over unrelated returncode", scheduler_path,
           lambda value: value.update(exit_code=1, returncode=0), "LIF scheduler has not completed successfully")
    reject("altered normalized CPU", normalized_path,
           lambda value: value["scopes"][1].update(cpu_seconds=1.75), "normalized CPU does not equal")
    reject("boolean is not integer exit status", normalized_path,
           lambda value: value["scopes"][1].update(success_value=False), "normalized success binding differs")
    ClosureAudit(package).prerequisites()
    result = dict(schema="hcsn-archive-closure-targeted-gates.v1", status="passed", synthetic_fixture_only=True,
        checks=checks, active_watcher_rejected=True, final_adapter_retry_succeeded=True,
        new_required_proof_keys=sorted(required), independent_window_not_core=True,
        source_sha256={path.name: file_hash(path) for path in source.glob("*.py")}, nested_children=child_receipts,
        real_final_closure_executed=False, real_normalized_receipts_modified=False,
        scope="Only new prerequisite review gates and explicit LIF JSON-pointer cost adapter; no archives, numerical runtime, training or analysis were re-executed")
    write_new(output / "RESULTS.json", result)
    print(json.dumps({key: result[key] for key in ("status", "synthetic_fixture_only", "active_watcher_rejected", "final_adapter_retry_succeeded", "real_final_closure_executed")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
