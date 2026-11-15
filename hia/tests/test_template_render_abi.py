#!/usr/bin/env python3
"""Run the unchanged render buffer matrix against the actual formal native build."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

sys.dont_write_bytecode = True
from template_render_oracle.admission import admit, require
from template_render_oracle.raw_matrix import exercise
from template_render_oracle.raw_runtime import Runner, identity

EXPECTED_COUNTS = {
    "calls": 66026, "operation_0": 22735, "operation_1": 35663,
    "operation_2": 7624, "operation_3": 2, "operation_18446744073709551615": 2,
    "status_4294967295": 48543, "status_4294967294": 5719, "status_0": 11764,
    "nonzero_entire_output_unchanged": 54262, "semantic_errors": 10722,
}


def run(args, report, output):
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    require(Path(__file__).resolve() == args.producer / "hia/tests/test_template_render_abi.py",
            "the ABI runner must belong to its actual producing checkout")
    build, library, bindings = admit(args.producer, args.library_dir)
    report["bound_inputs"] = bindings
    report["formal_module_count"] = len(build["modules"])
    report["native_library"] = identity(library)
    runner = Runner(args.producer, library, output)
    try:
        exercise(runner.check)
        result = runner.finish()
        require(result["counts"] == EXPECTED_COUNTS, "the complete unchanged raw matrix coverage differs")
        for name, record in bindings.items():
            require(identity(Path(name)) == {"path": name, **record},
                    "a formally admitted source or artifact changed")
        report.update(result)
        report.update(passed=True, all_bound_inputs_unchanged=True)
    except BaseException:
        runner.trace.close()
        report["partial_counts"] = dict(runner.counts)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.producer = args.producer.resolve(strict=True)
    args.library_dir = args.library_dir.resolve(strict=True)
    report_path = args.report.resolve()
    output = report_path.with_name(report_path.stem + "-files")
    for path in (report_path, output):
        require(not any(path == root or path.is_relative_to(root)
                        for root in (args.producer, args.library_dir)),
                "results must be outside the producing checkout and native artifacts")
        require(not path.exists(), "historical result paths cannot be overwritten")
    require(shutil.disk_usage(args.producer).free >= 24 * 1024 * 1024,
            "fresh 24 MiB reserve unavailable before output creation")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    os.nice(10)
    report = {"schema": "codex.hia.template-render-formal-abi.v1", "passed": False,
        "controller": identity(Path(__file__)), "started_ns": time.time_ns(),
        "producer": str(args.producer), "library_dir": str(args.library_dir),
        "work_dir": str(output), "skipped": 0,
        "scope": "Complete unchanged valid/malformed/priority/large-frame raw matrix, admitted against both actual template components and the complete fixed-point native build. The raw reference reads the contract; complete original Rust behavior is a separate public gate.",
        "original_rust_differential_qualified": False, "actual_cargo_qualified": False,
        "concurrent_execution": False, "whole_product_qualified": False,
        "default_changed": False, "performance_qualified": False, "legacy_retirement": False}
    try:
        run(args, report, output)
    except BaseException:
        report["exception"] = traceback.format_exc()
        raise
    finally:
        report["finished_ns"] = time.time_ns()
        with report_path.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(json.dumps({"passed": report["passed"], "report": identity(report_path)}), flush=True)


if __name__ == "__main__":
    main()
