#!/usr/bin/env python3
"""Replay the complete frozen 19,232-call UUID ABI matrix on a formal build."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

sys.dont_write_bytecode = True
from uuid_find_oracle.common import binding, outside, require, save
from uuid_find_oracle.raw import run_cases
from uuid_find_oracle.transport import Native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    producer, library_dir = args.producer.resolve(strict=True), args.library_dir.resolve(strict=True)
    report_path = outside(args.report, (producer, library_dir))
    work = outside(args.work_dir or report_path.with_name(report_path.stem + "-files"), (producer, library_dir))
    require(not report_path.exists(), "report exists; prior executions are immutable")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=False)
    report = {"schema": "codex.hia.uuid-formal-abi.v1", "passed": False,
        "started_unix": time.time(), "controller": binding(Path(__file__)),
        "producer": str(producer), "library_dir": str(library_dir), "work_dir": str(work),
        "scope": "Actual formal HIA buffers and arbitrary-byte pattern contract. Python byte regex is only the raw-byte checker; complete original Rust/regex behavior is a separate public gate.",
        "concurrent_execution": False, "tests_skipped": 0, "invented_oversized_pointer_ranges_used": False,
        "usize_max_allocations_executed": False, "cargo_qualified": False,
        "whole_product_qualified": False, "legacy_retirement": False}
    native = None
    try:
        native = Native(producer, library_dir, work / "calls.jsonl.gz")
        run_cases(native, report)
        report["formal_module_count"] = len(native.build["modules"])
        report["passed"] = True
    except BaseException:
        report["exception"] = traceback.format_exc()
        raise
    finally:
        if native is not None:
            try:
                report.update(native.finish())
            except BaseException:
                report["passed"] = False
                report["terminal_verification_exception"] = traceback.format_exc()
                raise
            finally:
                report["finished_unix"] = time.time()
                save(report_path, report)
        else:
            report["finished_unix"] = time.time()
            save(report_path, report)
        print(json.dumps({"passed": report["passed"], "report": binding(report_path)}), flush=True)


if __name__ == "__main__":
    main()
