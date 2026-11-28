"""Compare native strict RFC3339 values and error kinds with original locked Chrono."""
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
from datetime_parse_cases import parsing_cases
from test_datetime_calendar import identity

ROOT = Path(__file__).resolve().parents[2]
MASK = (1 << 64) - 1


def qualify(args, report):
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    before = identity()
    contract_path = ROOT / "hia/datetime_parse_buffer_contract.json"
    contract = json.loads(contract_path.read_bytes())
    source = binding(ROOT / "hia/datetime_parse.hepta")
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
                                             args.output, contract, "hia/tests/datetime_parse_oracle")
    report["original"] = {"receipt": binding(args.output / "original-custody.json"),
                          "executable": original["executable"], "toolchain": original["toolchain"]}
    cases = parsing_cases()
    corpus = contract["differential_corpus"]
    input_path = args.output / "inputs.bin"
    raw = b"".join(struct.pack("<Q", len(case)) + case for case in cases)
    input_path.write_bytes(raw)
    require(len(cases) == corpus["total_cases"] and binding(input_path)["sha256"] == corpus["input_sha256"],
            "parser corpus differs from its complete cycle, field grids and mutations")
    observed = subprocess.run([str(executable)], input=raw, capture_output=True, timeout=60)
    output_path = args.output / "original-chrono.bin"
    output_path.write_bytes(observed.stdout)
    (args.output / "original-chrono.stderr").write_bytes(observed.stderr)
    require(observed.returncode == 0 and len(observed.stdout) == len(cases) * 64
            and binding(output_path)["sha256"] == corpus["original_output_sha256"],
            "actual original Chrono output differs or is incomplete")
    counts = Counter(row[5] for row in struct.iter_unpack("<8Q", observed.stdout))
    counts = {str(kind): count for kind, count in sorted(counts.items())}
    require(counts == corpus["original_error_kinds"], "original error-kind coverage differs")
    report.update(cases=len(cases), inputs=binding(input_path), original_output=binding(output_path),
                  original_error_kinds=counts)
    library = ctypes.CDLL(str(library_path))
    entry = library.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint64
    prefix, suffix = bytes(range(17)), bytes(range(239, 256))
    trace_hash = hashlib.sha256()
    trace_bytes, calls = 0, 0
    trace_path = args.output / "native-calls.bin.gz"
    with gzip.open(trace_path, "xb") as trace:
        def call(frame, workspace, capacity, fill, status, expected=b""):
            nonlocal calls, trace_bytes
            initial = (prefix + frame + suffix, prefix + workspace + suffix,
                       prefix + bytes([fill]) * capacity + suffix)
            source_buf, workspace_buf, output_buf = [ctypes.create_string_buffer(data, len(data)) for data in initial]
            actual = entry(ctypes.addressof(source_buf) + 17, len(frame), ctypes.addressof(output_buf) + 17,
                           capacity, ctypes.addressof(workspace_buf) + 17, len(workspace))
            calls += 1
            require(actual == status, "native status differs at call " + str(calls))
            require(source_buf.raw == initial[0] and workspace_buf.raw == initial[1], "input or guard mutation")
            wanted = initial[2] if status else prefix + expected + bytes([fill]) * (capacity - len(expected)) + suffix
            require(output_buf.raw == wanted,
                    "native value, error kind, atomic no-write, tail or guard differs at call " + str(calls))
            record = struct.pack("<6Q", len(frame), len(workspace), capacity, fill, status, len(output_buf.raw))
            record += frame + workspace + output_buf.raw
            trace.write(record)
            trace_hash.update(record)
            trace_bytes += len(record)

        for index, payload in enumerate(cases):
            frame = struct.pack("<4Q", 1, 0, len(payload), 0) + payload
            expected = observed.stdout[index * 64:(index + 1) * 64]
            for capacity in [64, 77]:
                for fill in [0, 165]:
                    call(frame, b"", capacity, fill, 0, expected)
        semantic_calls = calls
        payload = b"1970-01-01T00:00:00Z"
        good = struct.pack("<4Q", 1, 0, len(payload), 0) + payload
        for frame in [good[:n] for n in range(len(good))] + [good + b"\0" * n for n in [1, 8, 16]]:
            for capacity in [0, 63, 64, 77]:
                for fill in [0, 165]:
                    call(frame, b"", capacity, fill, 0xFFFFFFFE if capacity < 64 else 0xFFFFFFFF)
        for position, values in [(0, [0, 2, MASK]), (1, [1, 2, MASK]),
                                 (2, [0, 1, len(payload) - 1, len(payload) + 1, MASK]), (3, [1, MASK])]:
            for value in values:
                words = [1, 0, len(payload), 0]
                words[position] = value
                for capacity in [63, 64, 77]:
                    call(struct.pack("<4Q", *words) + payload, b"", capacity, 165,
                         0xFFFFFFFE if capacity < 64 else 0xFFFFFFFF)
        for workspace in [b"\0", b"\xa5" * 8, b"\0" * 64]:
            for capacity in [63, 64, 77]:
                call(good, workspace, capacity, 165, 0xFFFFFFFE if capacity < 64 else 0xFFFFFFFF)
        for capacity in range(64):
            call(good, b"", capacity, 165, 0xFFFFFFFE)
    require(calls == corpus["native_calls_required"] == len(cases) * 4 + 552,
            "native call coverage is incomplete")
    report.update(native_calls=calls, semantic_calls=semantic_calls, buffer_control_calls=calls - semantic_calls,
                  trace_bytes=trace_bytes, trace_sha256=trace_hash.hexdigest(), trace_archive=binding(trace_path))
    require(identity() == before and binding(library_path) == build["library"]
            and binding(ROOT / "hia/datetime_parse.hepta") == source, "source or native artifact changed")
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
    report = {"schema": "codex.hia.datetime-parse-differential.v1", "passed": False,
              "started_unix": time.time(), "controller": binding(Path(__file__).resolve()), "skipped": 0,
              "scope": "strict RFC3339 UTF-8 parser values and error kinds; original Chrono 0.4.43 observations",
              "production_callers_migrated": False, "relaxed_serde_parsing_qualified": False,
              "local_timezone_qualified": False, "whole_product_qualified": False, "legacy_retirement": False}
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
