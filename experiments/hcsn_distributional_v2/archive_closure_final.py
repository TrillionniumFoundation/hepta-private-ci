"""Final archive consumer preserving the original failed scaling summary.

The previously normalized archive_closure.py remains byte-identical. This
subclass retains all of its main, LIF, bundle and source checks, and replaces
only the scaling completion contract with an explicitly independent summary
repair. Original worker values and the failed suite are never overwritten.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time
import traceback

from . import archive_closure as base
from .archive_closure import PACKAGE, file_hash, read_json, require, safe_relative, verify_main_admission, write_new

BASE_SOURCE_SHA256 = "a73cdcadf0164a83c1355cce17bec9e38e0991e9155b9a4c52c243cb8e4d0209"


def verify_original_failed_suite(suite, protocol_sha, sources):
    require(type(suite["returncode"]) is int and suite["returncode"] == 1
            and suite["protocol_sha256"] == protocol_sha and suite["source_files_sha256"] == sources
            and suite["complete_receipt_sha256"] is None,
            "Original scaling suite failure must remain explicit and unchanged")


def validate_summary_ratios(summary):
    rows = summary["rows"]
    indexed = {(row["model"], row["length"]): row for row in rows if row["panel"] == "length"}
    require(len(indexed) == 18, "Summary length panel must retain all 18 original rows")
    changes = summary["measured_fixed_width_depth_changes"]
    require(len(changes) == 18 and {(row["model"], row["length"]) for row in changes} == set(indexed),
            "Summary ratios omit or duplicate a registered length case")
    for change in changes:
        key = (change["model"], change["length"])
        row, anchor = indexed[key], indexed[(change["model"], 16)]
        require(change["length_ratio_to_16"] == change["length"] / 16, "Length ratio changed")
        undefined = set()
        for operation in ("forward", "optimizer"):
            for clock in ("cpu", "wall"):
                field = f"{operation}_{clock}_median"
                ratio = f"{operation}_{clock}_ratio_to_16"
                numerator, denominator = row[field], anchor[field]
                require(type(numerator) in (int, float) and type(denominator) in (int, float)
                        and math.isfinite(numerator) and math.isfinite(denominator)
                        and min(numerator, denominator) >= 0, "Summary contains an invalid original timing")
                if denominator == 0:
                    require(change[ratio] is None, "A zero denominator must remain an undefined null ratio")
                    undefined.add(ratio)
                    require(isinstance(change["undefined_ratio_reasons"].get(ratio), str)
                            and bool(change["undefined_ratio_reasons"][ratio]), "Undefined ratio lacks its reason")
                else:
                    require(type(change[ratio]) in (int, float) and math.isfinite(change[ratio])
                            and change[ratio] == numerator / denominator, "Ratio differs from the original measured values")
        require(set(change["undefined_ratio_reasons"]) == undefined, "Undefined-ratio reasons do not match zero denominators")


class ClosureAudit(base.ClosureAudit):
    def __init__(self, package=PACKAGE):
        super().__init__(package)
        require(file_hash(base.__file__) == BASE_SOURCE_SHA256, "Previously normalized base auditor changed")
        self.source_hashes["archive_closure_final.py"] = file_hash(__file__)

    def audit_scaling(self):
        old_protocol_path = self.package / "SCALING001_PROTOCOL.json"
        old_protocol = read_json(old_protocol_path)
        old_protocol_sha = file_hash(old_protocol_path)
        protocol_path = self.package / "SCALING002_PROTOCOL.json"
        protocol = read_json(protocol_path)
        protocol_sha = file_hash(protocol_path)
        require(old_protocol["schema"] == "hcsn-v2-scaling-protocol.v1"
                and old_protocol["study_id"] == "scaling001"
                and protocol["schema"] == "hcsn-v2-scaling-protocol.v2" and protocol["study_id"] == "scaling002",
                "Scaling admission must preserve the original identity and use a separate 002 protocol")
        require(protocol["inherited_protocol"] == dict(path=str(old_protocol_path.relative_to(self.root)), sha256=old_protocol_sha)
                and protocol["frozen_benchmark"] == dict(path=str((self.package / "scaling_eval.py").relative_to(self.root)),
                    sha256=file_hash(self.package / "scaling_eval.py"), functions=["benchmark", "summary_report"], implementation_modified=False)
                and protocol["timing_parameter_seed_or_repetition_change"] is False and protocol["new_preflight"] is False,
                "Scaling002 changed the frozen benchmark or obscured its inherited identity")
        for field in ("cases", "measurement", "randomness", "preflight", "expected_cases"):
            require(protocol[field] == old_protocol[field], "Scaling002 changed the registered diagnostic design: " + field)
        require(all(protocol["source_files_sha256"].get(path) == digest
                    for path, digest in old_protocol["source_files_sha256"].items()),
                "Scaling002 does not preserve every original registered source")
        preflight_relative = old_protocol["preflight"]["path"]
        safe_relative(preflight_relative)
        preflight_directory = self.root / preflight_relative
        require(preflight_directory.resolve().is_relative_to(self.package)
                and file_hash(preflight_directory / "EXECUTION.json") == old_protocol["preflight"]["execution_sha256"]
                and file_hash(preflight_directory / "RESULTS.json") == old_protocol["preflight"]["results_sha256"],
                "Original scaling001 preflight evidence changed")
        old_study = self.package / "results/scaling001"
        blocked_path = old_study / "NOT_EXECUTED.json"
        blocked = read_json(blocked_path)
        require(blocked["schema"] == "hcsn-v2-scaling-not-executed.v1" and blocked["study_id"] == "scaling001"
                and blocked["status"] == "not_executed" and blocked["protocol_sha256"] == old_protocol_sha
                and blocked["benchmark_source_sha256"] == file_hash(self.package / "scaling_eval.py")
                and type(blocked["started_workers"]) is int and blocked["started_workers"] == 0
                and blocked["strict_gate_passed"] is False and blocked["successor_study"] == "scaling002",
                "Scaling001 must retain its explicit unexecuted failed-strict-gate evidence")
        strict_path = self.package / "results/content_analysis002/ANALYSIS.json"
        require(blocked["original_analysis"] == dict(path=str(strict_path.relative_to(self.root)), sha256=file_hash(strict_path),
                                                    expected=176, valid=175, invalid=1)
                and protocol["original_not_executed"] == dict(path=str(blocked_path.relative_to(self.root)), sha256=file_hash(blocked_path)),
                "Scaling001 block or successor protocol is bound to another strict analysis")
        admission = getattr(self, "main_analysis_admission", None) or verify_main_admission(self.package)["record"]
        declared_admission = protocol["admission_evidence"]
        require(declared_admission["schema"] == "hcsn-scaling002-main-admission.v1"
                and all(declared_admission[key] == admission[key] for key in ("original_strict", "supplemental", "derived_source")),
                "Scaling002 admission differs from the completed original-plus-supplemental audit")
        require(not (old_study / "COMPLETE.json").exists() and not (old_study / "SUITE_EXECUTION.json").exists()
                and not (old_study / "cases").exists(), "Original blocked scaling001 acquired executed case evidence")
        study = self.package / "results/scaling002"
        repair_directory = self.package / "results/scaling002_summary_repair001"
        completion_path = repair_directory / "COMPLETE.json"
        completion = read_json(completion_path)
        source_map = protocol["source_files_sha256"]
        for relative, expected in source_map.items():
            safe_relative(relative)
            source = self.root / relative
            require(source.resolve().is_relative_to(self.root) and not source.is_symlink()
                    and file_hash(source) == expected, "Registered scaling source changed: " + relative)
        cases = {}
        for case in protocol["cases"]:
            case_id = f"{case['model']}_b{case['batch']}_t{case['length']}_w{case['width']}_d{case['depth']}"
            require(case["case_id"] == case_id and case_id not in cases, "Wrong or duplicate scaling case identity")
            cases[case_id] = case
        expected_grid = {(model, 1, length, 32, 1)
                         for model in ("distribution_free_dual", "two_gates", "transformer")
                         for length in (16, 32, 64, 128, 256, 512)}
        expected_grid |= {(model, 1, 64, width, depth)
                          for model in ("distribution_free_dual", "two_gates", "transformer")
                          for width, depth in ((32, 2), (32, 4), (64, 1), (64, 2))}
        observed_grid = {(case["model"], case["batch"], case["length"], case["width"], case["depth"])
                         for case in cases.values()}
        require(len(cases) == len(protocol["cases"]) == 30 and observed_grid == expected_grid,
                "Scaling protocol differs from the registered 30-configuration diagnostic grid")
        require(completion["schema"] == "hcsn-v2-scaling-summary-repair-complete.v1" and completion["status"] == "completed"
                and completion["expected_cases"] == completion["completed_cases"] == 30
                and completion["protocol_sha256"] == protocol_sha and completion["source_files_sha256"] == source_map
                and completion["study_id"] == "scaling002" and completion["original_strict_gate_passed"] is False
                and completion["admission_evidence"] == declared_admission
                and completion["frozen_benchmark"] == protocol["frozen_benchmark"],
                "Scaling suite has not attempted and recorded all 30 cases")
        rows = {}
        for row in completion["records"]:
            case_id = row["case_id"]
            require(case_id in cases and case_id not in rows, "Unknown or duplicate scaling case receipt")
            case = cases[case_id]
            require(all(row[key] == case[key] for key in ("model", "batch", "length", "width", "depth")),
                    "Scaling completion row has different case coordinates")
            directory = study / "cases" / case_id
            expected_receipt = directory / "EXECUTION.json"
            relative = row["receipt_path"]
            safe_relative(relative)
            if relative.startswith("experiments/hcsn_distributional_v2/"):
                receipt_path = self.root / relative
            elif relative.startswith("cases/"):
                receipt_path = study / relative
            else:
                receipt_path = self.local(relative)
            require(receipt_path.resolve() == expected_receipt.resolve(), "Scaling receipt path names the wrong case")
            receipt = read_json(receipt_path)
            identity = read_json(directory / "IDENTITY.json")
            for evidence in (row, receipt, identity):
                require(evidence["case_id"] == case_id and evidence["protocol_sha256"] == protocol_sha
                        and evidence["source_files_sha256"] == source_map, "Scaling source or protocol identity mismatch")
            require(type(row["returncode"]) is int and receipt["returncode"] == row["returncode"], "Scaling return codes differ")
            if row["returncode"] == 0:
                require((directory / "RESULT.json").is_file() and identity.get("status") != "failed_before_identity",
                        "Successful scaling case has no result or valid identity")
            else:
                require((directory / "FAILURE.json").is_file(), "Failed scaling case lacks preserved failure evidence")
            rows[case_id] = row
        require(set(rows) == set(cases), "Scaling case receipts do not cover all registered cases")
        successful = sum(row["returncode"] == 0 for row in rows.values())
        failed = 30 - successful
        require(completion["successful_cases"] == successful and completion["failed_cases"] == failed
                and completion["all_cases_successful"] is (failed == 0), "Scaling outcome totals are inconsistent")
        suite_path = study / "SUITE_EXECUTION.json"
        suite = read_json(suite_path)
        verify_original_failed_suite(suite, protocol_sha, source_map)
        require(not any((study / name).exists() for name in ("COMPLETE.json", "SUMMARY.json", "REPORT.md")),
                "The failed original suite must not acquire replacement summary outputs")
        require(math.isfinite(suite["complete_child_cpu_seconds"]) and suite["complete_child_cpu_seconds"] >= 0,
                "Invalid scaling complete-process CPU")
        authorization_path = study / "RUN_AUTHORIZATION.json"
        authorization = read_json(authorization_path)
        require(authorization["study_id"] == "scaling002" and authorization["protocol_sha256"] == protocol_sha
                and authorization["source_files_sha256"] == source_map
                and authorization["original_strict_gate_passed"] is False
                and authorization["benchmark_implementation_modified"] is False
                and authorization["admission"]["main_admission"] == declared_admission,
                "Scaling002 run authorization differs from the explicit registered admission")
        for key, relative in (("normalized_lif", "results/lif_cost_receipts001/RECEIPTS.json"),
                              ("normalization_execution", "results/lif_cost_normalization001/EXECUTION.json")):
            path = self.package / relative
            require(authorization["admission"][key] == dict(path=str(path.relative_to(self.root)), sha256=file_hash(path)),
                    "Scaling002 run did not bind final LIF normalization: " + key)
        proofs = dict(scaling_protocol=self.metadata(protocol_path), scaling_completion=self.metadata(completion_path),
                      scaling_suite_execution=self.metadata(suite_path), scaling_run_authorization=self.metadata(authorization_path),
                      original_scaling_protocol=self.metadata(old_protocol_path),
                      original_scaling_not_executed=self.metadata(blocked_path),
                      original_scaling_preflight_execution=self.metadata(preflight_directory / "EXECUTION.json"),
                      original_scaling_preflight_results=self.metadata(preflight_directory / "RESULTS.json"))
        repair = self.audit_summary_repair(study, repair_directory, protocol, protocol_sha, completion, rows)
        proofs.update(repair["proofs"])
        self.scaling_summary_repair = repair
        return dict(directory=study, old_directory=old_study, preflight_directory=preflight_directory,
                    cases=cases, rows=rows, successful=successful, failed=failed, proofs=proofs)

    def audit_summary_repair(self, study, directory, protocol, protocol_sha, completion, rows):
        suite_path = study / "SUITE_EXECUTION.json"
        suite = read_json(suite_path)
        expected_suite = dict(path=str(suite_path.relative_to(self.root)), sha256=file_hash(suite_path), returncode=1)
        require(completion["original_suite"] == expected_suite and completion["original_suite_failed"] is True
                and completion["new_timing_or_inference"] is False
                and completion["original_case_timings_modified"] is False
                and completion["successful_cases"] == 30 and completion["failed_cases"] == 0,
                "Summary repair must preserve the failed suite and all 30 successful original workers")
        log_path = study / "process.log"
        require(file_hash(log_path) == suite["process_log_sha256"]
                and "ZeroDivisionError: float division by zero" in log_path.read_text(),
                "Original failed-suite log is missing or changed")
        repair_source = self.package / "scaling_summary_repair.py"
        source_sha = file_hash(repair_source)
        require(completion["repair_source_sha256"] == source_sha
                and file_hash(directory / "source/scaling_summary_repair.py") == source_sha,
                "Summary repair source differs from its recorded execution")
        bindings_path = directory / "INPUT_BINDINGS.json"
        bindings = read_json(bindings_path)
        require(file_hash(bindings_path) == completion["input_bindings_sha256"]
                and bindings["schema"] == "hcsn-scaling-summary-repair-inputs.v1"
                and bindings["protocol_sha256"] == protocol_sha
                and bindings["original_source_files_sha256"] == protocol["source_files_sha256"]
                and bindings["original_suite"] == expected_suite
                and bindings["repair_source"] == dict(path=str(repair_source.relative_to(self.root)), sha256=source_sha),
                "Summary repair input bindings are incomplete or inconsistent")
        original_files = {str((self.package / "SCALING002_PROTOCOL.json").relative_to(self.root))}
        for path in sorted(study.rglob("*")):
            require(not path.is_symlink(), "Original scaling evidence contains a symlink")
            if path.is_file():
                original_files.add(str(path.relative_to(self.root)))
        require(set(bindings["files"]) == original_files, "Repair did not bind every original scaling file")
        for relative, expected in bindings["files"].items():
            safe_relative(relative)
            path = self.root / relative
            require(path.resolve().is_relative_to(self.package) and not path.is_symlink()
                    and expected == dict(bytes=path.stat().st_size, sha256=file_hash(path)),
                    "Original scaling file changed after repair: " + relative)

        summary_path, report_path = directory / "SUMMARY.json", directory / "REPORT.md"
        require(file_hash(summary_path) == completion["summary_sha256"]
                and file_hash(report_path) == completion["report_sha256"], "Repaired summary or report changed")
        summary = read_json(summary_path)
        require(summary["schema"] == "hcsn-v2-scaling-summary.v1"
                and summary["post_hoc_summary_reconstruction"] is True
                and summary["original_suite"] == expected_suite
                and summary["original_suite_status"] == "failed_after30successful_workers",
                "Summary obscures the independent repair or the original failed suite")
        summary_rows = {row["case_id"]: row for row in summary["rows"]}
        require(len(summary_rows) == len(summary["rows"]) == 30 and set(summary_rows) == set(rows),
                "Summary rows do not cover the same 30 original cases")
        zeros = set()
        for case in protocol["cases"]:
            case_id = case["case_id"]
            case_directory = study / "cases" / case_id
            execution_path = case_directory / "EXECUTION.json"
            identity_path = case_directory / "IDENTITY.json"
            result_path = case_directory / "RESULT.json"
            execution, identity, result = (read_json(path) for path in (execution_path, identity_path, result_path))
            row = summary_rows[case_id]
            require(rows[case_id] == execution and execution["returncode"] == 0
                    and row["returncode"] == 0 and row["receipt_sha256"] == file_hash(execution_path)
                    and row["result_sha256"] == file_hash(result_path), "Repair changed an original worker receipt")
            require(all(row[key] == case[key] for key in ("model", "batch", "length", "width", "depth", "panel")),
                    "Repaired summary case coordinates changed")
            require(result["status"] == "completed" and result["case_id"] == case_id
                    and result["protocol_sha256"] == protocol_sha
                    and result["source_files_sha256"] == protocol["source_files_sha256"]
                    and result["identity_sha256"] == file_hash(identity_path)
                    and row["actual_counts"] == identity["actual_counts"] == result["actual_counts"] == case["registered_counts"]
                    and row["registered_counts"] == case["registered_counts"], "Original case identity or parameter counts changed")
            require(row["worker_cpu_seconds"] == execution["complete_child_cpu_seconds"]
                    and row["worker_wall_seconds"] == execution["wall_seconds"]
                    and row["worker_peak_rss_kib"] == execution["peak_rss_kib_linux"],
                    "Summary changed an original whole-worker measurement")
            require(len(result["warmup"]) == 2 and len(result["forward"]) == len(result["optimizer_step"]) == 3,
                    "Original warmup or repetition counts changed")
            timings = result["warmup"] + result["forward"] + result["optimizer_step"]
            for index, timing in enumerate(timings, 1):
                require(read_json(case_directory / f"MEASURE_{index:02d}.json") == timing
                        and timing["finite_checks_passed"] is True, "Original raw timing differs from its saved result")
                require(all(type(timing[key]) in (int, float) and math.isfinite(timing[key]) and timing[key] >= 0
                            for key in ("cpu_seconds", "wall_seconds")), "Nonfinite original timing")
            for prefix, series in (("forward", result["forward"]), ("optimizer", result["optimizer_step"])):
                for clock in ("cpu", "wall"):
                    field = f"{prefix}_{clock}_median"
                    value = statistics.median(timing[clock + "_seconds"] for timing in series)
                    require(result[field] == row[field] == value, "Repair changed an original measured median")
                    if value == 0:
                        zeros.add((case_id, field))
        zero_rows = summary["zero_timing_medians"]
        require(len(zero_rows) == len(zeros) == completion["zero_timing_median_count"]
                and {(row["case_id"], row["field"]) for row in zero_rows} == zeros
                and all(type(row["value"]) in (int, float) and row["value"] == 0 for row in zero_rows),
                "Summary hid or altered an observed zero timer difference")
        validate_summary_ratios(summary)
        worker_cpu = math.fsum(row["complete_child_cpu_seconds"] for row in rows.values())
        require(completion["complete_worker_cpu_seconds"] == worker_cpu <= suite["complete_child_cpu_seconds"],
                "Original failed suite cost does not contain all original worker measurements")

        outer_directory = self.package / "results/scaling002_summary_repair001_execution"
        outer_path = outer_directory / "EXECUTION.json"
        outer = read_json(outer_path)
        require(outer["schema"] == "hcsn-measured-support-execution.v1" and outer["status"] == "completed"
                and type(outer["returncode"]) is int and outer["returncode"] == 0
                and outer["source_sha256"] == file_hash(self.package / "measured_support.py")
                and outer["request_sha256"] == file_hash(outer_directory / "REQUEST.json")
                and outer["log_sha256"] == file_hash(outer_directory / "process.log"),
                "Summary repair has no successful, source-bound independent outer receipt")
        require(type(outer["complete_child_cpu_seconds"]) in (int, float)
                and math.isfinite(outer["complete_child_cpu_seconds"]) and outer["complete_child_cpu_seconds"] >= 0,
                "Summary repair outer CPU is invalid")
        inner_path = directory / "EXECUTION.json"
        inner = read_json(inner_path)
        require(inner["schema"] == "hcsn-scaling-summary-repair-body.v1" and inner["status"] == "completed"
                and inner["source_sha256"] == source_sha
                and inner["complete_sha256"] == file_hash(directory / "COMPLETE.json"),
                "Summary repair body and completion identities disagree")
        proofs = dict(scaling_original_failed_suite_log=self.metadata(log_path),
            scaling_summary_repair_summary=self.metadata(summary_path), scaling_summary_repair_report=self.metadata(report_path),
            scaling_summary_repair_inputs=self.metadata(bindings_path), scaling_summary_repair_body=self.metadata(inner_path),
            scaling_summary_repair_source=self.metadata(repair_source), scaling_summary_repair_outer=self.metadata(outer_path),
            scaling_summary_repair_outer_request=self.metadata(outer_directory / "REQUEST.json"),
            scaling_summary_repair_outer_log=self.metadata(outer_directory / "process.log"))
        return dict(directory=directory, outer_directory=outer_directory, proofs=proofs,
            original_suite=expected_suite, original_suite_cpu_seconds=suite["complete_child_cpu_seconds"],
            repair_outer=dict(path=str(outer_path.relative_to(self.root)), sha256=file_hash(outer_path), returncode=0),
            repair_cpu_seconds=outer["complete_child_cpu_seconds"], zero_timing_medians=len(zeros),
            undefined_ratios=sum(value is None for change in summary["measured_fixed_width_depth_changes"]
                                 for key, value in change.items() if key.endswith("_ratio_to_16") and key != "length_ratio_to_16"))

    def run(self):
        record = super().run()
        repair = self.scaling_summary_repair
        repaired_inventory = {}
        for directory in (repair["directory"], repair["outer_directory"]):
            files = set()
            for path in sorted(directory.rglob("*")):
                require(not path.is_symlink() and "work" not in path.relative_to(directory).parts,
                        "Repair evidence contains a symlink or internal work tree")
                if path.is_file():
                    self.covered_file(path)
                    files.add(self.relative(path))
            prefix = self.relative(directory) + "/"
            require({path for path in self.union if path.startswith(prefix)} == files,
                    "Repair archive must contain every file in the independent repair evidence")
            repaired_inventory[self.relative(directory)] = len(files)
        record["scaling_case_coverage"].update(original_suite=repair["original_suite"],
            original_suite_succeeded=False, independent_summary_repair=repair["repair_outer"],
            summary_repair_succeeded=True, original_case_timings_modified=False, new_timing_or_inference=False,
            zero_timing_median_count=repair["zero_timing_medians"], undefined_ratio_count=repair["undefined_ratios"],
            repair_evidence_inventories=repaired_inventory,
            interpretation="All 30 original workers succeeded. Original scaling002 suite returned 1 during summary division by zero and remains failed; a separately measured read-only summary repair completed. Original zero timer values are preserved and corresponding ratios remain null.")
        record["archive_consumer"] = dict(derived_source=self.metadata(Path(__file__)),
            normalized_base_source=self.metadata(Path(base.__file__)), normalized_base_unchanged=True,
            scope="Inherits original main/LIF/archive checks; adds explicit failed-suite plus independent-summary-repair scaling verification")
        return record



def execute(package, output):
    package, output = Path(package).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    status, error, result = "failed", None, None
    source_sha = file_hash(Path(__file__))
    try:
        require(not (package / "artifacts/ARCHIVE_COMPLETION.json").exists(), "Archive closure is immutable and already exists")
        result = ClosureAudit(package).run()
        pending = output / "ARCHIVE_COMPLETION.candidate.json"
        write_new(pending, result)
        # Same-filesystem exclusive link is atomic and cannot overwrite a prior
        # closure. No successful closure is exposed until all checks have passed.
        os.link(pending, package / "artifacts/ARCHIVE_COMPLETION.json")
        status = "completed"
        print(json.dumps(dict(status=status, bundles=len(result["bundles"]), main=result["main_run_coverage"]["unique"],
                              lif=result["lif_run_coverage"]["unique"], closure_sha256=file_hash(pending))), flush=True)
        return result
    except BaseException:
        error = traceback.format_exc()
        raise
    finally:
        write_new(output / "EXECUTION.json", dict(schema="hcsn-v2-archive-closure-execution.v1", status=status,
            source_sha256=source_sha, own_cpu_seconds_through_receipt=time.process_time(),
            wall_seconds=time.perf_counter()-started, error=error,
            closure_path="artifacts/ARCHIVE_COMPLETION.json" if status == "completed" else None,
            closure_sha256=file_hash(package / "artifacts/ARCHIVE_COMPLETION.json") if status == "completed" else None,
            scope="Auditor process self CPU through receipt, excludes final serialization and exit; no children; outside all evidence bundles and never recursively charged to them"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--output", type=Path, default=PACKAGE / "results/archive_closure001")
    arguments = parser.parse_args()
    execute(arguments.package, arguments.output)
