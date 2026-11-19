#!/usr/bin/env python3
"""Compile the independent example-validation candidate with the pinned B3 HIA compiler.

This is an *actual native machine-code/borrowed-buffer* gate, separate from the
source-only interpreter. It is not an installed Codex caller or the original
Rust owner's public differential test and must never be credited as either.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import sys

from example_validation_source_vm import encode
from test_example_validation_response_integrity import expected

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "hia/example_validation_continuation.hepta"
BLOB_SHA = "1edde1f9bae629f8419d2aeb27677883cbea0da8"
GUARD = bytes(range(1, 34))
INVALID = 0xFFFFFFFF
SHORT = 0xFFFFFFFE
MAX = (1 << 64) - 1
SEED = 0x4558414D504C453138


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def pin_source():
    raw = SOURCE.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(blob == BLOB_SHA, "example18 source is not the pinned original")
    return raw


def compile_candidate(hepta, native, output, record):
    sys.path.insert(0, str(hepta))
    sys.path.insert(0, str(ROOT / "hia"))
    from hepta.hia_agent_assembly import assemble_program
    from tools.qualify_hia_selfhost import compile_stage, inspect_selfhost_object
    from build import selfhost_object_source

    source = pin_source()
    checked = assemble_program(source)
    program = checked.as_dict()
    functions = program["functions"]
    require(len(functions) == 1 and functions[0]["name"] == "f0", "unexpected HIA functions")
    require([v["type"] for v in functions[0]["params"]] == ["readbuf", "mutbuf", "mutbuf"]
            and functions[0]["returns"] == ["u32"]
            and program.get("exports", []) == [], "unexpected buffer ABI")
    build_path = native / "build.json"
    build_bytes = build_path.read_bytes()
    build = json.loads(build_bytes)
    require(build.get("status") == "built" and build.get("build_mode") == "native-selfhost"
            and build.get("compiler_fixed_point") is True
            and len(build.get("bootstrap_generations", [])) == 3,
            "predecessor is not the actual three-generation native build")
    fixed = build["compiler_sha256"]
    for gen in (1, 2, 3):
        image = native / "bootstrap" / f"B{gen}.image.bin"
        require(sha(image.read_bytes()) == fixed, f"B{gen} compiler differs from fixed point")
    b3 = native / "bootstrap/B3.image.bin"
    transformed = selfhost_object_source(source, program)
    obj, receipt = compile_stage(output, "example18-b3", b3, transformed, output_extension=".o")
    inspection = inspect_selfhost_object(obj.read_bytes())
    library = output / "libexample18-b3.so"
    command = ["ld", "-m", "elf_x86_64", "-shared", "-z", "defs", "-z", "noexecstack",
               "-z", "relro", "-z", "now", "--build-id=none", str(obj), "-o", str(library)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    symbols = subprocess.run(["nm", "-D", "--defined-only", str(library)],
                             check=True, capture_output=True, text=True, timeout=30).stdout
    defined = [line.split()[-1] for line in symbols.splitlines() if line.strip()]
    require(defined == ["f0"], "compiled candidate must export only f0")
    record["compilation"] = {
        "candidate_source_sha256": sha(source), "candidate_core_sha256": checked.sha256,
        "transformed_source_sha256": sha(transformed),
        "predecessor_build_sha256": sha(build_bytes), "compiler_b3_sha256": fixed,
        "compiler_receipt": receipt, "object_inspection": inspection,
        "object_sha256": sha(obj.read_bytes()), "shared_sha256": sha(library.read_bytes()),
        "link_command": command, "exported_symbols": defined,
    }
    require(SOURCE.read_bytes() == source and sha(b3.read_bytes()) == fixed,
            "native source or compiler changed during compilation")
    return library


class BorrowedNative:
    def __init__(self, library):
        self.image = ctypes.CDLL(str(library))
        self.f0 = self.image.f0
        self.f0.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.f0.restype = ctypes.c_uint64

    def call(self, source, capacity=40, workspace=b""):
        require(0 <= capacity <= 40 and len(workspace) <= 1, "unadmitted live buffer size")
        buffers = [bytearray(GUARD + value + GUARD) for value in
                   (source, b"\xa5" * capacity, workspace)]
        before = [bytes(item) for item in buffers]
        views = [(ctypes.c_ubyte * len(item)).from_buffer(item) for item in buffers]
        ptrs = [ctypes.cast(ctypes.byref(item, len(GUARD)), ctypes.c_void_p) for item in views]
        ret = self.f0(ptrs[0], len(source), ptrs[1], capacity, ptrs[2], len(workspace))
        require(ret <= 0xFFFFFFFF, "foreign entry returned nonzero high word")
        require(bytes(buffers[0]) == before[0] and bytes(buffers[2]) == before[2],
                "source/workspace/guards mutated")
        require(buffers[1][:len(GUARD)] == GUARD and buffers[1][-len(GUARD):] == GUARD,
                "output guard mutated")
        return ret, bytes(buffers[1][len(GUARD):-len(GUARD)])


def check(native, mode, total, index, misses, hit, *, source=None, capacity=40, workspace=b""):
    data = encode(mode, total, index, misses, hit) if source is None else source
    truth = expected(mode, total, index, misses, hit) if source is None else None
    if source is None and capacity >= 32 and not workspace:
        status = 0 if truth is not None else INVALID
    elif source is None and not workspace and capacity < 32:
        status = SHORT
    else:
        status = INVALID
    actual, result = native.call(data, capacity=capacity, workspace=workspace)
    wanted = bytearray(b"\xa5" * capacity)
    if status == 0:
        wanted[:32] = struct.pack("<4Q", *truth)
    require(actual == status and result == bytes(wanted),
            f"native mismatch: mode={mode} total={total} index={index} "
            f"misses={misses} hit={hit} length={len(data)} capacity={capacity} "
            f"workspace={len(workspace)} status={actual}/{status}")


def exercise(native, report):
    count = 0
    for mode in (0, 1):
        check(native, mode, 0, 0, 0, 0)
        count += 1
        for total in range(1, 18):
            for index in range(total):
                for misses in (range(index + 1) if mode else (0,)):
                    for hit in (0, 1):
                        check(native, mode, total, index, misses, hit)
                        count += 1
    report["reachable_native_calls"] = count
    rng = random.Random(SEED)
    invalid = 0
    for _ in range(4096):
        mode, total, index, misses, hit = (rng.randrange(4), rng.randrange(24),
                                           rng.randrange(25), rng.randrange(25), rng.randrange(4))
        if expected(mode, total, index, misses, hit) is None:
            check(native, mode, total, index, misses, hit)
            invalid += 1
    require(invalid >= 3500, "invalid generator insufficiently adversarial")
    report["invalid_native_calls"] = invalid
    for raw in (b"", b"x", encode(1, 2, 0, 0, 0)[:-1],
                encode(1, 2, 0, 0, 0) + b"\0", encode(1, 2, 0, 0, 0, version=2)):
        check(native, 1, 2, 0, 0, 0, source=raw)
    for capacity in (0, 1, 31):
        check(native, 1, 2, 0, 0, 1, capacity=capacity)
    check(native, 1, 2, 0, 0, 1, workspace=b"x")
    report["malformed_capacity_workspace_native_calls"] = 9
    full = MAX
    for mode, index, misses, hit in ((0, full - 1, 0, 1), (0, full - 1, 0, 0),
                                     (1, full - 1, full - 2, 1), (1, full - 1, full - 2, 0)):
        check(native, mode, full, index, misses, hit)
    report["full_u64_boundary_calls"] = 4

    def worker(identifier):
        local = random.Random(SEED + identifier)
        for _ in range(256):
            total = local.randrange(1, 20)
            index = local.randrange(total)
            mode = local.randrange(2)
            misses = local.randrange(index + 1) if mode else 0
            check(native, mode, total, index, misses, local.randrange(2))
        return 256

    with ThreadPoolExecutor(max_workers=8) as pool:
        report["concurrent_native_calls"] = sum(pool.map(worker, range(8)))
    report["concurrent_workers"] = 8
    report["native_calls_checked"] = sum(report[k] for k in (
        "reachable_native_calls", "invalid_native_calls", "malformed_capacity_workspace_native_calls",
        "full_u64_boundary_calls", "concurrent_native_calls"))
    report["seed"] = str(SEED)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hepta-root", required=True, type=Path)
    p.add_argument("--native-dir", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    hepta = args.hepta_root.resolve(strict=True)
    native = args.native_dir.resolve(strict=True)
    require(subprocess.run(["git", "-C", str(hepta), "rev-parse", "HEAD"],
                           check=True, capture_output=True, text=True).stdout.strip()
            == json.loads((ROOT / "hia/toolchain.json").read_bytes())["revision"],
            "Hepta checkout not pinned to the exact compiler revision")
    require(not subprocess.run(["git", "-C", str(hepta), "status", "--porcelain"],
                               check=True, capture_output=True, text=True).stdout.strip(),
            "Hepta checkout contains modifications")
    output = args.output_dir.resolve()
    require(ROOT not in output.parents and output != ROOT and not output.exists(),
            "native test output must be a fresh directory outside the source checkout")
    output.mkdir(parents=True)
    record = {"schema": "codex.hia.example18.native-candidate.v1", "passed": False,
              "scope": "B3 native candidate ABI; not original Rust FFI or installed Codex",
              "source_blob": BLOB_SHA, "native_calls_checked": 0}
    try:
        library = compile_candidate(hepta, native, output, record)
        exercise(BorrowedNative(library), record)
        require(SOURCE.read_bytes() == pin_source(), "HIA source changed during probes")
        record["passed"] = True
    except BaseException as error:
        record["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        args.report.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")


if __name__ == "__main__":
    main()
