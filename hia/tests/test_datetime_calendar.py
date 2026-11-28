"""Compare the real HIA calendar image against the exact original Chrono constructor."""
import argparse
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

ROOT = Path(__file__).resolve().parents[2]
MASK = (1 << 64) - 1


def constructor_cases():
    cases = []
    for day in range(146097):
        seconds = (day - 719468) * 86400 + (day * 7919) % 86400
        nanos = [0, 123, 999999999][day % 3]
        if seconds % 60 == 59 and day % 7 == 0:
            nanos += 1000000000
        cases.append((seconds, nanos))
    minimum, maximum = -8334601228800, 8210266876799
    seed = 0x53AC0192D3E47856
    for _ in range(20000):
        seed = (seed * 6364136223846793005 + 1442695040888963407) & MASK
        seconds = minimum + seed % (maximum - minimum + 1)
        nanos = [0, 1, 999999, 1000000, 999999999, 1000000000, 1999999999,
                 2000000000, 4294967295, 1 << 32, MASK][seed % 11]
        cases.append((seconds, nanos))
    for seconds in [-(1 << 63), minimum - 1, minimum, minimum + 1, -86401, -86400, -61, -60,
                    -59, -2, -1, 0, 1, 58, 59, 60, 61, 86399, 86400, maximum - 1, maximum,
                    maximum + 1, (1 << 63) - 1]:
        for nanos in [0, 1, 999999999, 1000000000, 1000000001, 1999999999,
                      2000000000, 4294967295, 1 << 32, MASK]:
            cases.append((seconds, nanos))
    return cases


def identity():
    git = lambda *args: subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()
    require(not git("status", "--porcelain", "--untracked-files=all"), "producing checkout is dirty")
    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}")}


def qualify(args, report):
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    before = identity()
    contract_path = ROOT / "hia/datetime_calendar_buffer_contract.json"
    contract = json.loads(contract_path.read_bytes())
    source = binding(ROOT / "hia/datetime_calendar.hepta")
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
                                             args.output, contract)
    report["original"] = {"receipt": binding(args.output / "original-custody.json"),
                          "executable": original["executable"], "toolchain": original["toolchain"]}
    cases = constructor_cases()
    corpus = contract["differential_corpus"]
    raw = b"".join(struct.pack("<qQ", *case) for case in cases)
    input_path = args.output / "inputs.bin"
    input_path.write_bytes(raw)
    require(len(cases) == corpus["total_constructor_cases"] and binding(input_path)["sha256"] == corpus["input_sha256"],
            "constructor corpus differs from the specified complete cycle and boundaries")
    observed = subprocess.run([str(executable)], input=raw, capture_output=True, timeout=30)
    output_path = args.output / "original-chrono.bin"
    output_path.write_bytes(observed.stdout)
    (args.output / "original-chrono.stderr").write_bytes(observed.stderr)
    require(observed.returncode == 0 and len(observed.stdout) == len(cases) * 64
            and binding(output_path)["sha256"] == corpus["original_output_sha256"],
            "actual original Chrono output differs or is incomplete")
    report.update(cases=len(cases), inputs=binding(input_path), original_output=binding(output_path))
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
            require(output_buf.raw == wanted, "native result, atomic no-write, tail or guard differs at call " + str(calls))
            record = struct.pack("<6Q", len(frame), len(workspace), capacity, fill, status, len(output_buf.raw))
            record += frame + workspace + output_buf.raw
            trace.write(record)
            trace_hash.update(record)
            trace_bytes += len(record)

        for index, (seconds, nanos) in enumerate(cases):
            frame = struct.pack("<8Q", 1, 0, seconds & MASK, nanos, 0, 0, 0, 0)
            expected = observed.stdout[index * 64:(index + 1) * 64]
            for capacity in [64, 77]:
                for fill in [0, 165]:
                    call(frame, b"", capacity, fill, 0, expected)
        good = struct.pack("<8Q", 1, 0, 0, 0, 0, 0, 0, 0)
        for frame in [good[:n] for n in range(64)] + [good + b"\0" * n for n in [1, 8, 16]]:
            for capacity in [0, 63, 64, 77]:
                for fill in [0, 165]:
                    call(frame, b"", capacity, fill, 0xFFFFFFFE if capacity < 64 else 0xFFFFFFFF)
        for position in [0, 1, 4, 5, 6, 7]:
            for value in [2, MASK]:
                words = [1, 0, 0, 0, 0, 0, 0, 0]
                words[position] = value
                for capacity in [63, 64, 77]:
                    call(struct.pack("<8Q", *words), b"", capacity, 165,
                         0xFFFFFFFE if capacity < 64 else 0xFFFFFFFF)
        for workspace in [b"\0", b"\xa5" * 8, b"\0" * 64]:
            for capacity in [63, 64, 77]:
                call(good, workspace, capacity, 165, 0xFFFFFFFE if capacity < 64 else 0xFFFFFFFF)
        for capacity in range(64):
            call(good, b"", capacity, 165, 0xFFFFFFFE)
    require(calls == 665953, "native call coverage is incomplete")
    report.update(native_calls=calls, trace_bytes=trace_bytes, trace_sha256=trace_hash.hexdigest(),
                  trace_archive=binding(trace_path))
    require(identity() == before and binding(library_path) == build["library"]
            and binding(ROOT / "hia/datetime_calendar.hepta") == source, "source or native artifact changed")
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
    report = {"schema": "codex.hia.datetime-calendar-differential.v1", "passed": False,
              "started_unix": time.time(), "controller": binding(Path(__file__).resolve()), "skipped": 0,
              "scope": "UTC constructor and Gregorian calendar component; original Chrono 0.4.43 API observations",
              "production_callers_migrated": False, "rfc3339_serde_local_qualified": False,
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
