"""Narrow stdlib contract tests for the explicit post-hoc audit admission."""

import argparse
import copy
import json
from pathlib import Path

from . import archive_closure as closure
from . import final_bundle_plan as planner
from . import lif_cost_receipts as normalizer


PACKAGE = Path(__file__).resolve().parent


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def fixture(output):
    package = output / "fixture/hepta/experiments/hcsn_distributional_v2"
    package.mkdir(parents=True)
    root = package.parents[1]
    for name in ("archive_closure.py", "lif_cost_receipts.py", "final_bundle_plan.py", "measured_support.py"):
        (package / name).write_bytes((PACKAGE / name).read_bytes())
    for name in ("content_analysis.py", "content_supplemental_analysis.py", "scaling_eval.py", "scaling_admission.py"):
        (package / name).write_text("# Synthetic identity fixture; never executed.\n" + name + "\n")
    jobs = [dict(task="fixture" + str(i), model="ordinary", seed=i) for i in range(175)]
    jobs.append(dict(task="fsdd", model="transformer", seed=9202))
    base_relative = str((package / "content_analysis.py").relative_to(root))
    base_sha = closure.file_hash(package / "content_analysis.py")
    parent = dict(jobs=jobs, source_files_sha256={base_relative: base_sha})
    write(package / "CONTENT002_PROTOCOL.json", parent)
    parent_sha = closure.file_hash(package / "CONTENT002_PROTOCOL.json")
    rows = [dict(job=job, valid=True) for job in jobs]
    rows[-1] = dict(job=jobs[-1], valid=False, error="AssertionError: cross entropy summary")
    strict_path = package / "results/content_analysis002/ANALYSIS.json"
    strict = dict(schema="hcsn-distribution-content-analysis.v2", protocol_sha256=parent_sha,
                  analyzer_sha256=base_sha, expected=176, valid=175, invalid=1,
                  common_initialization_mismatches=[], audits=rows)
    write(strict_path, strict)
    strict_execution_path = strict_path.with_name("EXECUTION.json")
    write(strict_execution_path, dict(returncode=0, protocol_sha256=parent_sha, analyzer_sha256=base_sha))
    original = dict(path=str(strict_path.relative_to(root)), sha256=closure.file_hash(strict_path),
                    execution_path=str(strict_execution_path.relative_to(root)),
                    execution_sha256=closure.file_hash(strict_execution_path),
                    expected=176, valid=175, invalid=1, gate_passed=False)
    derived_path = package / "content_supplemental_analysis.py"
    derived = dict(path=str(derived_path.relative_to(root)), sha256=closure.file_hash(derived_path))
    sources = dict(parent["source_files_sha256"], **{derived["path"]: derived["sha256"]})
    registration_directory = package / "results/content_supplement001"
    write(registration_directory / "DERIVATION.diff", dict(synthetic=True))
    write(registration_directory / "AST_COMPARISON.json", dict(schema="hcsn-supplemental-audit-ast-evidence.v1",
        base=dict(path=base_relative, sha256=base_sha), derived=derived, audit_run_unchanged=True,
        exact_sign_flip_unchanged=True, holm_unchanged=True, entire_core_mechanism_screen_statement_block_unchanged=True))
    write(registration_directory / "PRODUCER_CHECKS.json", dict(schema="hcsn-exact-producer-contract-checks.v1",
        passed=True, source=derived))
    write(registration_directory / "PREPARE.py", dict(synthetic=True))
    diagnostic_path = package / "results/content_ce_diagnostic002/RESULT.json"
    write(diagnostic_path, dict(synthetic=True))
    evidence = lambda path: dict(path=str(path.relative_to(root)), sha256=closure.file_hash(path))
    protocol = dict(schema="hcsn-post-hoc-content-audit-protocol.v1", study_id="content_supplement001", expected_runs=176,
        post_hoc=True, statistical_gates_changed=False, base_analyzer_sha256=base_sha, derived_source=derived,
        parent_protocol_sha256=parent_sha, source_files_sha256=sources, original_strict_audit=original,
        derivation_diff=evidence(registration_directory / "DERIVATION.diff"),
        ast_evidence=evidence(registration_directory / "AST_COMPARISON.json"),
        producer_checks=evidence(registration_directory / "PRODUCER_CHECKS.json"),
        preparer_source=evidence(registration_directory / "PREPARE.py"), diagnostic=evidence(diagnostic_path))
    write(package / "CONTENT_SUPPLEMENT001_PROTOCOL.json", protocol)
    write(registration_directory / "REGISTRATION.json", dict(schema="hcsn-post-hoc-content-audit-registration.v1",
        status="registered_not_run", post_hoc=True, original_strict_gate_passed=False,
        protocol=evidence(package / "CONTENT_SUPPLEMENT001_PROTOCOL.json"), derived_source=derived))
    reconciliation = {name: True for name in (
        "all_four_mechanism_records_exactly_equal", "previously_complete_core_records_exactly_equal",
        "previously_complete_content_screens_exactly_equal", "only_previously_missing_fsdd_rows_filled",
        "all_prediction_summaries_producer_exact", "original_strict_ce_failure_remains_explicit")}
    reconciliation["training_selection_prediction_or_scientific_threshold_changes"] = False
    supplement = dict(schema="hcsn-distribution-content-supplemental-analysis.v1", protocol_sha256=parent_sha,
        supplemental_protocol_sha256=closure.file_hash(package / "CONTENT_SUPPLEMENT001_PROTOCOL.json"),
        post_hoc=True, statistical_gates_changed=False, base_analyzer_sha256=base_sha,
        expected=176, valid=176, invalid=0, common_initialization_mismatches=[],
        audits=[dict(job=job, valid=True) for job in jobs], original_strict_audit=original, derived_source=derived,
        supplemental_gate_passed=True, supplemental=dict(expected=176, valid=176, invalid=0, gate_passed=True),
        scientific_comparison_reconciliation=reconciliation)
    write(package / "results/content_analysis_supplement001/ANALYSIS.json", supplement)
    outer = package / "results/content_analysis_supplement001_execution"
    write(outer / "REQUEST.json", dict(command=["fixture"]))
    (outer / "process.log").write_text("Synthetic receipt fixture, no actual research execution.\n")
    write(outer / "EXECUTION.json", dict(schema="hcsn-measured-support-execution.v1", status="completed", returncode=0,
        request_sha256=closure.file_hash(outer / "REQUEST.json"), log_sha256=closure.file_hash(outer / "process.log"),
        source_sha256=closure.file_hash(package / "measured_support.py"), complete_child_cpu_seconds=1.25))
    write(package / "LIF_SUPPLEMENT001_PROTOCOL.json", dict(synthetic=True))
    lif_sha = closure.file_hash(package / "LIF_SUPPLEMENT001_PROTOCOL.json")
    study = package / "results/lif_supplement001"
    write(study / "COMPLETE.json", dict(status="completed", expected=18, completed=18, failures=0, protocol_sha256=lif_sha))
    write(package / "results/lif_analysis001/ANALYSIS.json", dict(status="passed", expected_pairs=18,
        valid_pairs=18, protocol_sha256=lif_sha, parent_protocol_sha256=parent_sha))
    write(study / "SCHEDULER_EXECUTION.json", dict(exit_code=0, complete_child_cpu_seconds=3.0,
        child_user_cpu_seconds=2.5, child_system_cpu_seconds=.5, protocol_sha256=lif_sha,
        outer_supervisor_self_window_cpu_seconds=.01))
    write(study / "ANALYSIS_OUTER_EXECUTION.json", dict(status="completed", exit_code=0,
        complete_child_cpu_seconds=1.0, watcher_self_cpu_seconds=.02))
    binding = dict(schema="hcsn-lif-cost-bindings.v1", scopes=[])
    for key, filename, field, success, value, kind in (
        ("lif_scheduler", "SCHEDULER_EXECUTION.json", "/complete_child_cpu_seconds", "/exit_code", 0, "complete_process_tree_wait4"),
        ("lif_analysis", "ANALYSIS_OUTER_EXECUTION.json", "/complete_child_cpu_seconds", "/exit_code", 0, "complete_process_tree_wait4"),
        ("lif_analysis_watcher", "ANALYSIS_OUTER_EXECUTION.json", "/watcher_self_cpu_seconds", "/status", "completed", "process_self_cpu_through_receipt")):
        binding["scopes"].append(dict(scope_id=key, receipt=str((study / filename).relative_to(root)),
            field=field, success_field=success, success_value=value, measurement_kind=kind, scope="Synthetic fixture only"))
    write(package / "BINDINGS.json", binding)
    return package


def scaling_fixture(package):
    root = package.parents[1]
    cases = []
    for model in ("distribution_free_dual", "two_gates", "transformer"):
        shapes = [(length, 32, 1) for length in (16, 32, 64, 128, 256, 512)]
        shapes += [(64, width, depth) for width, depth in ((32, 2), (32, 4), (64, 1), (64, 2))]
        for length, width, depth in shapes:
            cases.append(dict(case_id=f"{model}_b1_t{length}_w{width}_d{depth}", model=model,
                              batch=1, length=length, width=width, depth=depth))
    preflight = package / "results/scaling_preflight001"
    write(preflight / "EXECUTION.json", dict(synthetic=True))
    write(preflight / "RESULTS.json", dict(synthetic=True))
    source_path = package / "scaling_eval.py"
    sources = {str(source_path.relative_to(root)): closure.file_hash(source_path)}
    old = dict(schema="hcsn-v2-scaling-protocol.v1", study_id="scaling001", expected_cases=30, cases=cases,
        measurement=dict(measured_forward=3, measured_optimizer_step=3, workers=1), randomness=dict(input_seed=743001),
        preflight=dict(path=str(preflight.relative_to(root)), execution_sha256=closure.file_hash(preflight / "EXECUTION.json"),
                       results_sha256=closure.file_hash(preflight / "RESULTS.json")), source_files_sha256=sources)
    write(package / "SCALING001_PROTOCOL.json", old)
    old_sha = closure.file_hash(package / "SCALING001_PROTOCOL.json")
    strict_path = package / "results/content_analysis002/ANALYSIS.json"
    blocked_path = package / "results/scaling001/NOT_EXECUTED.json"
    write(blocked_path, dict(schema="hcsn-v2-scaling-not-executed.v1", study_id="scaling001", status="not_executed",
        protocol_sha256=old_sha, benchmark_source_sha256=closure.file_hash(source_path), started_workers=0,
        strict_gate_passed=False, successor_study="scaling002",
        original_analysis=dict(path=str(strict_path.relative_to(root)), sha256=closure.file_hash(strict_path),
                               expected=176, valid=175, invalid=1)))
    new = copy.deepcopy(old)
    new.update(schema="hcsn-v2-scaling-protocol.v2", study_id="scaling002")
    new_source = package / "scaling_admission.py"
    new["source_files_sha256"][str(new_source.relative_to(root))] = closure.file_hash(new_source)
    admission = closure.verify_main_admission(package)["record"]
    evidence = dict(schema="hcsn-scaling002-main-admission.v1",
                    **{key: admission[key] for key in ("original_strict", "supplemental", "derived_source")})
    new.update(inherited_protocol=dict(path=str((package / "SCALING001_PROTOCOL.json").relative_to(root)), sha256=old_sha),
        frozen_benchmark=dict(path=str(source_path.relative_to(root)), sha256=closure.file_hash(source_path),
                              functions=["benchmark", "summary_report"], implementation_modified=False),
        timing_parameter_seed_or_repetition_change=False, new_preflight=False,
        original_not_executed=dict(path=str(blocked_path.relative_to(root)), sha256=closure.file_hash(blocked_path)),
        admission_evidence=evidence)
    write(package / "SCALING002_PROTOCOL.json", new)
    protocol_sha = closure.file_hash(package / "SCALING002_PROTOCOL.json")
    study = package / "results/scaling002"
    rows = []
    for index, case in enumerate(cases):
        directory = study / "cases" / case["case_id"]
        rc = int(index == 29)
        identity = dict(case_id=case["case_id"], protocol_sha256=protocol_sha, source_files_sha256=new["source_files_sha256"])
        receipt = dict(identity, returncode=rc)
        write(directory / "IDENTITY.json", identity)
        write(directory / "EXECUTION.json", receipt)
        write(directory / ("FAILURE.json" if rc else "RESULT.json"), dict(synthetic=True))
        rows.append(dict(case, **receipt, receipt_path=str((directory / "EXECUTION.json").relative_to(root))))
    completion = dict(schema="hcsn-v2-scaling-complete.v1", status="completed", expected_cases=30, completed_cases=30,
        successful_cases=29, failed_cases=1, all_cases_successful=False,
        protocol_sha256=protocol_sha, source_files_sha256=new["source_files_sha256"], records=rows,
        study_id="scaling002", original_strict_gate_passed=False, admission_evidence=evidence,
        frozen_benchmark=new["frozen_benchmark"])
    write(study / "COMPLETE.json", completion)
    write(study / "SUITE_EXECUTION.json", dict(returncode=0, protocol_sha256=protocol_sha,
        source_files_sha256=new["source_files_sha256"], complete_receipt_sha256=closure.file_hash(study / "COMPLETE.json"),
        complete_child_cpu_seconds=1.0))
    normalization_execution = package / "results/lif_cost_normalization001/EXECUTION.json"
    write(normalization_execution, dict(synthetic=True, returncode=0))
    normalize_receipts = package / "results/lif_cost_receipts001/RECEIPTS.json"
    write(study / "RUN_AUTHORIZATION.json", dict(study_id="scaling002", protocol_sha256=protocol_sha,
        source_files_sha256=new["source_files_sha256"], original_strict_gate_passed=False,
        benchmark_implementation_modified=False, admission=dict(main_admission=evidence,
            normalized_lif=dict(path=str(normalize_receipts.relative_to(root)), sha256=closure.file_hash(normalize_receipts)),
            normalization_execution=dict(path=str(normalization_execution.relative_to(root)), sha256=closure.file_hash(normalization_execution)))))
    return study


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    package = fixture(output)
    records = []

    def reject(name, relative, mutate, operation):
        path = package / relative
        original = path.read_bytes()
        value = json.loads(original)
        mutate(value)
        write(path, value)
        try:
            operation()
        except (ValueError, KeyError, FileNotFoundError) as error:
            records.append(dict(case=name, status="passed", rejection=str(error)))
        else:
            raise AssertionError("Invalid admission accepted: " + name)
        finally:
            path.write_bytes(original)

    admission = closure.verify_main_admission(package)
    assert admission["record"]["original_strict"]["gate_passed"] is False
    assert admission["record"]["supplemental"]["valid"] == 176
    records.append(dict(case="explicit_failed_strict_and_complete_supplement", status="passed"))
    call = lambda: closure.verify_main_admission(package)
    strict = "results/content_analysis002/ANALYSIS.json"
    supplemental = "results/content_analysis_supplement001/ANALYSIS.json"
    reject("strict_pass_cannot_be_rewritten", strict, lambda d: d.update(valid=176, invalid=0), call)
    reject("supplement_must_be_post_hoc", supplemental, lambda d: d.update(post_hoc=False), call)
    reject("supplement_must_cover_all_jobs", supplemental, lambda d: d["audits"].pop(), call)
    reject("original_failure_binding_must_stay_false", supplemental,
           lambda d: d["original_strict_audit"].update(gate_passed=True), call)
    reject("scientific_thresholds_must_not_change", supplemental,
           lambda d: d["scientific_comparison_reconciliation"].update(training_selection_prediction_or_scientific_threshold_changes=True), call)
    reject("all_original_scientific_records_preserved", supplemental,
           lambda d: d["scientific_comparison_reconciliation"].update(all_four_mechanism_records_exactly_equal=False), call)
    reject("source_binding_must_match", supplemental, lambda d: d["derived_source"].update(sha256="0"*64), call)
    reject("supplement_outer_must_be_final", "results/content_analysis_supplement001_execution/EXECUTION.json",
           lambda d: d.update(status="running"), call)
    previous_package, previous_root = normalizer.PACKAGE, normalizer.ROOT
    try:
        normalizer.PACKAGE, normalizer.ROOT = package, package.parents[1]
        normalized = normalizer.normalize(package / "BINDINGS.json", package / "results/lif_cost_receipts001")
        assert normalized["main_admission"] == admission["record"]
        assert len(normalized["scopes"]) == 3 and normalized["scopes"][0]["cpu_seconds"] == 3.0
        records.append(dict(case="normalizer_binds_both_audits_and_preserves_three_cost_scopes", status="passed"))
    finally:
        normalizer.PACKAGE, normalizer.ROOT = previous_package, previous_root
    scaling_fixture(package)
    auditor = closure.ClosureAudit.__new__(closure.ClosureAudit)
    auditor.package, auditor.root = package, package.parents[1]
    scale = auditor.audit_scaling()
    assert len(scale["rows"]) == 30 and scale["successful"] == 29 and scale["failed"] == 1
    records.append(dict(case="new_scaling_identity_retains_recorded_negative_case", status="passed"))
    reject("new_scaling_measurement_must_equal_original", "SCALING002_PROTOCOL.json",
           lambda d: d["measurement"].update(measured_forward=4), auditor.audit_scaling)
    reject("original_scaling_must_remain_unexecuted", "results/scaling001/NOT_EXECUTED.json",
           lambda d: d.update(started_workers=1), auditor.audit_scaling)
    reject("original_scaling_strict_gate_cannot_be_relabeled", "results/scaling001/NOT_EXECUTED.json",
           lambda d: d.update(strict_gate_passed=True), auditor.audit_scaling)
    reject("new_scaling_must_keep_original_sources", "SCALING002_PROTOCOL.json",
           lambda d: d["source_files_sha256"].pop(next(key for key in d["source_files_sha256"] if key.endswith("/scaling_eval.py"))), auditor.audit_scaling)
    for path in ("CONTENT_SUPPLEMENT001_PROTOCOL.json", "content_supplemental_analysis.py",
                 "results/content_supplement001/REGISTRATION.json",
                 "results/content_supplement_preflight001/EXECUTION.json",
                 "results/content_analysis_supplement001_execution/EXECUTION.json"):
        assert planner.group(path) == "content002_metadata" and planner.exclusion(path) is None
    for path in ("results/content_ce_diagnostic001_measurement/EXECUTION.json",
                 "results/content_ce_diagnostic002/RESULT.json", "results/admission_consumer004/BEFORE.json"):
        assert planner.group(path) == "v2_auxiliary_evidence" and planner.exclusion(path) is None
    records.append(dict(case="new_evidence_partition_keeps_failed_diagnosis_and_admission_history", status="passed"))
    actual = closure.verify_main_admission(PACKAGE)
    write(output / "ACTUAL_MAIN_ADMISSION.json", actual)
    records.append(dict(case="actual_completed_original_and_supplemental_metadata_verified", status="passed"))
    source = output / "source"
    source.mkdir()
    for name in ("archive_closure.py", "lif_cost_receipts.py", "final_bundle_plan.py", "admission_consumer_tests.py"):
        (source / name).write_bytes((PACKAGE / name).read_bytes())
    result = dict(schema="hcsn-admission-consumer-tests.v1", status="passed", tests=len(records), records=records,
        source_sha256={path.name: closure.file_hash(path) for path in source.iterdir()},
        scope="Synthetic stdlib metadata and cost-pointer contracts only; no Torch, training, original-result modification, benchmark execution or archive re-pack")
    write(output / "RESULTS.json", result)
    print(json.dumps(dict(status=result["status"], tests=result["tests"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
