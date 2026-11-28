"""Compare three original relaxed date APIs with native HIA and guarded buffers."""
import argparse
import contextlib
import ctypes
import json
from pathlib import Path
import struct
import sys
import time
import traceback

sys.dont_write_bytecode = True
from datetime_calendar_oracle.custody import binding, compile_original, require
from datetime_relaxed_stream import EvidenceStream, original_batches
from test_datetime_calendar import identity

ROOT = Path(__file__).resolve().parents[2]
MASK = (1 << 64) - 1


def qualify(args, report):
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    before = identity()
    contract_path = ROOT / "hia/datetime_relaxed_buffer_contract.json"
    contract = json.loads(contract_path.read_bytes())
    source = binding(ROOT / "hia/datetime_relaxed.hepta")
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
                                             args.output, contract, "hia/tests/datetime_relaxed_oracle")
    report["original"] = {"receipt": binding(args.output / "original-custody.json"),
                          "executable": original["executable"], "toolchain": original["toolchain"]}
    library = ctypes.CDLL(str(library_path))
    entry = library.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint64
    prefix, suffix = bytes(range(17)), bytes(range(239, 256))
    calls, semantic_calls = 0, 0
    trace = EvidenceStream(args.output / "native-calls.bin.gz")
    report["original_stream"] = {}
    try:
        def call(frame, workspace, capacity, fill, status, expected=b""):
            nonlocal calls
            initial = (prefix + frame + suffix, prefix + workspace + suffix,
                       prefix + bytes([fill]) * capacity + suffix)
            source_buf, workspace_buf, output_buf = [ctypes.create_string_buffer(data, len(data)) for data in initial]
            actual = entry(ctypes.addressof(source_buf) + 17, len(frame), ctypes.addressof(output_buf) + 17,
                           capacity, ctypes.addressof(workspace_buf) + 17, len(workspace))
            calls += 1
            record = struct.pack("<7Q", len(frame), len(workspace), capacity, fill, status, actual, len(output_buf.raw))
            trace.write(record + frame + workspace + output_buf.raw)
            require(actual == status, "native status differs at call " + str(calls))
            require(source_buf.raw == initial[0] and workspace_buf.raw == initial[1], "input or guard mutation")
            wanted = initial[2] if status else prefix + expected + bytes([fill]) * (capacity - len(expected)) + suffix
            require(output_buf.raw == wanted,
                    "native value, error kind, atomic no-write, tail or guard differs at call " + str(calls))

        stream = original_batches(executable, args.output, report["original_stream"])
        with contextlib.closing(stream):
            for batch_index, (batch, observed) in enumerate(stream, 1):
                for index, (coverage, payload) in enumerate(batch):
                    modes = range(3) if coverage == 0 else [0]
                    for mode in modes:
                        frame = struct.pack("<4Q", 1, mode, len(payload), 0) + payload
                        expected = observed[index * 192 + mode * 64:index * 192 + (mode + 1) * 64]
                        capacities, fills = ([64, 77], [0, 165]) if coverage == 0 else ([77], [165])
                        for capacity in capacities:
                            for fill in fills:
                                call(frame, b"", capacity, fill, 0, expected)
                if batch_index % 100 == 0:
                    print(json.dumps({"original_batches": batch_index, "native_calls": calls}), flush=True)
        semantic_calls = calls
        payload = b"1970-01-01T00:00:00Z"
        good = struct.pack("<4Q", 1, 0, len(payload), 0) + payload
        for frame in [good[:n] for n in range(len(good))] + [good + b"\0" * n for n in [1, 8, 16]]:
            for capacity in [0, 63, 64, 77]:
                for fill in [0, 165]:
                    call(frame, b"", capacity, fill, 0xFFFFFFFE if capacity < 64 else 0xFFFFFFFF)
        for position, values in [(0, [0, 2, MASK]), (1, [3, MASK]),
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
        for mode in range(3):
            frame = struct.pack("<4Q", 1, mode, len(payload), 0) + payload
            for capacity in range(64):
                call(frame, b"", capacity, 165, 0xFFFFFFFE)
    finally:
        report.update(native_calls=calls, semantic_calls=semantic_calls, trace=trace.close())
    observed = report["original_stream"]
    corpus = contract["differential_corpus"]
    require(observed["complete"] and observed["total_cases"] == corpus["total_cases"]
            and observed["normal_cases"] == corpus["normal_cases"]
            and observed["unicode_cases"] == corpus["unicode_cases"] == 1112064,
            "the normal corpus or complete Unicode scalar sweep is incomplete")
    require(observed["inputs"]["raw_sha256"] == corpus["input_sha256"]
            and observed["original_output"]["raw_sha256"] == corpus["original_output_sha256"]
            and observed["original_error_kinds"] == corpus["original_error_kinds"],
            "complete original three-API observations differ from their frozen corpus")
    require(calls - semantic_calls == corpus["buffer_control_calls"] == 677
            and calls == corpus["native_calls_required"] == observed["normal_cases"] * 12 + 1112064 + 677,
            "native call coverage is incomplete")
    report.update(cases=observed["total_cases"], original_api_observations=observed["total_cases"] * 3,
                  buffer_control_calls=calls - semantic_calls)
    require(identity() == before and binding(library_path) == build["library"]
            and binding(ROOT / "hia/datetime_relaxed.hepta") == source, "source or native artifact changed")
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
    report = {"schema": "codex.hia.datetime-relaxed-differential.v1", "passed": False,
              "started_unix": time.time(), "controller": binding(Path(__file__).resolve()), "skipped": 0,
              "scope": "FixedOffset/Utc FromStr and actual Serde UTC String values; original Chrono 0.4.43",
              "production_callers_migrated": False, "json_lexical_parsing_qualified": False,
              "public_error_display_qualified": False, "local_timezone_qualified": False,
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
