#!/usr/bin/env python3
"""Run the complete standalone continuation matrix on a genuine native build.

This gate preserves the previously executed 6310-call matrix. Whole-original
process arguments, I/O, filesystem effects and runtime behavior are separate.
"""
import argparse
import ctypes
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from patch_standalone_oracle.abi_admission import SYMBOL
from patch_standalone_oracle.abi_admission import admit
from patch_standalone_oracle.abi_admission import require
from patch_standalone_oracle.abi_admission import sha
from patch_standalone_oracle.abi_cases import run_cases

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, default=ROOT)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.resolve()
    require(not report_path.exists(), "a previous report must not be overwritten")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "codex.hia.patch-standalone-abi-test.v1",
        "passed": False,
        "scope": "The full continuation ABI and buffer atomicity matrix, bound to the actual complete native-selfhost build and every locked HIA source.",
        "producer": str(ROOT),
        "library_dir": str(args.library_dir.resolve()),
        "complete_process_qualified": False,
        "runtime_initialization_failure_qualified": False,
        "stdout_flush_failure_qualified": False,
        "cargo_qualified": False,
        "simultaneous_thread_execution": False,
        "whole_codex_rewritten": False,
        "legacy_retirement": False,
        "tests_skipped": 0,
    }
    inputs = {}
    try:
        producer = args.producer.resolve(strict=True)
        require(producer == ROOT, "standalone ABI producer differs from executing checkout")
        build, library_path, inputs = admit(producer, args.library_dir.resolve())
        for path in (
            Path(__file__).resolve(),
            ROOT / "hia/tests/patch_standalone_oracle/abi_cases.py",
            ROOT / "hia/tests/patch_standalone_oracle/__init__.py",
            ROOT / "codex-rs/apply-patch/src/hia_native_patch_standalone.rs",
            ROOT / "codex-rs/apply-patch/src/standalone_executable.rs",
            ROOT / "codex-rs/apply-patch/src/lib.rs",
        ):
            inputs[str(path)] = {"bytes": path.stat().st_size, "sha256": sha(path)}
        result["input_bindings"] = inputs
        result["locked_modules"] = list(build["toolchain"]["modules"])
        library = ctypes.CDLL(str(library_path))
        function = getattr(library, SYMBOL)
        function.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p,
                             ctypes.c_uint64, ctypes.c_void_p, ctypes.c_uint64]
        function.restype = ctypes.c_uint64
        matrix = run_cases(function, report_path.with_suffix(".calls.jsonl"))
        result["matrix"] = matrix
        require(matrix.get("passed") is True, "standalone raw matrix failed: " + str(matrix.get("error")))
        require(matrix["counters"]["calls"] == 6310 and
                matrix["counters"]["error_no_write_calls"] == 5097 and
                matrix["unique_transition_keys"] == 25 and
                matrix["source_condition_outcomes"] == 27 and
                matrix["actions"] == list(range(1, 18)) and
                len(matrix["complete_callback_traces"]) == 13 and
                matrix["interleaved_instances"] == 128,
                "the frozen complete raw matrix or its coverage changed")
        for filename, expected in inputs.items():
            path = Path(filename)
            require({"bytes": path.stat().st_size, "sha256": sha(path)} == expected,
                    "a bound input changed during the raw gate: " + filename)
        result["source_and_artifacts_unchanged"] = True
        result["passed"] = True
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    with report_path.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"report": str(report_path), "sha256": sha(report_path),
                      "passed": result["passed"],
                      "native_calls": result.get("matrix", {}).get("counters", {}).get("calls", 0)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
