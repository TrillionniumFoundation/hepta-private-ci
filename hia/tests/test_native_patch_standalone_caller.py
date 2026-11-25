#!/usr/bin/env python3
"""Compare complete immutable original/native standalone OS processes.

Both binaries use the entire original src/main.rs and complete admitted owner
libraries. This gate compiles those real entrypoints with direct rustc; its
required effects report supplies fresh actual Cargo graphs and 13 root tests.
"""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def verify(args, report):
    producer = args.producer.resolve(strict=True)
    if Path(__file__).resolve() != producer / "hia/tests/test_native_patch_standalone_caller.py":
        raise RuntimeError("the process CLI must come from its actual producing checkout")
    if sys.flags.optimize:
        raise RuntimeError("qualification cannot disable Python assertions")
    sys.path.insert(0, str(producer / "hia/tests"))
    from patch_standalone_oracle import prerequisite
    from patch_standalone_oracle import processes

    context = prerequisite.prepare(args, report)
    public = processes.run(context["binaries"], context["work"] / "process-observations")
    report["process_observations"] = {key: value for key, value in public.items() if key != "cases"}
    report["process_observations"]["report_path"] = str(context["work"] / "process-observations/report.json")
    prerequisite.unchanged(context)
    report["source_and_artifacts_unchanged"] = True
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("producer", "library-dir", "effects-report", "rustc", "work-dir", "report"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    # A failure report must not write into the pinned original checkout either.
    from patch_effects_oracle import admission
    original = admission.parent_original_checkout(
        args.effects_report.resolve(strict=True), args.producer.resolve(strict=True))
    path = args.report.resolve()
    admission.identity.outside(path, (original,))
    if path.exists() or any(path.is_relative_to(root.resolve()) for root in (args.producer, args.library_dir)):
        raise RuntimeError("report must be new and outside source/artifact directories")
    report = {
        "schema": "codex.hia.native-patch-standalone-caller.v1", "passed": False,
        "scope": "Actual argv/stdin/environment/cwd/stdout/stderr/status/filesystem observations of complete original and native programs, with identical paths and no result normalization.",
        "cargo_compilation_executed_by_this_gate": False,
        "whole_original_program_execution": False,
        "filesystem_results_substituted": False,
        "paths_or_errors_normalized": False,
        "controlled_runtime_initialization_failure_qualified": False,
        "stdout_flush_failure_qualified": False,
        "write_syscall_trace_qualified": False,
        "controlled_runtime_shutdown_or_cancellation_qualified": False,
        "entire_crate_test_suite_qualified_by_this_report": False,
        "whole_product_qualification": False,
        "performance_qualification": False,
        "legacy_retirement_qualification": False,
    }
    try:
        verify(args, report)
        report["whole_original_program_execution"] = True
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        print(report["error"], file=sys.stderr)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": report["passed"], "report": str(path),
                      "processes": report.get("process_observations", {})}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
