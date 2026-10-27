"""Link a small C ABI against the exact already-restored native Rust crates.

Run V1 restore_native.py first on a fresh machine. This script neither downloads
nor modifies those crates; it verifies their source receipt and records all
linked compiler/dependency identities. Output must be a new directory.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

STUDY = Path(__file__).resolve().parent
V1 = STUDY.with_name("field_bridge_20261027")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--native-receipt", type=Path, required=True)
    parser.add_argument("--native-workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    compiler, workspace, out = (p.resolve() for p in (args.compiler, args.native_workspace, args.out))
    profile = json.loads((V1 / "native_reproduction/PROFILE.json").read_text())
    previous = json.loads(args.native_receipt.read_text())
    original_hashes = previous["source_sha256"]
    for name, expected in original_hashes.items():
        if sha(workspace / name) != expected:
            raise ValueError(f"Original native crate source changed: {name}")
    if previous["source_commit"] != "63f198ad85cfa2aa579032256355f446cfe793a0":
        raise ValueError("Unexpected original sparse kernel commit")
    version = subprocess.check_output([str(compiler), "--version"], text=True).strip()
    if version != profile["toolchain"]["rustc_version"]:
        raise ValueError("Compiler version differs from original exact build")
    sysroot = Path(subprocess.check_output([str(compiler), "--print", "sysroot"], text=True).strip())
    compiler_inventory = {}
    for record in profile["toolchain"]["executable_library_inventory"]:
        if record["path"] in {"bin/cargo", "bin/rustfmt"}:
            continue
        value = sha(sysroot / record["path"])
        if value != record["sha256"]:
            raise ValueError(f"Compiler/runtime bytes differ: {record['path']}")
        compiler_inventory[record["path"]] = value
    deps = workspace / "target/release/deps"
    rlibs = sorted(deps.glob("*.rlib"))
    selected = {}
    for name in ("codex_hepta_neuron", "codex_hepta_types"):
        choices = list(deps.glob(f"lib{name}-*.rlib"))
        if len(choices) != 1:
            raise ValueError(f"Need exactly one restored release rlib for {name}")
        selected[name] = choices[0]
    out.mkdir(parents=True, exist_ok=False)
    binary = out / "libhepta_field_bridge.so"
    command = [str(compiler), "--edition=2024", "--crate-type=cdylib", "--crate-name=hepta_field_bridge_ffi",
               "-C", "opt-level=3", "-C", "panic=unwind", "-C", "strip=symbols",
               "-L", f"dependency={deps}"]
    for name, path in selected.items():
        command.extend(["--extern", f"{name}={path}"])
    command.extend([str(STUDY / "native_ffi.rs"), "-o", str(binary)])
    started = time.perf_counter_ns()
    result = subprocess.run(command, capture_output=True, text=True)
    elapsed = time.perf_counter_ns() - started
    (out / "BUILD.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    for name, expected in original_hashes.items():
        if sha(workspace / name) != expected:
            raise RuntimeError("Compilation changed an original source file")
    receipt = dict(
        schema="hepta.field-bridge-v2.native-ffi-build.v1", binary=str(binary), binary_sha256=sha(binary),
        binary_bytes=binary.stat().st_size, source_sha256=sha(STUDY / "native_ffi.rs"),
        build_script_sha256=sha(__file__), compiler=version, compiler_runtime_inventory=compiler_inventory,
        original_build_receipt_sha256=sha(args.native_receipt), original_source_commit=previous["source_commit"],
        original_sparse_sha256=previous["original_sparse_sha256"], original_sources_verified=len(original_hashes),
        original_crates_unmodified=True, linked_rlib_sha256={p.name: sha(p) for p in rlibs},
        native_owner_integration=False, authority="DENY_ALL", requires_calibration=True,
        full_product_workspace_build_or_qualification=False, command=command, build_wall_ns=elapsed,
        build_log_sha256=sha(out / "BUILD.log"),
    )
    (out / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"binary": str(binary), "binary_sha256": receipt["binary_sha256"],
                      "original_sources_verified": len(original_hashes)}))


if __name__ == "__main__":
    main()
