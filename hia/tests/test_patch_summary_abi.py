#!/usr/bin/env python3
"""Check the native summary continuation ABI without writer callbacks.

The complete original/native public Write matrix is a separate gate. This gate
uses deliberately unaligned disjoint buffers and admits only a real full
native-selfhost build whose source, contract and artifacts match this checkout.
"""
import argparse
import ctypes
import hashlib
import itertools
import json
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = "patch_summary"
SYMBOL = "codex_hia_patch_summary"
MAX = (1 << 64) - 1
INVALID, SHORT = (1 << 32) - 1, (1 << 32) - 2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame(counts=(0, 0, 0), state=(0, 0, 0)):
    return struct.pack('<8Q', 1, *state, *counts, 0)


def response(effect, index=0, group=0, next_index=0):
    return (1, effect, index, 1, group, next_index, 0, 0)



def run_cases(native):
    def check(label, request, status=0, wanted=None, capacity=80, workspace=0):
        guard = b'\xd3' * 17
        buffers = [bytearray(guard+request+guard),
                   bytearray(guard+b'\xa5'*capacity+guard),
                   bytearray(guard+b'\x79'*workspace+guard)]
        before = [bytes(value) for value in buffers]
        views = [(ctypes.c_ubyte*len(value)).from_buffer(value) for value in buffers]
        pointers = [ctypes.addressof(view)+17 for view in views]
        assert all(pointer % 8 != 0 for pointer in pointers)
        actual = native(pointers[0],len(request),pointers[1],capacity,pointers[2],workspace)
        assert actual == status, (label,actual,status)
        assert bytes(buffers[0]) == before[0] and bytes(buffers[2]) == before[2],label
        words = None
        if status:
            assert bytes(buffers[1]) == before[1], ('error wrote output',label)
        else:
            assert buffers[1][:17] == guard and bytes(buffers[1][81:]) == before[1][81:],label
            words = struct.unpack('<8Q',buffers[1][17:81])
            assert words == wanted, (label,words,wanted)
        return {'case':label,'status':actual,'request_sha256':hashlib.sha256(request).hexdigest(),
                'response':words,'output_sha256':hashlib.sha256(buffers[1]).hexdigest()}

    records, valid = [], []
    for counts in itertools.product(range(5),repeat=3):
        selected = [(1,0,0,0)] + [
            (group+2,index,group,index+1)
            for group,count in enumerate(counts) for index in range(count)] + [(0,0,3,0)]
        state = (0,0,0)
        for step,values in enumerate(selected):
            label=f'trace-{counts}-{step}'
            request,wanted=frame(counts,state),response(*values)
            records.append(check(label,request,wanted=wanted))
            valid.append((label,request,wanted))
            state=wanted[3:6]
    for count in (1<<32,1<<63,MAX):
        counts=(count,count,count)
        for group in range(3):
            for index in (0,1,count-1,count):
                effect=group+2 if index<count else (group+3 if group<2 else 0)
                wanted=(response(effect,index,group,index+1) if index<count else
                        response(effect,0,group+1,1) if group<2 else response(0,0,3,0))
                request=frame(counts,(1,group,index));label=f'u64-{count}-{group}-{index}'
                records.append(check(label,request,wanted=wanted));valid.append((label,request,wanted))
        records.append(check(f'u64-terminal-{count}',frame(counts,(1,3,0)),wanted=response(0,0,3,0)))
    for length in range(64):
        records.append(check(f'source-short-{length}',frame()[:length],SHORT))
        records.append(check(f'output-short-{length}',frame(),SHORT,capacity=length))
    for length in (65,96,128):
        records.append(check(f'source-extra-{length}',frame()+b'x'*(length-64),INVALID))
    for length in (1,8,65):
        records.append(check(f'workspace-{length}',frame(),INVALID,workspace=length))
    for capacity in (64,65,81,129):
        records.append(check(f'output-tail-{capacity}',frame(),wanted=response(1),capacity=capacity))
    for word,values in ((0,(0,2,MAX)),(1,(2,MAX)),(2,(4,MAX)),(7,(1,MAX))):
        for value in values:
            words=list(struct.unpack('<8Q',frame()));words[word]=value
            records.append(check(f'invalid-word-{word}-{value}',struct.pack('<8Q',*words),INVALID))
    for group in range(4):
        if group:
            records.append(check(f'invalid-initial-group-{group}',frame(state=(0,group,0)),INVALID))
        for index in (1,MAX):
            records.append(check(f'invalid-continuation-index-{group}-{index}',frame(state=(1,group,index)),INVALID))
    for index in (1,MAX):
        records.append(check(f'invalid-initial-index-{index}',frame(state=(0,0,index)),INVALID))
    records.append(check('short-priority',b'',SHORT,capacity=0,workspace=1))
    def concurrent(index):
        label,request,wanted=valid[(index*31)%len(valid)]
        return check('concurrent-'+str(index)+'-'+label,request,wanted=wanted)
    with ThreadPoolExecutor(max_workers=8) as pool:
        records.extend(pool.map(concurrent,range(128)))
    assert len(records) == 1328, "the complete raw case inventory changed"
    assert sum(row["status"] != 0 for row in records) == 157
    return records


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def admit(library_dir):
    require(sys.flags.optimize == 0,
            "qualification cannot disable Python assertions")
    source = ROOT / "hia/patch_summary.hepta"
    contract_path = ROOT / "hia/patch_summary_buffer_contract.json"
    lock_path = ROOT / "hia/toolchain.json"
    driver_path = ROOT / "hia/build.py"
    helper_path = ROOT / "hia/cargo_build.rs"
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    require(build.get("schema") == "codex.hia.native-build.v1" and
            build.get("status") == "built" and
            build.get("build_mode") == "native-selfhost" and
            build.get("compiler_fixed_point") is True,
            "a genuine complete native-selfhost build is required")
    require(MODULE in build.get("modules", {}),
            "the complete native build does not contain patch_summary")
    contract = json.loads(contract_path.read_text())
    expected = {
        "schema": "codex.hia.patch-summary-buffer.v1",
        "module": MODULE, "native_entry": SYMBOL,
        "entry_profile": "borrowed-buffers-u32-v1",
        "request_bytes": 64, "output_bytes": 64, "workspace_bytes": 0,
        "revision": 1,
    }
    require(all(contract.get(key) == value for key, value in expected.items()),
            "the summary buffer contract is incompatible")
    request_names = (
        "revision", "phase", "group", "index", "added_count",
        "modified_count", "deleted_count", "reserved",
    )
    response_names = (
        "revision", "effect", "path_index", "next_phase", "next_group",
        "next_index", "reserved0", "reserved1",
    )
    for field, names in (("request", request_names), ("response", response_names)):
        require(contract.get(field) == [
            {"word": index, "name": name} for index, name in enumerate(names)
        ], "the summary " + field + " layout changed")
    require(set(contract.get("statuses", {})) == {"0", str(SHORT), str(INVALID)},
            "the summary status encoding changed")
    lock = json.loads(lock_path.read_text())
    require(build.get("toolchain") == lock and
            build.get("toolchain_lock_sha256") == sha(lock_path),
            "the build is not bound to the current toolchain lock")
    require(set(build["modules"]) == set(lock["modules"]),
            "the native build must contain the complete locked module inventory")
    require(MODULE in lock["modules"] and
            lock.get("entry_profiles", {}).get(MODULE, "borrowed-buffers-u32-v1") ==
            "borrowed-buffers-u32-v1",
            "the summary module must use the buffer entry profile")
    require(build.get("build_driver_sha256") == sha(driver_path) and
            build.get("cargo_helper_sha256") == sha(helper_path),
            "the current native build driver/helper differs from the producer")

    component = build["modules"][MODULE]
    require(component.get("source_sha256") == contract.get("source_sha256") ==
            sha(source), "stale summary source/contract/build binding")
    require(component.get("entry_profile") == "borrowed-buffers-u32-v1",
            "a typed scalar entry cannot qualify the summary buffer ABI")
    abi = component["codex_link_abi"]
    require(abi.get("symbol") == SYMBOL and
            abi.get("defined_symbols") == [SYMBOL] and
            abi.get("undefined_symbols") == [],
            "the summary archive has the wrong symbol inventory")
    artifacts = {}
    for kind, name in (
        ("library", "libcodex_hia_patch_summary.so"),
        ("archive", "libcodex_hia_patch_summary.a"),
        ("object", "patch_summary.namespaced.o"),
    ):
        path = library_dir / name
        require(abi.get(kind) == name and abi.get(kind + "_sha256") == sha(path),
                "stale summary " + kind + " binding")
        artifacts[kind] = path

    raw_object = library_dir / "patch_summary.o"
    inventory = component["object_inventory"]
    require(inventory.get("object_sha256") == sha(raw_object) and
            inventory.get("exports") == ["f0"] and
            inventory.get("undefined_symbols") == [] and
            inventory.get("external_relocations") == [] and
            inventory.get("entry_wrapper_bytes") == 78,
            "the raw summary object differs from the admitted buffer object")
    compilation = component["compilation"]
    require(compilation.get("status") == "returned" and
            compilation.get("abi_status") == 0 and
            compilation.get("source_unchanged") is True and
            compilation.get("forbidden_compiler_modules_loaded") == [] and
            compilation.get("produced_sha256") == sha(raw_object) and
            compilation.get("image_sha256") == build["compiler_sha256"] and
            compilation.get("artifact_sha256") == build["compiler_sha256"],
            "the summary object lacks the real fixed-point compilation receipt")
    generations = build["bootstrap_generations"]
    require(len(generations) == 3 and
            [entry.get("case") for entry in generations] == ["B1", "B2", "B3"],
            "all three compiler generations must be present")
    images = []
    for entry in generations:
        image_path = library_dir / "bootstrap" / (entry["case"] + ".image.bin")
        require(entry.get("status") == "returned" and
                entry.get("abi_status") == 0 and
                entry.get("source_unchanged") is True and
                entry.get("forbidden_compiler_modules_loaded") == [] and
                entry.get("produced_sha256") == build["compiler_sha256"] ==
                sha(image_path),
                "the compiler generations do not reproduce the reported fixed point")
        images.append(image_path)
    inputs = {
        str(path): sha(path) for path in (
            Path(__file__).resolve(), source, contract_path, lock_path,
            driver_path, helper_path, build_path, raw_object,
            *artifacts.values(), *images,
        )
    }
    return build, artifacts["library"], inputs


def verify(library_dir):
    build, library_path, before = admit(library_dir)
    library = ctypes.CDLL(str(library_path))
    native = getattr(library, SYMBOL)
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint64
    records = run_cases(native)
    require(all(sha(path) == digest for path, digest in before.items()),
            "a source, compiler or native artifact changed during the gate")
    return {
        "schema": "codex.hia.patch-summary-abi.v1",
        "passed": True,
        "scope": "Raw continuation ABI, selection traces and no-write boundaries; the complete original/native public Write matrix is a separate gate.",
        "native_calls": len(records),
        "error_no_write_cases": sum(row["status"] != 0 for row in records),
        "concurrent_calls": 128,
        "complete_small_count_traces": 125,
        "full_u64_aggregate_overflow_admitted": True,
        "unaligned_disjoint_buffers": True,
        "source_and_artifacts_unchanged": True,
        "compiler_sha256": build["compiler_sha256"],
        "build_report_sha256": sha(library_dir / "build.json"),
        "entry_profile": build["modules"][MODULE]["entry_profile"],
        "inputs": before,
        "records": records,
        "skipped": 0,
        "public_writer_matrix_qualified_by_this_report": False,
        "cargo_qualified_by_this_report": False,
        "whole_product_qualified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    library_dir = args.library_dir.resolve(strict=True)
    target = args.report.resolve() if args.report else None
    if target is not None:
        if target.exists() or any(
            target == root or target.is_relative_to(root)
            for root in (ROOT, library_dir)
        ):
            parser.error("report must be new and outside source/artifact directories")
    result = {
        "schema": "codex.hia.patch-summary-abi.v1", "passed": False,
        "skipped": 0, "whole_product_qualified": False,
    }
    try:
        result = verify(library_dir)
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
        print(result["error"], file=sys.stderr)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key in (
        "passed", "native_calls", "error_no_write_cases", "concurrent_calls",
        "complete_small_count_traces", "skipped", "error",
    )}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
