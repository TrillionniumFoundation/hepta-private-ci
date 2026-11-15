#!/usr/bin/env python3
"""Qualify the fixed patch-application continuation against a real complete build.

Whole-original public APIs and writer/FS behavior are a separate gate. This
script retains the exact previously executed 2790-case development ABI matrix.
"""
import argparse
import concurrent.futures
import ctypes
import hashlib
import itertools
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
MODULE, SYMBOL = "patch_application", "codex_hia_patch_application"
SHORT, INVALID = 0xFFFFFFFE, 0xFFFFFFFF
TRANSITIONS = (
    (0, 0, 0, 1, 1),
    (1, 0, 0, 4, 2),
    (0, 1, 1, 4, 2),
    (0, 1, 2, 2, 3),
    (0, 1, 3, 3, 4),
    (0, 2, 4, 8, 9),
    (0, 2, 5, 8, 10),
    (0, 3, 4, 8, 9),
    (0, 3, 5, 8, 10),
    (0, 4, 6, 5, 5),
    (0, 4, 7, 6, 6),
    (0, 5, 4, 8, 8),
    (0, 5, 5, 8, 11),
    (0, 6, 4, 7, 7),
    (0, 6, 5, 8, 11),
    (0, 7, 8, 8, 12),
    (0, 7, 9, 8, 13),
    (1, 4, 6, 5, 5),
    (1, 4, 7, 6, 6),
    (1, 5, 4, 8, 8),
    (1, 5, 5, 8, 11),
    (1, 6, 4, 7, 7),
    (1, 6, 5, 8, 11),
    (1, 7, 8, 8, 12),
    (1, 7, 9, 8, 13),
)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_cases(function, transitions):
    def call(frame, source_len=64, output_capacity=80, workspace_len=0, offset=0):
        prefix = 16 + offset
        source_raw = bytearray(b"\xB7" * (prefix + max(64, source_len) + 16))
        source_raw[prefix:prefix + 64] = struct.pack("<8Q", *frame)
        output_raw = bytearray(b"\xA3" * (prefix + output_capacity + 16))
        workspace_raw = bytearray(b"\x6D" * (prefix + workspace_len + 16))
        original = tuple(bytes(item) for item in (source_raw, output_raw, workspace_raw))
        source = (ctypes.c_ubyte * len(source_raw)).from_buffer(source_raw)
        output = (ctypes.c_ubyte * len(output_raw)).from_buffer(output_raw)
        workspace = (ctypes.c_ubyte * len(workspace_raw)).from_buffer(workspace_raw)
        status = function(ctypes.addressof(source) + prefix, source_len,
            ctypes.addressof(output) + prefix, output_capacity,
            ctypes.addressof(workspace) + prefix, workspace_len)
        selection = transitions.get(tuple(frame[1:4]))
        if source_len < 64 or output_capacity < 64:
            expected = SHORT
        elif source_len != 64 or workspace_len != 0 or frame[0] != 1 or any(frame[4:]) or selection is None:
            expected = INVALID
        else:
            expected = 0
        require(status == expected, f"status mismatch: {frame}/{source_len}/{output_capacity}/{workspace_len}")
        require(bytes(source_raw) == original[0] and bytes(workspace_raw) == original[2],
                "native wrote source/workspace")
        if status:
            require(bytes(output_raw) == original[1], "transport failure wrote output")
        else:
            phase, action = selection
            expected_output = bytearray(original[1])
            expected_output[prefix:prefix + 64] = struct.pack("<8Q", 1, frame[1], phase,
                action, frame[2], frame[3], 0, 0)
            require(output_raw == expected_output, "success wrote wrong frame or output canary")
        return status

    calls, errors = 0, 0
    def test(*args, **kwargs):
        nonlocal calls, errors
        status = call(*args, **kwargs)
        calls += 1
        errors += bool(status)

    for entry, phase, event in itertools.product(range(4), range(11), range(12)):
        test([1, entry, phase, event, 0, 0, 0, 0])
    for triple in transitions:
        for offset in range(8):
            test([1, *triple, 0, 0, 0, 0], offset=offset)
            test([1, *triple, 0, 0, 0, 0], offset=offset)  # legal deterministic replay
    large = (1 << 64) - 1
    for field in range(8):
        for value in (0, 1, 2, 8, 9, 10, 255, 1 << 32, 1 << 63, large):
            frame = [1, 0, 0, 0, 0, 0, 0, 0]
            frame[field] = value
            test(frame)
    for source_len, capacity, workspace_len in itertools.product(
            range(67), (0, 1, 63, 64, 65, 80), (0, 1, 17)):
        test([1, 0, 0, 0, 0, 0, 0, 0], source_len, capacity, workspace_len)
    for capacity in range(64):
        test([large] * 8, 65, capacity, 17)
    frames = [[1, *triple, 0, 0, 0, 0] for triple in transitions]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda index: call(frames[index % len(frames)], offset=index % 8),
                                range(512)))
    calls += len(results)
    errors += sum(bool(value) for value in results)
    require(calls == 2790 and errors == 1841, "the frozen raw ABI matrix changed")
    return {"native_calls": calls, "error_no_write_cases": errors,
            "legal_transitions": len(transitions), "concurrent_calls": 512,
            "unaligned_disjoint_buffers": True, "skipped": 0}


def admit(producer, library_dir):
    require(sys.flags.optimize == 0, "qualification cannot disable Python assertions")
    require(Path(__file__).resolve() == producer / "hia/tests/test_patch_application_abi.py",
            "raw gate must come from the actual producing checkout")
    source = producer / "hia/patch_application.hepta"
    contract_path = producer / "hia/patch_application_buffer_contract.json"
    lock_path, driver_path = producer / "hia/toolchain.json", producer / "hia/build.py"
    helper_path = producer / "hia/cargo_build.rs"
    build_path = library_dir / "build.json"
    build, lock = json.loads(build_path.read_text()), json.loads(lock_path.read_text())
    require(build.get("schema") == "codex.hia.native-build.v1" and
            build.get("status") == "built" and build.get("build_mode") == "native-selfhost"
            and build.get("compiler_fixed_point") is True,
            "a genuine complete native-selfhost build is required")
    require(build.get("toolchain") == lock and
            build.get("toolchain_lock_sha256") == sha(lock_path) and
            set(build["modules"]) == set(lock["modules"]) and MODULE in lock["modules"],
            "the complete build is not bound to the current locked module inventory")
    require(build.get("build_driver_sha256") == sha(driver_path) and
            build.get("cargo_helper_sha256") == sha(helper_path),
            "the actual native build driver/helper differs from the producer")
    contract = json.loads(contract_path.read_text())
    require(contract.get("schema") == "codex.hia.patch-application-buffer-contract.v1" and
            contract.get("revision") == 1 and contract.get("module") == MODULE and
            contract.get("symbol") == SYMBOL and contract.get("target") == "x86_64-unknown-linux-gnu",
            "the application transport contract differs")
    layout = contract["layout"]
    require(layout == {"endianness": "little", "word_bytes": 8, "source_exact_bytes": 64,
        "output_min_bytes": 64, "workspace_exact_bytes": 0,
        "request_words": ["revision=1", "entry", "phase", "event", "reserved=0",
                          "reserved=0", "reserved=0", "reserved=0"],
        "response_words": ["revision=1", "entry echo", "next_phase", "action",
                           "previous_phase echo", "event echo", "reserved=0", "reserved=0"]},
        "the exact request/response ABI layout differs")
    require(tuple(contract["transport"].get(key) for key in ("OK", "SHORT", "INVALID")) ==
            (0, SHORT, INVALID), "the transport statuses differ")
    transitions = {(row["entry"], row["phase"], row["event"]):
                   (row["next_phase"], row["action"]) for row in contract["transitions"]}
    require(len(contract["transitions"]) == 25 and transitions ==
            {tuple(row[:3]): tuple(row[3:]) for row in TRANSITIONS},
            "the exact reviewed transition table differs")
    component = build["modules"][MODULE]
    require(component.get("source_sha256") == sha(source) and
            component.get("entry_profile") == "borrowed-buffers-u32-v1" and
            lock.get("entry_profiles", {}).get(MODULE, "borrowed-buffers-u32-v1") ==
            "borrowed-buffers-u32-v1", "stale source or incompatible native entry profile")
    abi = component["codex_link_abi"]
    require(abi.get("symbol") == SYMBOL and abi.get("defined_symbols") == [SYMBOL] and
            abi.get("undefined_symbols") == [], "the namespaced object has a wrong symbol inventory")
    artifacts = {}
    for kind, name in (("library", "libcodex_hia_patch_application.so"),
                       ("archive", "libcodex_hia_patch_application.a"),
                       ("object", "patch_application.namespaced.o")):
        path = library_dir / name
        require(abi.get(kind) == name and abi.get(kind + "_sha256") == sha(path),
                "stale native artifact: " + kind)
        artifacts[kind] = path
    raw = library_dir / "patch_application.o"
    compiler_input = library_dir / "patch_application.input.bin"
    inventory, compilation = component["object_inventory"], component["compilation"]
    require(inventory.get("object_sha256") == sha(raw) and inventory.get("exports") == ["f0"]
            and inventory.get("undefined_symbols") == [] and inventory.get("external_relocations") == []
            and inventory.get("entry_wrapper_bytes") == 78,
            "the raw object differs from the admitted buffer object")
    require(compilation.get("status") == "returned" and compilation.get("abi_status") == 0
            and compilation.get("source_unchanged") is True
            and compilation.get("forbidden_compiler_modules_loaded") == []
            and compilation.get("produced_sha256") == sha(raw)
            and compilation.get("source_sha256") == sha(compiler_input)
            and compilation.get("image_sha256") == build["compiler_sha256"]
            and compilation.get("artifact_sha256") == build["compiler_sha256"],
            "the module lacks the genuine fixed-point compilation receipt")
    generations = build["bootstrap_generations"]
    require([item.get("case") for item in generations] == ["B1", "B2", "B3"],
            "the actual compiler bootstrap generations are incomplete")
    images = []
    for generation in generations:
        image = library_dir / "bootstrap" / (generation["case"] + ".image.bin")
        require(generation.get("status") == "returned" and generation.get("abi_status") == 0
                and generation.get("source_unchanged") is True
                and generation.get("forbidden_compiler_modules_loaded") == []
                and generation.get("produced_sha256") == build["compiler_sha256"] == sha(image),
                "the actual bootstrap generation does not match the fixed-point image")
        images.append(image)
    inputs = {str(path): {"bytes": path.stat().st_size, "sha256": sha(path)} for path in (
        Path(__file__).resolve(), source, contract_path, lock_path, driver_path, helper_path,
        build_path, raw, compiler_input, *artifacts.values(), *images)}
    return build, artifacts["library"], transitions, inputs


def verify(producer, library_dir):
    build, path, transitions, inputs = admit(producer, library_dir)
    library = ctypes.CDLL(str(path))
    native = getattr(library, SYMBOL)
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint64
    counts = run_cases(native, transitions)
    for name, record in inputs.items():
        require(sha(name) == record["sha256"] and Path(name).stat().st_size == record["bytes"],
                "a source, compiler, contract or native artifact changed during qualification")
    return {"schema": "codex.hia.patch-application-abi.v1", "passed": True, **counts,
        "inputs": inputs, "build_report_sha256": sha(library_dir / "build.json"),
        "compiler_sha256": build["compiler_sha256"], "source_and_artifacts_unchanged": True,
        "scope": "Raw fixed continuation ABI and full source/artifact build binding. Full original public API, writer, async and filesystem behavior are separately qualified.",
        "public_original_qualified": False, "cargo_qualified": False,
        "whole_product_qualified": False, "legacy_retirement_qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, default=ROOT)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    producer, library = args.producer.resolve(strict=True), args.library_dir.resolve(strict=True)
    target = args.report.resolve()
    require(not target.exists() and not any(target == root or target.is_relative_to(root)
            for root in (producer, library)), "report must be new and outside source/artifact directories")
    result = {"schema": "codex.hia.patch-application-abi.v1", "passed": False,
              "whole_product_qualified": False, "legacy_retirement_qualified": False}
    try:
        result = verify(producer, library)
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
        print(result["error"], file=sys.stderr)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "native_calls", "error_no_write_cases",
        "concurrent_calls", "legal_transitions", "error") if key in result}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
