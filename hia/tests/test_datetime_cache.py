"""Qualify the production cache-duration object against original Chrono APIs."""
import argparse
from collections import Counter
import ctypes
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
from datetime_cache_cases import cache_cases
from datetime_calendar_oracle.custody import binding, compile_original, require
from test_datetime_calendar import identity
from test_duration_units import preserve

ROOT = Path(__file__).resolve().parents[2]
MASK = (1 << 64) - 1


def qualify(args, report):
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    before = identity()
    contract_path = ROOT / "hia/datetime_cache_buffer_contract.json"
    contract = json.loads(contract_path.read_bytes())
    source = binding(ROOT / "hia/datetime_cache.hepta")
    build_path = args.build / "build.json"
    build = json.loads(build_path.read_bytes())
    lock_path = ROOT / "hia/toolchain.json"
    lock = json.loads(lock_path.read_bytes())
    require(build["status"] == "built" and build["build_mode"] == "native-selfhost"
            and build["compiler_fixed_point"] is True
            and build["compiler_sha256"] == contract["compiler"]["native_sha256"],
            "production build has no original native fixed point")
    require(build["toolchain"] == lock and build["toolchain_lock_sha256"] == binding(lock_path)["sha256"]
            and build["build_driver_sha256"] == binding(ROOT / "hia/build.py")["sha256"]
            and build["cargo_helper_sha256"] == binding(ROOT / "hia/cargo_build.rs")["sha256"],
            "production build inputs differ from the producing tree")
    require(set(build["modules"]) == set(lock["modules"]), "production module inventory differs")
    for name, row in build["modules"].items():
        require(row["source_sha256"] == binding(ROOT / f"hia/{name}.hepta")["sha256"],
                "production HIA source differs: " + name)
    row = build["modules"]["datetime_cache"]
    require(source["sha256"] == contract["source_sha256"] == row["source_sha256"]
            and row["core_sha256"] == contract["core_sha256"], "cache source or Core differs")
    library_path = args.build / "datetime_cache.so"
    library_binding = binding(library_path)
    require(library_binding["sha256"] == row["library_sha256"]
            and library_binding["bytes"] == row["library_bytes"], "native library differs")
    for caller in contract["production_callers"]:
        actual = binding(ROOT / caller["path"])
        require(actual["bytes"] == caller["current_bytes"]
                and actual["sha256"] == caller["current_sha256"], "production caller source differs")
    for original_test in contract["unchanged_original_test_files"]:
        actual = binding(ROOT / original_test["path"])
        require(actual["bytes"] == original_test["bytes"] and actual["sha256"] == original_test["sha256"],
                "original complete test file changed")
    report.update(producer=before, contract=binding(contract_path), source=source,
                  native_build=binding(build_path), library=library_binding)
    executable, original = compile_original(ROOT, args.original_lock, args.cargo, args.rustc,
                                             args.output, contract, "hia/tests/datetime_cache_oracle")
    report["original"] = {"receipt": binding(args.output / "original-custody.json"),
                          "executable": original["executable"], "toolchain": original["toolchain"]}
    cases = cache_cases()
    corpus = contract["differential_corpus"]
    raw = b"".join(struct.pack("<7Q", *case) for case in cases)
    report["inputs"] = preserve(args.output / "inputs.bin.gz", raw)
    require(len(cases) == corpus["total_cases"] and report["inputs"]["raw_sha256"] == corpus["input_sha256"],
            "cache corpus differs from the complete frozen duration/date boundaries")
    observed = subprocess.run([str(executable)], input=raw, capture_output=True, timeout=60)
    report["original_output"] = preserve(args.output / "original-chrono.bin.gz", observed.stdout)
    (args.output / "original-chrono.stderr").write_bytes(observed.stderr)
    require(observed.returncode == 0 and len(observed.stdout) == len(cases) * 32
            and report["original_output"]["raw_sha256"] == corpus["original_output_sha256"],
            "actual original Chrono observations differ or are incomplete")
    counts = Counter((case[0], *words[1:])
                     for case, words in zip(cases, struct.iter_unpack("<4Q", observed.stdout)))
    counts = {",".join(map(str, key)): value for key, value in sorted(counts.items())}
    require(counts == corpus["original_result_counts"], "cache policy outcome coverage differs")
    report.update(cases=len(cases), original_result_counts=counts)
    library = ctypes.CDLL(str(library_path))
    entry = library.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint64
    prefix, suffix = bytes(range(17)), bytes(range(239, 256))
    trace_hash = hashlib.sha256()
    trace_bytes, calls, semantic_calls = 0, 0, 0
    controls = {}
    trace_path = args.output / "native-calls.bin.gz"
    try:
        with trace_path.open("xb") as file, gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as trace:
            def call(frame, workspace, capacity, fill, status, expected=b""):
                nonlocal calls, trace_bytes
                initial = (prefix + frame + suffix, prefix + workspace + suffix,
                           prefix + bytes([fill]) * capacity + suffix)
                source_buf, workspace_buf, output_buf = [ctypes.create_string_buffer(data, len(data)) for data in initial]
                actual = entry(ctypes.addressof(source_buf) + 17, len(frame), ctypes.addressof(output_buf) + 17,
                               capacity, ctypes.addressof(workspace_buf) + 17, len(workspace))
                calls += 1
                record = struct.pack("<7Q", len(frame), len(workspace), capacity, fill, status, actual, len(output_buf.raw))
                record += frame + workspace + output_buf.raw
                trace.write(record)
                trace_hash.update(record)
                trace_bytes += len(record)
                require(actual == status, "native status differs at call " + str(calls))
                require(source_buf.raw == initial[0] and workspace_buf.raw == initial[1], "input or guard mutation")
                wanted = initial[2] if status else prefix + expected + bytes([fill]) * (capacity - len(expected)) + suffix
                require(output_buf.raw == wanted,
                        "native cache result, atomic no-write, tail or guard differs at call " + str(calls))

            for index, case in enumerate(cases):
                frame = struct.pack("<8Q", 1, *case)
                expected = observed.stdout[index * 32:(index + 1) * 32]
                for capacity in [32, 45]:
                    for fill in [0, 165]:
                        call(frame, b"", capacity, fill, 0, expected)
            semantic_calls = calls
            good = struct.pack("<8Q", 1, 1, 0, 0, 0, 0, 1, 0)
            for frame in [good[:n] for n in range(64)] + [good + b"\0" * n for n in [1, 8, 16]]:
                for capacity in [0, 31, 32, 45]:
                    for fill in [0, 165]:
                        call(frame, b"", capacity, fill, 0xFFFFFFFE if capacity < 32 else 0xFFFFFFFF)
            controls["frame_sizes"] = calls - semantic_calls
            group_start = calls
            for position, values in [(0, [0, 2, MASK]), (1, [3, MASK])]:
                for value in values:
                    words = [1, 1, 0, 0, 0, 0, 1, 0]
                    words[position] = value
                    for capacity in [31, 32, 45]:
                        call(struct.pack("<8Q", *words), b"", capacity, 165,
                             0xFFFFFFFE if capacity < 32 else 0xFFFFFFFF)
            controls["metadata"] = calls - group_start
            group_start = calls
            for position in range(2, 6):
                for value in [1, MASK]:
                    words = [1, 0, 0, 0, 0, 0, 1, 0]
                    words[position] = value
                    for capacity in [31, 32, 45]:
                        call(struct.pack("<8Q", *words), b"", capacity, 165,
                             0xFFFFFFFE if capacity < 32 else 0xFFFFFFFF)
            controls["unused_preflight_dates"] = calls - group_start
            controls["short_capacity_by_operation"] = 0
            controls["workspace_by_operation"] = 0
            for operation in range(3):
                frame = struct.pack("<8Q", 1, operation, 0, 0, 0, 0, 1, 0)
                group_start = calls
                for capacity in range(32):
                    call(frame, b"", capacity, 165, 0xFFFFFFFE)
                controls["short_capacity_by_operation"] += calls - group_start
                group_start = calls
                for workspace in [b"\0", b"\xa5" * 8, b"\0" * 64]:
                    for capacity in [31, 32, 45]:
                        call(frame, workspace, capacity, 165, 0xFFFFFFFE if capacity < 32 else 0xFFFFFFFF)
                controls["workspace_by_operation"] += calls - group_start
    finally:
        report.update(native_calls=calls, semantic_calls=semantic_calls, buffer_control_groups=controls,
                      trace={"raw_bytes": trace_bytes, "raw_sha256": trace_hash.hexdigest(),
                             "archive": binding(trace_path)})
    require(controls == corpus["buffer_control_groups"], "native buffer control groups are incomplete")
    require(calls - semantic_calls == sum(controls.values()) == corpus["buffer_control_calls"]
            and calls == corpus["native_calls_required"] == len(cases) * 4 + sum(controls.values()),
            "native cache call coverage is incomplete")
    report["buffer_control_calls"] = calls - semantic_calls
    require(identity() == before and binding(library_path) == library_binding
            and binding(ROOT / "hia/datetime_cache.hepta") == source, "source or native artifact changed")
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--original-lock", type=Path, required=True)
    parser.add_argument("--cargo", type=Path, required=True)
    parser.add_argument("--rustc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name in ("build", "original_lock", "cargo", "rustc"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    args.output = args.output.resolve()
    require(not args.output.is_relative_to(ROOT) and not args.output.is_relative_to(args.build),
            "qualification output must be outside source and native build directories")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "codex.hia.datetime-cache-differential.v1", "passed": False,
              "started_unix": time.time(), "controller": binding(Path(__file__).resolve()), "skipped": 0,
              "scope": "Native cache duration admission, date difference and both original freshness policies",
              "whole_production_crates_qualified": False, "whole_product_qualified": False, "legacy_retirement": False}
    try:
        qualify(args, report)
    except BaseException:
        report["exception"] = traceback.format_exc()
        raise
    finally:
        report["finished_unix"] = time.time()
        path = args.output / "report.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "report": binding(path)}), flush=True)


if __name__ == "__main__":
    main()
