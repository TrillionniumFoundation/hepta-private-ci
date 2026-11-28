"""Compare native duration units with the exact original Chrono constructors."""
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
from datetime_calendar_oracle.custody import binding, compile_original, require
from duration_units_cases import duration_cases
from test_datetime_calendar import identity

ROOT = Path(__file__).resolve().parents[2]
MASK = (1 << 64) - 1


def preserve(path, data):
    with path.open("xb") as file:
        with gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as stream:
            stream.write(data)
    return {"raw_bytes": len(data), "raw_sha256": hashlib.sha256(data).hexdigest(), "archive": binding(path)}


def qualify(args, report):
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    before = identity()
    contract_path = ROOT / "hia/duration_units_buffer_contract.json"
    contract = json.loads(contract_path.read_bytes())
    source = binding(ROOT / "hia/duration_units.hepta")
    build_path = args.build / "build.json"
    build = json.loads(build_path.read_bytes())
    require(build["passed"] and build["producer"] == before and build["core_sha256"] == contract["core_sha256"],
            "native build is not bound to this clean producing tree and Core")
    require(source["sha256"] == contract["source_sha256"] and build["inputs"][0] == source,
            "native source differs from the contract or build")
    library_path = Path(build["library"]["path"]).resolve(strict=True)
    require(library_path.is_relative_to(args.build) and binding(library_path) == build["library"],
            "native library changed or escaped its build directory")
    report.update(producer=before, contract=binding(contract_path), source=source,
                  native_build=binding(build_path), library=build["library"])
    executable, original = compile_original(ROOT, args.original_lock, args.cargo, args.rustc,
                                             args.output, contract, "hia/tests/duration_units_oracle")
    report["original"] = {"receipt": binding(args.output / "original-custody.json"),
                          "executable": original["executable"], "toolchain": original["toolchain"]}
    cases = duration_cases()
    corpus = contract["differential_corpus"]
    raw = b"".join(struct.pack("<3Q", *case) for case in cases)
    report["inputs"] = preserve(args.output / "inputs.bin.gz", raw)
    require(len(cases) == corpus["total_cases"] and report["inputs"]["raw_sha256"] == corpus["input_sha256"],
            "duration unit corpus differs from the frozen constructor and numeric boundaries")
    observed = subprocess.run([str(executable)], input=raw, capture_output=True, timeout=60)
    report["original_output"] = preserve(args.output / "original-chrono.bin.gz", observed.stdout)
    (args.output / "original-chrono.stderr").write_bytes(observed.stderr)
    require(observed.returncode == 0 and len(observed.stdout) == len(cases) * 168
            and report["original_output"]["raw_sha256"] == corpus["original_output_sha256"],
            "actual original Chrono output differs or is incomplete")
    counts = Counter()
    for case, words in zip(cases, struct.iter_unpack("<21Q", observed.stdout)):
        counts[(case[0], words[1], words[10], words[12], words[17])] += 1
    counts = {",".join(map(str, key)): value for key, value in sorted(counts.items())}
    require(counts == corpus["original_result_counts"], "original constructor and nanos-option coverage differs")
    report.update(cases=len(cases), original_result_counts=counts)
    library = ctypes.CDLL(str(library_path))
    entry = library.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint64
    prefix, suffix = bytes(range(17)), bytes(range(239, 256))
    trace_hash = hashlib.sha256()
    trace_bytes, calls, semantic_calls = 0, 0, 0
    controls = {"frame_sizes": 0, "metadata": 0, "short_capacity_by_operation": 0,
                "workspace_by_operation": 0, "unused_nanoseconds": 0, "zero_arguments": 0}
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
                        "native units, atomic no-write, tail or guard differ at call " + str(calls))

            for index, (operation, value, nanos) in enumerate(cases):
                frame = struct.pack("<8Q", 1, operation, value & MASK, nanos, 0, 0, 0, 0)
                expected = observed.stdout[index * 168:(index + 1) * 168]
                for capacity in [168, 181]:
                    for fill in [0, 165]:
                        call(frame, b"", capacity, fill, 0, expected)
            semantic_calls = calls
            good = struct.pack("<8Q", 1, 0, 0, 0, 0, 0, 0, 0)
            for frame in [good[:n] for n in range(64)] + [good + b"\0" * n for n in [1, 8, 16]]:
                for capacity in [0, 167, 168, 181]:
                    for fill in [0, 165]:
                        call(frame, b"", capacity, fill, 0xFFFFFFFE if capacity < 168 else 0xFFFFFFFF)
            controls["frame_sizes"] = calls - semantic_calls
            group_start = calls
            for position, values in [(0, [0, 2, MASK]), (1, [11, MASK]),
                                     (4, [1, MASK]), (5, [1, MASK]), (6, [1, MASK]), (7, [1, MASK])]:
                for value in values:
                    words = [1, 0, 0, 0, 0, 0, 0, 0]
                    words[position] = value
                    for capacity in [167, 168, 181]:
                        call(struct.pack("<8Q", *words), b"", capacity, 165,
                             0xFFFFFFFE if capacity < 168 else 0xFFFFFFFF)
            controls["metadata"] = calls - group_start
            for operation in range(11):
                frame = struct.pack("<8Q", 1, operation, 0, 0, 0, 0, 0, 0)
                group_start = calls
                for capacity in range(168):
                    call(frame, b"", capacity, 165, 0xFFFFFFFE)
                controls["short_capacity_by_operation"] += calls - group_start
                group_start = calls
                for workspace in [b"\0", b"\xa5" * 8, b"\0" * 64]:
                    for capacity in [167, 168, 181]:
                        call(frame, workspace, capacity, 165, 0xFFFFFFFE if capacity < 168 else 0xFFFFFFFF)
                controls["workspace_by_operation"] += calls - group_start
                group_start = calls
                if operation not in (0, 9):
                    for value in [1, MASK]:
                        frame = struct.pack("<8Q", 1, operation, 0, value, 0, 0, 0, 0)
                        for capacity in [167, 168, 181]:
                            call(frame, b"", capacity, 165, 0xFFFFFFFE if capacity < 168 else 0xFFFFFFFF)
                controls["unused_nanoseconds"] += calls - group_start
            group_start = calls
            for argument in [1, MASK]:
                frame = struct.pack("<8Q", 1, 10, argument, 0, 0, 0, 0, 0)
                for capacity in [167, 168, 181]:
                    call(frame, b"", capacity, 165, 0xFFFFFFFE if capacity < 168 else 0xFFFFFFFF)
            controls["zero_arguments"] = calls - group_start
    finally:
        report.update(native_calls=calls, semantic_calls=semantic_calls, buffer_control_groups=controls,
                      trace={"raw_bytes": trace_bytes, "raw_sha256": trace_hash.hexdigest(),
                             "archive": binding(trace_path)})
    require(controls == corpus["buffer_control_groups"] == {
                "frame_sizes": 536, "metadata": 39, "short_capacity_by_operation": 1848,
                "workspace_by_operation": 99, "unused_nanoseconds": 54, "zero_arguments": 6},
            "native buffer control groups are incomplete")
    require(calls - semantic_calls == sum(controls.values()) == corpus["buffer_control_calls"] == 2582
            and calls == corpus["native_calls_required"] == len(cases) * 4 + 2582,
            "native call coverage is incomplete")
    report["buffer_control_calls"] = calls - semantic_calls
    require(identity() == before and binding(library_path) == build["library"]
            and binding(ROOT / "hia/duration_units.hepta") == source, "source or native artifact changed")
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
    report = {"schema": "codex.hia.duration-units-differential.v1", "passed": False,
              "started_unix": time.time(), "controller": binding(Path(__file__).resolve()), "skipped": 0,
              "scope": "TimeDelta constructors, integer accessors and std Duration conversion; actual original Chrono 0.4.43 APIs",
              "production_callers_migrated": False, "general_duration_arithmetic_qualified": False,
              "whole_product_qualified": False, "legacy_retirement": False}
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
