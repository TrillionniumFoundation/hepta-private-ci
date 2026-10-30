"""SCALING002 admission and orchestration, reusing the frozen SCALING001 timers.

The original strict audit remains 175 valid / 1 invalid and SCALING001 is never
run. This separate protocol admits the unchanged random-weight diagnostic only
after an independent producer-exact 176-run supplement and final LIF receipts.
"""

import argparse
import copy
import math
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import traceback

from . import scaling_eval as frozen


PACKAGE, ROOT = frozen.PACKAGE, frozen.ROOT
sha, read, write, relative = frozen.sha, frozen.read, frozen.write, frozen.relative
ORIGINAL_SOURCE_SHA = "be79c27898c56e557b3b58ee9858d116dbfd61998129a5f1e2ab84f0115db6fa"
ORIGINAL_PROTOCOL_SHA = "287c56ae904ec5c4cabe6e5ee309d6a22b8f4648e9b1890ed650af2b0fbc1fa3"
INHERITED = ("cases", "expected_cases", "randomness", "measurement", "preflight", "limitations",
             "content_protocols_unchanged", "content_data_or_checkpoints_used")
RECONCILIATION_KEYS = (
    "all_four_mechanism_records_exactly_equal", "all_prediction_summaries_producer_exact",
    "only_previously_missing_fsdd_rows_filled", "original_strict_ce_failure_remains_explicit",
    "previously_complete_content_screens_exactly_equal", "previously_complete_core_records_exactly_equal")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def location(path):
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate if candidate.parts[0] == "experiments" else PACKAGE / candidate
    candidate = candidate.resolve()
    require(candidate.is_relative_to(PACKAGE), "Admission evidence must belong to this v2 package")
    return candidate


def binding(path):
    path = location(path)
    return dict(path=relative(path), sha256=sha(path))


def pointer(data, field):
    for part in field.strip("/").split("/"):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def original_contract():
    path = PACKAGE / "SCALING001_PROTOCOL.json"
    require(sha(PACKAGE / "scaling_eval.py") == ORIGINAL_SOURCE_SHA, "Frozen benchmark implementation changed")
    require(sha(path) == ORIGINAL_PROTOCOL_SHA, "Original 30-point protocol changed")
    original = read(path)
    frozen.verify(original["source_files_sha256"])
    require(frozen.source_mapping() == original["source_files_sha256"], "Original executable dependency set changed")
    preflight = location(original["preflight"]["path"])
    require(sha(preflight / "EXECUTION.json") == original["preflight"]["execution_sha256"] and
            sha(preflight / "RESULTS.json") == original["preflight"]["results_sha256"],
            "Original preflight evidence changed")
    return original


def main_evidence():
    original_path = PACKAGE / "results/content_analysis002/ANALYSIS.json"
    original_execution = PACKAGE / "results/content_analysis002/EXECUTION.json"
    supplemental_path = PACKAGE / "results/content_analysis_supplement001/ANALYSIS.json"
    supplemental_protocol = PACKAGE / "CONTENT_SUPPLEMENT001_PROTOCOL.json"
    supplemental_execution = PACKAGE / "results/content_analysis_supplement001_execution/EXECUTION.json"
    original, supplement = read(original_path), read(supplemental_path)
    main_protocol_sha = sha(PACKAGE / "CONTENT002_PROTOCOL.json")
    require(original["schema"] == "hcsn-distribution-content-analysis.v2" and
            (original["expected"], original["valid"], original["invalid"]) == (176, 175, 1),
            "Original strict 175/1 result must be retained explicitly")
    invalid = [{key: row.get(key) for key in ("job", "valid", "error")}
               for row in original["audits"] if not row["valid"]]
    require(invalid == [dict(job=dict(model="transformer", seed=9202, task="fsdd"), valid=False,
                            error="AssertionError: cross entropy summary")], "Unexpected original strict failure")
    require(original["protocol_sha256"] == main_protocol_sha and
            original["analyzer_sha256"] == sha(PACKAGE / "content_analysis.py"), "Original audit identity changed")
    require(supplement["schema"] == "hcsn-distribution-content-supplemental-analysis.v1" and
            (supplement["expected"], supplement["valid"], supplement["invalid"]) == (176, 176, 0) and
            not supplement["common_initialization_mismatches"], "Supplement must independently audit all 176 runs")
    require(supplement["post_hoc"] is True and supplement["statistical_gates_changed"] is False,
            "Supplement must disclose its post-hoc integrity-only status")
    reconciliation = supplement["scientific_comparison_reconciliation"]
    require(supplement["supplemental_gate_passed"] is True and
            all(reconciliation.get(key) is True for key in RECONCILIATION_KEYS) and
            reconciliation["training_selection_prediction_or_scientific_threshold_changes"] is False,
            "Supplement must retain every existing scientific comparison and threshold")
    require(supplement["protocol_sha256"] == main_protocol_sha and
            supplement["supplemental_protocol_sha256"] == sha(supplemental_protocol) and
            supplement["base_analyzer_sha256"] == original["analyzer_sha256"], "Supplement protocol/base identity mismatch")
    derived = supplement["derived_source"]
    require(location(derived["path"]) == PACKAGE / "content_supplemental_analysis.py" and
            sha(location(derived["path"])) == derived["sha256"], "Supplement executable source changed")
    supplemental_registration = read(supplemental_protocol)
    require(supplemental_registration["schema"] == "hcsn-post-hoc-content-audit-protocol.v1" and
            supplemental_registration["post_hoc"] is True and
            supplemental_registration["statistical_gates_changed"] is False and
            supplemental_registration["derived_source"] == derived and
            supplemental_registration["parent_protocol_sha256"] == main_protocol_sha,
            "Supplement registration contract differs")
    prior = supplement["original_strict_audit"]
    require(location(prior["path"]) == original_path and prior["sha256"] == sha(original_path) and
            location(prior["execution_path"]) == original_execution and prior["execution_sha256"] == sha(original_execution) and
            (prior["expected"], prior["valid"], prior["invalid"]) == (176, 175, 1) and prior["gate_passed"] is False,
            "Supplement must preserve the exact original failed strict gate")
    require(read(original_execution)["returncode"] == 0, "Original audit process did not complete")
    outer = read(supplemental_execution)
    require(outer["returncode"] == 0 and outer["status"] == "completed", "Supplement outer process has not exited successfully")
    return dict(schema="hcsn-scaling002-main-admission.v1", original_strict=prior,
        supplemental=dict(**binding(supplemental_path), protocol_path=relative(supplemental_protocol),
            protocol_sha256=sha(supplemental_protocol), expected=176, valid=176, invalid=0,
            post_hoc=True, statistical_gates_changed=False), derived_source=derived,
        supplemental_execution=binding(supplemental_execution), original_invalid_metadata=invalid,
        scientific_comparisons_preserved=True,
        interpretation="Original strict gate failed175/1 and is not repaired; a separate post-hoc producer-exact integrity audit admits only this unchanged random-weight CPU diagnostic")


def run_gates():
    main = main_evidence()
    checks = [
        ("results/content002/COMPLETE.json", dict(status="completed", expected=176, completed=176, failures=0)),
        ("results/content002/SCHEDULER_EXECUTION.json", dict(returncode=0)),
        ("results/lif_supplement001/COMPLETE.json", dict(status="completed", expected=18, completed=18, failures=0)),
        ("results/lif_supplement001/SCHEDULER_EXECUTION.json", dict(exit_code=0)),
        ("results/lif_analysis001/ANALYSIS.json", dict(status="passed", expected_pairs=18, valid_pairs=18)),
    ]
    gates = []
    for path, expected in checks:
        data = read(PACKAGE / path)
        require({key: data.get(key) for key in expected} == expected, "Unfinished prerequisite: " + path)
        gates.append(dict(**binding(path), required_metadata=expected))
    normalizer_path = PACKAGE / "results/lif_cost_receipts001/RECEIPTS.json"
    normalized = read(normalizer_path)
    require(normalized["schema"] == "hcsn-lif-cost-receipts.v1" and normalized["status"] == "completed",
            "Final LIF normalization is required")
    admitted = normalized["main_admission"]
    require(admitted["schema"] == "hcsn-main-analysis-admission.v1" and
            admitted["basis"] == "independent_post_hoc_producer_exact_integrity_audit" and
            admitted["scientific_comparisons_preserved"] is True and
            admitted["derived_source"] == main["derived_source"] and
            admitted["original_strict"] == main["original_strict"], "LIF normalizer did not preserve original strict failure")
    for key in ("sha256", "protocol_sha256", "expected", "valid", "invalid", "post_hoc", "statistical_gates_changed"):
        require(admitted["supplemental"][key] == main["supplemental"][key], "Normalizer supplementary admission differs")
    require(location(admitted["supplemental"]["path"]) == location(main["supplemental"]["path"]) and
            location(admitted["supplemental"]["protocol_path"]) == location(main["supplemental"]["protocol_path"]),
            "Normalizer supplementary paths differ")
    require({row["scope_id"] for row in normalized["scopes"]} == {"lif_scheduler", "lif_analysis", "lif_analysis_watcher"}
            and len(normalized["scopes"]) == 3, "LIF final scope set differs")
    for row in normalized["scopes"]:
        path = location(row["receipt"])
        require(sha(path) == row["receipt_sha256"], "Original LIF receipt changed")
        raw = read(path)
        success = pointer(raw, row["success_field"])
        require(type(success) is type(row["success_value"]) and success == row["success_value"], "LIF terminal state changed")
        cpu = pointer(raw, row["field"])
        require(type(cpu) in (int, float) and math.isfinite(cpu) and cpu >= 0 and cpu == row["cpu_seconds"],
                "LIF original CPU field does not match its normalization")
    normalization_execution = "results/lif_cost_normalization001/EXECUTION.json"
    require(read(PACKAGE / normalization_execution)["returncode"] == 0, "Normalization outer process has not exited successfully")
    return dict(main_admission=main, gates=gates, normalized_lif=binding(normalizer_path),
                normalization_execution=binding(normalization_execution))


def register(protocol_path, output):
    require(not protocol_path.exists() and not output.exists(), "SCALING002 requires new protocol/output paths")
    original, evidence = original_contract(), main_evidence()
    run_gates()
    old_study = PACKAGE / "results/scaling001"
    require(not any((old_study / leaf).exists() for leaf in ("cases", "RUN_AUTHORIZATION.json", "SUITE_EXECUTION.json", "COMPLETE.json")),
            "SCALING001 must have zero started formal workers")
    marker = old_study / "NOT_EXECUTED.json"
    marker_record = dict(schema="hcsn-v2-scaling-not-executed.v1", status="not_executed", study_id="scaling001",
        protocol_sha256=ORIGINAL_PROTOCOL_SHA, benchmark_source_sha256=ORIGINAL_SOURCE_SHA, started_workers=0,
        original_analysis=dict(**binding("results/content_analysis002/ANALYSIS.json"), expected=176, valid=175, invalid=1),
        strict_gate_passed=False, successor_study="scaling002", reason="Original strict analysis175/1 fails the unchanged SCALING001 admission gate; no formal001 timing was started")
    if marker.exists():
        require(read(marker) == marker_record, "Existing SCALING001 non-execution evidence differs")
    else:
        write(marker, marker_record)
    sources = dict(original["source_files_sha256"])
    sources[relative(__file__)] = sha(__file__)
    protocol = {key: copy.deepcopy(original[key]) for key in INHERITED}
    protocol.update(schema="hcsn-v2-scaling-protocol.v2", study_id="scaling002", registered_utc=frozen.utc(),
        source_files_sha256=sources, inherited_protocol=dict(path=relative(PACKAGE / "SCALING001_PROTOCOL.json"), sha256=ORIGINAL_PROTOCOL_SHA),
        frozen_benchmark=dict(path=relative(PACKAGE / "scaling_eval.py"), sha256=ORIGINAL_SOURCE_SHA,
            functions=["benchmark", "summary_report"], implementation_modified=False),
        original_not_executed=binding(marker), admission_evidence=evidence,
        new_admission="Exact preserved strict175/1 plus independent post-hoc producer-exact176 audit, completed LIF study/analysis and final original-pointer cost normalization",
        timing_parameter_seed_or_repetition_change=False, new_preflight=False)
    frozen.verify(sources)
    write(protocol_path, protocol)
    output.mkdir(parents=True)
    for path in sources:
        target = output / "source" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    shutil.copyfile(protocol_path, output / "source" / protocol_path.name)
    write(output / "REGISTRATION.json", dict(schema="hcsn-v2-scaling-registration.v2", status="registered_not_run",
        protocol_path=relative(protocol_path), protocol_sha256=sha(protocol_path), study_id="scaling002", expected_cases=30,
        source_files_sha256=sources, inherited_protocol=protocol["inherited_protocol"], original_not_executed=protocol["original_not_executed"],
        admission_evidence=evidence, self_cpu_seconds_through_registration=time.process_time()))
    print(f"registered scaling002 {sha(protocol_path)}", flush=True)


def registered(protocol_path, output):
    original = original_contract()
    protocol, registration = read(protocol_path), read(output / "REGISTRATION.json")
    require(protocol["schema"] == "hcsn-v2-scaling-protocol.v2" and protocol["study_id"] == "scaling002",
            "Expected the independent SCALING002 protocol")
    require(sha(protocol_path) == registration["protocol_sha256"] and
            protocol["source_files_sha256"] == registration["source_files_sha256"], "SCALING002 registration mismatch")
    require(all(protocol[key] == original[key] for key in INHERITED), "Original timing/configuration contract changed")
    frozen.verify(protocol["source_files_sha256"])
    marker = location(protocol["original_not_executed"]["path"])
    require(sha(marker) == protocol["original_not_executed"]["sha256"] and read(marker)["started_workers"] == 0,
            "Original unexecuted-study marker changed")
    require(main_evidence() == protocol["admission_evidence"], "Independent main admission evidence changed")
    return protocol


def launch(arguments, directory, wall_limit=None):
    command = [sys.executable, "-m", "experiments.hcsn_distributional_v2.scaling_admission", *arguments]
    environment = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[key] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started, timed_out = time.monotonic(), False
    with (directory / "process.log").open("xb") as log:
        child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            if wall_limit is not None and time.monotonic() - started > wall_limit and not timed_out:
                child.kill()
                timed_out = True
            time.sleep(.05)
    return dict(command=command, returncode=child.returncode, complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
        child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
        wall_seconds=time.monotonic() - started, peak_rss_kib_linux=usage.ru_maxrss,
        wall_limit_reached=timed_out, signal=(-child.returncode if child.returncode < 0 else None),
        process_log_sha256=sha(directory / "process.log"),
        measurement="Linux wait4 complete child including imports, unchanged benchmark and exit; body clocks are nested")


def worker(protocol_path, output, case_id):
    protocol = registered(protocol_path, output)
    authorization = read(output / "RUN_AUTHORIZATION.json")
    require(authorization["protocol_sha256"] == sha(protocol_path) and authorization["admission"] == run_gates(),
            "SCALING002 admission changed after authorization")
    case = next(row for row in protocol["cases"] if row["case_id"] == case_id)
    directory = output / "cases" / case_id
    limit = protocol["measurement"]["worker_cpu_limit_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 5))
    try:
        frozen.benchmark(directory, case, protocol["source_files_sha256"], sha(protocol_path), repeats=3)
    except BaseException as error:
        write(directory / "FAILURE.json", dict(case_id=case_id, type=type(error).__name__, message=str(error),
            traceback=traceback.format_exc(), protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"],
            partial_measurement_files=sorted(path.name for path in directory.glob("MEASURE_*.json"))))
        raise


def suite(protocol_path, output):
    protocol = registered(protocol_path, output)
    require(read(output / "RUN_AUTHORIZATION.json")["admission"] == run_gates(), "SCALING002 authorization changed")
    records = []
    (output / "cases").mkdir()
    for case in protocol["cases"]:
        frozen.verify(protocol["source_files_sha256"])
        directory = output / "cases" / case["case_id"]
        directory.mkdir()
        execution = launch(["_case", "--protocol", str(protocol_path), "--output", str(output), "--case-id", case["case_id"]],
                           directory, wall_limit=protocol["measurement"]["worker_wall_limit_seconds"])
        execution.update(case_id=case["case_id"], model=case["model"], batch=1, length=case["length"],
            width=case["width"], depth=case["depth"], protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"],
            receipt_path=relative(directory / "EXECUTION.json"))
        require(execution["returncode"] != 0 or (directory / "RESULT.json").exists(), "Successful case lacks its result")
        if execution["returncode"] != 0:
            for leaf in ("FAILURE.json", "IDENTITY.json"):
                path = directory / leaf
                if path.exists():
                    try:
                        read(path)
                    except (ValueError, UnicodeError):
                        path.rename(directory / (leaf + ".incomplete"))
            if not (directory / "FAILURE.json").exists():
                write(directory / "FAILURE.json", dict(case_id=case["case_id"], type="worker_exit_or_resource_limit",
                    returncode=execution["returncode"], wall_limit_reached=execution["wall_limit_reached"], signal=execution["signal"],
                    protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"],
                    partial_measurement_files=sorted(path.name for path in directory.glob("MEASURE_*.json"))))
        if not (directory / "IDENTITY.json").exists():
            write(directory / "IDENTITY.json", dict(schema="hcsn-v2-scaling-case-identity.v1", case_id=case["case_id"],
                status="failed_before_identity", actual_counts=None, constructor=frozen.constructor(case),
                protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"]))
        write(directory / "EXECUTION.json", execution)
        records.append(execution)
        print(f"scaling002 {len(records)}/30 {case['case_id']} returncode={execution['returncode']}", flush=True)
    frozen.verify(protocol["source_files_sha256"])
    frozen.summary_report(output, protocol, records)
    failed = sum(row["returncode"] != 0 for row in records)
    write(output / "COMPLETE.json", dict(schema="hcsn-v2-scaling-complete.v1", status="completed", study_id="scaling002",
        expected_cases=30, completed_cases=len(records), successful_cases=len(records)-failed, failed_cases=failed,
        all_cases_successful=failed == 0, records=records, protocol_sha256=sha(protocol_path), source_files_sha256=protocol["source_files_sha256"],
        complete_worker_cpu_seconds=math.fsum(row["complete_child_cpu_seconds"] for row in records),
        coordinator_self_cpu_seconds_through_cutoff=time.process_time(), summary_sha256=sha(output / "SUMMARY.json"),
        report_sha256=sha(output / "REPORT.md"), completed_utc=frozen.utc(), original_strict_gate_passed=False,
        admission_evidence=protocol["admission_evidence"], frozen_benchmark=protocol["frozen_benchmark"],
        scope="30 unchanged random-weight diagnostic cases under new explicit admission; original strict audit and unexecuted001 remain unchanged. Workers are nested in suite wait4."))


def run(protocol_path, output):
    protocol = registered(protocol_path, output)
    admission = run_gates()
    write(output / "RUN_AUTHORIZATION.json", dict(study_id="scaling002", protocol_sha256=sha(protocol_path),
        source_files_sha256=protocol["source_files_sha256"], admission=admission, original_strict_gate_passed=False,
        started_utc=frozen.utc(), benchmark_implementation_modified=False))
    execution = launch(["_suite", "--protocol", str(protocol_path), "--output", str(output)], output)
    execution.update(schema="hcsn-v2-scaling-suite-execution.v1", study_id="scaling002", protocol_sha256=sha(protocol_path),
        source_files_sha256=protocol["source_files_sha256"],
        complete_receipt_sha256=sha(output / "COMPLETE.json") if (output / "COMPLETE.json").exists() else None,
        supervisor_self_cpu_seconds_through_cutoff=time.process_time(),
        accounting="Whole suite child includes coordinator, workers, unchanged benchmark and report; only this outer supervisor self CPU is separate")
    write(output / "SUITE_EXECUTION.json", execution)
    if execution["returncode"]:
        raise SystemExit(execution["returncode"])


def main():
    require(__debug__, "SCALING002 requires normal Python execution, without -O")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "run", "_suite", "_case"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "SCALING002_PROTOCOL.json")
    parser.add_argument("--output", type=Path, default=PACKAGE / "results/scaling002")
    parser.add_argument("--case-id")
    args = parser.parse_args()
    protocol, output = args.protocol.resolve(), args.output.resolve()
    if args.action == "register":
        register(protocol, output)
    elif args.action == "run":
        run(protocol, output)
    elif args.action == "_suite":
        suite(protocol, output)
    else:
        worker(protocol, output, args.case_id)


if __name__ == "__main__":
    main()
