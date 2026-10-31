"""Restore and build the exact pinned native bridge in a new configurable directory.

No scientific experiment runs here. Optional --run-controls-tests executes only
the six small readout/native integration tests. The build is always offline and
locked; explicit preparation may download checksum-pinned source dependencies.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.request

STUDY = Path(__file__).resolve().parent
PROFILE_PATH = STUDY / "native_reproduction/PROFILE.json"
PROFILE = json.loads(PROFILE_PATH.read_text())
CRATES = ("hepta-types", "hepta-infer-core", "hepta-neuron")


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("Pinned profile contains an unsafe relative path")
    return Path(*path.parts)


def verify_profile():
    if PROFILE["schema"] != "hepta.field-bridge.native-reproduction-profile.v1":
        raise ValueError("Unknown native reproduction profile")
    if hashlib.sha256(PROFILE["isolated_lock_text"].encode()).hexdigest() != PROFILE["isolated_lock_sha256"]:
        raise ValueError("Embedded reduced lock hash mismatch")
    if tomllib.loads(PROFILE["isolated_lock_text"])["package"] != PROFILE["packages"]:
        raise ValueError("Embedded package identities differ from the exact lock")
    for name, expected in PROFILE["study_source_sha256"].items():
        if sha(STUDY / relative_path(name)) != expected:
            raise ValueError(f"Study native source changed: {name}")
    source_paths = [row["path"] for row in PROFILE["source_files"]]
    if len(source_paths) != len(set(source_paths)):
        raise ValueError("Duplicate pinned source path")
    for path in source_paths:
        relative_path(path)


def cached_download(url, expected, cache, offline):
    target = cache / expected
    if target.is_file() and sha(target) == expected:
        return target
    if offline:
        raise RuntimeError(f"Offline cache lacks pinned bytes for {url}")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cache / (expected + ".partial")
    with urllib.request.urlopen(url, timeout=120) as incoming, temporary.open("wb") as output:
        while chunk := incoming.read(1024 * 1024):
            output.write(chunk)
    if sha(temporary) != expected:
        temporary.unlink()
        raise ValueError(f"Downloaded source checksum mismatch: {url}")
    temporary.replace(target)
    return target


def restore_sources(destination, source_root, cache, offline):
    source = destination / "source"

    def restore(row):
        relative = relative_path(row["path"])
        target = source / relative
        candidate = source_root / relative if source_root is not None else None
        if candidate is not None and candidate.is_file():
            incoming = candidate
        else:
            url = f"https://raw.githubusercontent.com/{PROFILE['repository']}/{PROFILE['commit']}/{row['path']}"
            incoming = cached_download(url, row["sha256"], cache, offline)
        if sha(incoming) != row["sha256"]:
            raise ValueError(f"Source checkout differs from the frozen pin: {row['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(incoming, target)
        raw = target.read_bytes()
        git_blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if git_blob != row["sha"] or len(raw) != row["bytes"]:
            raise ValueError(f"Pinned Git blob identity mismatch: {row['path']}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(restore, PROFILE["source_files"]))
    original_lock = tomllib.loads((source / "codex-rs/Cargo.lock").read_text())["package"]
    identity = lambda row: (row["name"], row["version"], row.get("source"), row.get("checksum"))
    allowed = {identity(row) for row in original_lock}
    if any(identity(row) not in allowed for row in PROFILE["packages"]):
        raise ValueError("Reduced lock contains an identity absent from the original repository lock")
    return source


def restore_toolchain(destination, supplied_bin, cache, offline):
    if supplied_bin is not None:
        toolchain = supplied_bin.parent
    else:
        toolchain = destination / "toolchain"
        for record in PROFILE["toolchain"]["components"]:
            archive = cached_download(record["url"], record["sha256"], cache, offline)
            stem = Path(record["url"]).name.removesuffix(".tar.xz")
            unpacked = destination / "toolchain-installers" / stem
            with tarfile.open(archive, "r:xz") as package:
                package.extractall(unpacked.parent, filter="data")
            command = ["sh", str(unpacked / "install.sh"), f"--prefix={toolchain}", "--disable-ldconfig"]
            completed = subprocess.run(command, capture_output=True, text=True)
            (destination / f"INSTALL_{record['component']}.log").write_text(completed.stdout + completed.stderr)
            completed.check_returncode()
    for row in PROFILE["toolchain"]["executable_library_inventory"]:
        if sha(toolchain / relative_path(row["path"])) != row["sha256"]:
            raise ValueError(f"Toolchain executable/library mismatch: {row['path']}")
    actual = subprocess.check_output([str(toolchain / "bin/rustc"), "--version"], text=True).strip()
    if actual != PROFILE["toolchain"]["rustc_version"]:
        raise ValueError("Toolchain version does not match the frozen profile")
    return toolchain / "bin"


def restore_vendor(destination, cache, offline):
    vendor = destination / "vendor"
    vendor.mkdir()

    def restore(record):
        name, version = record["name"], record["version"]
        url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
        archive = cached_download(url, record["checksum"], cache, offline)
        with tarfile.open(archive, "r:gz") as package:
            package.extractall(vendor, filter="data")
        crate = vendor / f"{name}-{version}"
        if not crate.is_dir():
            raise ValueError(f"Downloaded crate has unexpected root: {name}")
        checksums = {}
        for file in sorted(crate.rglob("*")):
            if file.is_symlink():
                raise ValueError("Pinned vendor package unexpectedly contains a symbolic link")
            if file.is_file() and file.name != ".cargo-checksum.json":
                checksums[file.relative_to(crate).as_posix()] = sha(file)
        (crate / ".cargo-checksum.json").write_text(json.dumps({"files": checksums, "package": record["checksum"]}))

    registry_packages = [row for row in PROFILE["packages"] if "checksum" in row]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(restore, registry_packages))
    return vendor


def build(destination, source, compiler, vendor):
    workspace = destination / "build"
    workspace.mkdir()
    source_inventory = {}
    for crate in CRATES:
        shutil.copytree(source / "codex-rs" / crate, workspace / crate)
    for row in PROFILE["source_files"]:
        relative = PurePosixPath(row["path"])
        if len(relative.parts) > 2 and relative.parts[0] == "codex-rs" and relative.parts[1] in CRATES:
            path = relative_path(str(relative.relative_to("codex-rs")))
            if sha(workspace / path) != row["sha256"]:
                raise ValueError("Original crate changed during isolated copy")
            source_inventory[path.as_posix()] = row["sha256"]
    (workspace / "Cargo.toml").write_text(PROFILE["workspace_manifest"])
    (workspace / "Cargo.lock").write_text(PROFILE["isolated_lock_text"])
    config_dir = workspace / ".cargo"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[source.crates-io]\nreplace-with = "vendored-sources"\n'
        '[source.vendored-sources]\ndirectory = ' + json.dumps(str(vendor)) + '\n')
    example = workspace / "hepta-neuron/examples/parameter_field_bridge.rs"
    example.parent.mkdir()
    shutil.copyfile(STUDY / "bridge_probe.rs", example)
    env = dict(os.environ, CARGO_HOME=str(destination / "cargo-home"), RUSTC=str(compiler / "rustc"))
    command = [str(compiler / "cargo"), "build", "--offline", "--locked", "--release",
               "-p", "codex-hepta-neuron", "--example", "parameter_field_bridge"]
    started = time.perf_counter_ns()
    completed = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True)
    elapsed = time.perf_counter_ns() - started
    (destination / "BUILD.log").write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    if sha(workspace / "Cargo.lock") != PROFILE["isolated_lock_sha256"]:
        raise ValueError("Offline locked compilation changed the package lock")
    for path, expected in source_inventory.items():
        if sha(workspace / path) != expected:
            raise ValueError("Compilation changed an original crate")
    binary = workspace / "target/release/examples/parameter_field_bridge"
    reference = json.loads((STUDY / "native_reproduction/REFERENCE_BUILD.json").read_text())
    receipt = dict(
        schema="hepta.field-bridge.native-restoration.v1", binary=str(binary), binary_sha256=sha(binary),
        command=command, build_wall_ns=elapsed, profile_sha256=sha(PROFILE_PATH),
        source_commit=PROFILE["commit"], source_repository=PROFILE["repository"],
        original_source_file_count=len(source_inventory), source_sha256=source_inventory,
        original_sparse_sha256=source_inventory["hepta-neuron/src/sparse.rs"],
        original_crates_unmodified=True, native_owner_integration=False,
        full_product_workspace_build_or_qualification=False,
        isolated_lock_sha256=sha(workspace / "Cargo.lock"),
        dependency_name_version_source_checksum_match_repository_lock=True,
        compiler=PROFILE["toolchain"]["rustc_version"], compiler_runtime_inventory_verified=True,
        native_probe_sha256=sha(example), python_wrapper_sha256=sha(STUDY / "native_bridge.py"),
        build_log_sha256=sha(destination / "BUILD.log"),
        reference_binary_sha256=reference["binary_sha256"],
        rebuilt_binary_matches_reference=sha(binary) == reference["binary_sha256"],
        bit_identical_binary_across_paths_and_linkers_claimed=False,
    )
    path = destination / "BUILD_RECEIPT.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, help="New directory; never overwrite an existing restoration")
    parser.add_argument("--source-root", type=Path, help="Optional checkout root with byte-identical pinned source")
    parser.add_argument("--toolchain-bin", type=Path, help="Optional exact Rust 1.90.0 bin directory")
    parser.add_argument("--cache-dir", type=Path, help="Reusable checksum-addressed download cache")
    parser.add_argument("--offline", action="store_true", help="No downloads; require all pinned bytes already available")
    parser.add_argument("--verify-only", action="store_true", help="Validate packaged source/lock bindings without build or download")
    parser.add_argument("--run-controls-tests", action="store_true", help="Run only the small controls tests after building")
    args = parser.parse_args()
    verify_profile()
    if args.verify_only:
        print(json.dumps({"packaged_profile_valid": True, "source_commit": PROFILE["commit"],
                          "source_files": PROFILE["crate_file_count"], "resolved_packages": len(PROFILE["packages"])}))
        return
    if args.destination is None:
        parser.error("--destination is required unless --verify-only is selected")
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise RuntimeError("This frozen toolchain profile targets x86_64 Linux only")
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    cache = args.cache_dir.resolve() if args.cache_dir is not None else destination / "download-cache"
    source_root = args.source_root.resolve() if args.source_root is not None else None
    supplied_bin = args.toolchain_bin.resolve() if args.toolchain_bin is not None else None
    source = restore_sources(destination, source_root, cache, args.offline)
    compiler = restore_toolchain(destination, supplied_bin, cache, args.offline)
    vendor = restore_vendor(destination, cache, args.offline)
    receipt = build(destination, source, compiler, vendor)
    if args.run_controls_tests:
        command = [sys.executable, "-m", "experiments.multimodal_output_portfolio.field_bridge_20261027.controls_tests",
                   "--native-build-receipt", str(receipt), "-v"]
        result = subprocess.run(command, cwd=STUDY.parents[2], capture_output=True, text=True)
        (destination / "CONTROLS_TESTS.log").write_text(result.stdout + result.stderr)
        result.check_returncode()
    print(json.dumps({"build_receipt": str(receipt), "scientific_experiment_run": False}))


if __name__ == "__main__":
    main()
