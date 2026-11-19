"""Read-only reconstruction after SCALING002's zero-denominator summary failure.

No timing, neural execution, model import, or modification of original evidence.
The original suite remains failed. A separately identified receipt certifies
coverage and aggregation of its 30 successful original workers.
"""

import argparse
import math
from pathlib import Path
import shutil
import statistics
import sys
import time

from . import scaling_admission as admission


PACKAGE, ROOT = admission.PACKAGE, admission.ROOT
sha, read, write, relative, require = admission.sha, admission.read, admission.write, admission.relative, admission.require


def ratio(numerator, denominator):
    require(type(numerator) in (int, float) and type(denominator) in (int, float) and
            math.isfinite(numerator) and math.isfinite(denominator) and min(numerator, denominator) >= 0,
            "Ratios require original finite nonnegative timings")
    return None if denominator == 0 else numerator / denominator


def repair(output):
    require(__debug__, "Use normal Python, without -O")
    require(not output.exists(), "Summary repair requires a new directory")
    study = PACKAGE / "results/scaling002"
    protocol_path = PACKAGE / "SCALING002_PROTOCOL.json"
    protocol = admission.registered(protocol_path, study)
    sources, protocol_sha = protocol["source_files_sha256"], sha(protocol_path)
    require(read(study / "RUN_AUTHORIZATION.json")["admission"] == admission.run_gates(), "Admission evidence changed")
    suite_path = study / "SUITE_EXECUTION.json"
    suite = read(suite_path)
    require(suite["returncode"] == 1 and suite["complete_receipt_sha256"] is None and
            suite["protocol_sha256"] == protocol_sha and suite["source_files_sha256"] == sources,
            "Repair requires the explicit failed original suite")
    log_path = study / "process.log"
    require(sha(log_path) == suite["process_log_sha256"] and
            "ZeroDivisionError: float division by zero" in log_path.read_text(), "Original summary failure log differs")
    require(not any((study / name).exists() for name in ("SUMMARY.json", "REPORT.md", "COMPLETE.json")),
            "Original summary output unexpectedly exists")
    expected_ids = {case["case_id"] for case in protocol["cases"]}
    require(len(expected_ids) == 30 and {p.name for p in (study / "cases").iterdir()} == expected_ids,
            "Original case directory set differs from the registered30")
    input_files = [protocol_path, *sorted(path for path in study.rglob("*") if path.is_file())]
    bindings = {relative(path): dict(sha256=sha(path), bytes=path.stat().st_size) for path in input_files}
    records, rows, zero_medians, same_length_inputs = [], [], [], {}
    for case in protocol["cases"]:
        directory = study / "cases" / case["case_id"]
        execution_path, identity_path, result_path = (directory / name for name in ("EXECUTION.json", "IDENTITY.json", "RESULT.json"))
        record, identity, result = read(execution_path), read(identity_path), read(result_path)
        require(record["returncode"] == 0 and record["receipt_path"] == relative(execution_path), "An original worker did not succeed")
        for value in (record, identity, result):
            require(value["case_id"] == case["case_id"] and value["protocol_sha256"] == protocol_sha and
                    value["source_files_sha256"] == sources, "Original case identity/source/protocol differs")
        require(all(record[key] == case[key] for key in ("model", "batch", "length", "width", "depth")),
                "Original case coordinates differ")
        require(result["status"] == "completed" and identity["actual_counts"] == result["actual_counts"] == case["registered_counts"] and
                identity["full_model_config"] == case["registered_model_config"] and
                result["identity_sha256"] == sha(identity_path), "Original case metadata differs")
        require(identity["inputs_sha256"] == sha(directory / "INPUTS.npz") and
                identity["initial_sha256"] == sha(directory / "INITIAL.npz"), "Original synthetic input/initial weights changed")
        require(identity["input_seed"] == protocol["randomness"]["input_seed"] and
                identity["torch_threads"] == identity["torch_interop_threads"] == 1,
                "Original input seed/thread contract differs")
        previous_inputs = same_length_inputs.setdefault(case["length"], identity["input_arrays"])
        require(previous_inputs == identity["input_arrays"], "Same-length configurations did not use identical inputs")
        require(len(result["warmup"]) == 2 and len(result["forward"]) == len(result["optimizer_step"]) == 3 and
                result["completed_adam_steps"] == [4] and result["changed_state_tensors"] > 0,
                "Original full optimizer/warmup/repetition contract differs")
        timings = result["warmup"] + result["forward"] + result["optimizer_step"]
        for index, timing in enumerate(timings, 1):
            require(read(directory / f"MEASURE_{index:02d}.json") == timing and timing["finite_checks_passed"] is True,
                    "Original raw timing differs from its result")
            require(all(type(timing[key]) in (int, float) and math.isfinite(timing[key]) and timing[key] >= 0
                        for key in ("cpu_seconds", "wall_seconds")), "Invalid original timing")
        for prefix, series in (("forward", result["forward"]), ("optimizer", result["optimizer_step"])):
            for clock in ("cpu", "wall"):
                field = f"{prefix}_{clock}_median"
                require(result[field] == statistics.median(timing[clock + "_seconds"] for timing in series),
                        "Stored median does not match all three original repetitions")
                if result[field] == 0:
                    zero_medians.append(dict(case_id=case["case_id"], field=field, value=0,
                        interpretation="Observed zero timer difference; not a claim of zero computational work"))
        records.append(record)
        row = {key: case[key] for key in admission.frozen.cases()[0]}
        row.update(returncode=0, actual_counts=identity["actual_counts"], registered_counts=case["registered_counts"],
            **{key: result[key] for key in ("forward_cpu_median", "optimizer_cpu_median", "forward_wall_median", "optimizer_wall_median")},
            worker_cpu_seconds=record["complete_child_cpu_seconds"], worker_wall_seconds=record["wall_seconds"],
            worker_peak_rss_kib=record["peak_rss_kib_linux"], receipt_sha256=sha(execution_path), result_sha256=sha(result_path))
        rows.append(row)
    require(suite["complete_child_cpu_seconds"] >= math.fsum(row["complete_child_cpu_seconds"] for row in records),
            "Failed suite wait4 must contain all completed worker CPU")
    changes = []
    for model in admission.frozen.MODELS:
        selected = [row for row in rows if row["model"] == model and row["panel"] == "length"]
        base = next(row for row in selected if row["length"] == 16)
        for row in selected:
            change = dict(model=model, length=row["length"], length_ratio_to_16=row["length"] / 16,
                          undefined_ratio_reasons={})
            for operation in ("forward", "optimizer"):
                for clock in ("cpu", "wall"):
                    key = f"{operation}_{clock}_ratio_to_16"
                    field = f"{operation}_{clock}_median"
                    change[key] = ratio(row[field], base[field])
                    if change[key] is None:
                        change["undefined_ratio_reasons"][key] = "T16 denominator was recorded as zero; no epsilon or fabricated ratio"
            changes.append(change)
    output.mkdir(parents=True)
    (output / "source").mkdir()
    shutil.copyfile(__file__, output / "source" / Path(__file__).name)
    original_suite = dict(path=relative(suite_path), sha256=sha(suite_path), returncode=1)
    summary = dict(schema="hcsn-v2-scaling-summary.v1", rows=rows, measured_fixed_width_depth_changes=changes,
        post_hoc_summary_reconstruction=True, original_suite=original_suite, original_suite_status="failed_after30successful_workers",
        zero_timing_medians=zero_medians, interpretation="Original measured CPU/wall values unchanged; zero-denominator ratios are null. Descriptive CPU implementation only; no quality/GPU/energy/asymptotic claim")
    write(output / "SUMMARY.json", summary)
    lines = ["# SCALING002: reconstructed summary of the original30 timings", "",
        "All30 original workers succeeded. The original suite returned1 while dividing by a T16 CPU median recorded as0; its failed receipt remains unchanged. This independent read-only summary reruns no model or timing. Every median is checked against all three original per-operation records.", "",
        "A recorded0 CPU duration is preserved and does not mean computational work was free. Ratios with a zero denominator are unavailable. No epsilon, substituted wall time, or fresh measurement is inserted. Wall measurements remain separate original observations.", "",
        "| Model | T | Width | Depth | Actual parameters | Forward CPU(s) | Adam CPU(s) | Forward wall(s) | Adam wall(s) | Whole worker CPU(s) | Peak RSS(KiB) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        values = " | ".join(f"{row[key]:.9f}" for key in ("forward_cpu_median", "optimizer_cpu_median", "forward_wall_median", "optimizer_wall_median", "worker_cpu_seconds"))
        lines.append(f"| {row['model']} | {row['length']} | {row['width']} | {row['depth']} | {row['actual_counts']['total']} | {values} | {row['worker_peak_rss_kib']} |")
    lines += ["", "## Fixed width32/depth1: observed changes from T16", "",
        "| Model | T | Forward CPU ratio | Adam CPU ratio | Forward wall ratio | Adam wall ratio |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in changes:
        formatted = ["unavailable: zero denominator" if row[key] is None else f"{row[key]:.4f}" for key in
                     ("forward_cpu_ratio_to_16", "optimizer_cpu_ratio_to_16", "forward_wall_ratio_to_16", "optimizer_wall_ratio_to_16")]
        lines.append(f"| {row['model']} | {row['length']} | " + " | ".join(formatted) + " |")
    lines += ["", "Random weights/labels, batch1, one shared synthetic input sequence, CPU float32, one thread, one forward/Adam warmup and three measured forwards/full Adam steps. All actual parameter counts are reported; no imposed3% parameter matching claim. RSS is whole-process high-water memory, including interpreter, imports, construction and backwards; it is not isolated activation memory.", "",
        "Original suite CPU and each worker CPU are nested. The separate reconstruction process is measured independently. These30 points provide no evidence about content quality, GPU, energy, distributed execution, equal-quality throughput, foundation models or an asymptotic scaling law.", ""]
    (output / "REPORT.md").write_text("\n".join(lines))
    write(output / "INPUT_BINDINGS.json", dict(schema="hcsn-scaling-summary-repair-inputs.v1", files=bindings,
        original_suite=original_suite, protocol_sha256=protocol_sha, original_source_files_sha256=sources,
        repair_source=dict(path=relative(__file__), sha256=sha(__file__))))
    for path, binding in bindings.items():
        require(sha(ROOT / path) == binding["sha256"], "Original evidence changed during summary reconstruction")
    write(output / "COMPLETE.json", dict(schema="hcsn-v2-scaling-summary-repair-complete.v1", status="completed", study_id="scaling002",
        repair_id=output.name, expected_cases=30, completed_cases=30, successful_cases=30, failed_cases=0, all_cases_successful=True,
        records=records, protocol_sha256=protocol_sha, source_files_sha256=sources, original_strict_gate_passed=False,
        admission_evidence=protocol["admission_evidence"], frozen_benchmark=protocol["frozen_benchmark"], original_suite=original_suite,
        original_suite_failed=True, original_case_timings_modified=False, new_timing_or_inference=False,
        complete_worker_cpu_seconds=math.fsum(row["complete_child_cpu_seconds"] for row in records),
        summary_sha256=sha(output / "SUMMARY.json"), report_sha256=sha(output / "REPORT.md"),
        input_bindings_sha256=sha(output / "INPUT_BINDINGS.json"), repair_source_sha256=sha(__file__),
        zero_timing_median_count=len(zero_medians), completed_utc=admission.frozen.utc()))
    require("torch" not in sys.modules and "numpy" not in sys.modules, "Repair must remain stdlib-only")
    write(output / "EXECUTION.json", dict(schema="hcsn-scaling-summary-repair-body.v1", status="completed",
        whole_self_cpu_seconds_through_receipt=time.process_time(), complete_sha256=sha(output / "COMPLETE.json"),
        source_sha256=sha(__file__), measurement="Nested in the separate measured-support full child receipt; do not add this self clock"))
    print(f"reconstructed30original workers; zero_medians={len(zero_medians)}; original suite remains failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PACKAGE / "results/scaling002_summary_repair001")
    repair(parser.parse_args().output.resolve())
