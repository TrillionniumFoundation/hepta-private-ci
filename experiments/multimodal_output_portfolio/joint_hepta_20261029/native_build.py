"""Build the unchanged Agentd owner/runtime in a small source-bound workspace.

This adapts continuation_20261027/control/build.py without requiring its archived
lock. A full-lock dependency closure seeds Cargo's isolated resolution; the
resulting name/version/source/checksum identities are checked BEFORE compiling.
No production source or Cargo manifest is edited.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib


SOURCE_COMMIT = "a50c8974ac23c20c5174f7c3ad542a96e5652854"
CRATES = ("hepta-types", "hepta-infer-core", "hepta-neuron")
CONTROL = "experiments/multimodal_output_portfolio/continuation_20261027/control"
HOST_FILES = {
    "owner_host.rs": f"{CONTROL}/owner_host.rs",
    "events.rs": f"{CONTROL}/events.rs",
    "port.rs": f"{CONTROL}/port.rs",
    "profile.rs": f"{CONTROL}/profile.rs",
    "original_owner.rs": "codex-rs/hepta-agentd/src/neuron_runtime.rs",
    "measure.rs": "experiments/multimodal_output_portfolio/abc_next/native/measure.rs",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def package_identity(row):
    return row["name"], row["version"], row.get("source"), row.get("checksum")


def lock_subset(raw):
    """Preserve original lock entries for the three roots' dependency closure."""
    document = tomllib.loads(raw)
    packages = document["package"]
    by_name = {}
    for row in packages:
        by_name.setdefault(row["name"], []).append(row)

    def resolve(specification):
        parts = specification.split(" ", 2)
        rows = by_name.get(parts[0], [])
        if len(parts) > 1:
            rows = [row for row in rows if row["version"] == parts[1]]
        if len(parts) > 2:
            source = parts[2].removeprefix("(").removesuffix(")")
            rows = [row for row in rows if row.get("source") == source]
        if len(rows) != 1:
            raise ValueError(f"Ambiguous or absent original lock dependency: {specification}")
        return rows[0]

    pending = [resolve("codex-" + name) for name in CRATES]
    retained = set()
    while pending:
        row = pending.pop()
        identity = package_identity(row)
        if identity in retained:
            continue
        retained.add(identity)
        pending.extend(resolve(spec) for spec in row.get("dependencies", []))
    blocks = raw.split("[[package]]")
    selected = []
    for block in blocks[1:]:
        parsed = tomllib.loads("[[package]]" + block)["package"][0]
        if package_identity(parsed) in retained:
            selected.append("[[package]]" + block)
    result = blocks[0] + "".join(selected)
    if {package_identity(row) for row in tomllib.loads(result)["package"]} != retained:
        raise ValueError("Original lock closure extraction was incomplete")
    return result


def build(repository, destination, compiler=None, *, offline=False):
    repository, destination = Path(repository).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Native build destination must be new")
    subprocess.run(
        ["git", "cat-file", "-e", SOURCE_COMMIT + "^{commit}"],
        cwd=repository, check=True, capture_output=True,
    )
    destination.mkdir(parents=True)
    identities = {}

    def source_bytes(path):
        raw = subprocess.check_output(["git", "show", f"{SOURCE_COMMIT}:{path}"], cwd=repository)
        identities[path] = hashlib.sha256(raw).hexdigest()
        return raw

    for name in CRATES:
        prefix = f"codex-rs/{name}/"
        paths = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", SOURCE_COMMIT, "--", prefix],
            cwd=repository, text=True,
        ).splitlines()
        if not paths:
            raise ValueError(f"Pinned source crate absent: {name}")
        for path in paths:
            relative = Path(path).relative_to("codex-rs")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_bytes(path))
    original_lock = source_bytes("codex-rs/Cargo.lock").decode()
    locked = tomllib.loads(original_lock)["package"]
    original_identities = {package_identity(row) for row in locked}
    roots = [row for row in locked if row["name"] in {"codex-" + name for name in CRATES}]
    versions = {row["version"] for row in roots}
    if len(roots) != 3 or len(versions) != 1:
        raise ValueError("Pinned workspace crate versions are inconsistent")
    workspace = f'''[workspace]
members = ["hepta-types", "hepta-infer-core", "hepta-neuron"]
resolver = "2"
[workspace.package]
version = "{versions.pop()}"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = {{version = "=1.0.228", features = ["rc"]}}
serde_json = "=1.0.149"
sha2 = "=0.10.9"
pretty_assertions = "=1.4.1"
[workspace.lints.rust]
[profile.dev]
debug = 0
incremental = false
'''
    (destination / "Cargo.toml").write_text(workspace)
    (destination / "Cargo.lock").write_text(lock_subset(original_lock))
    examples = destination / "hepta-neuron/examples"
    examples.mkdir(exist_ok=True)
    for name, path in HOST_FILES.items():
        (examples / name).write_bytes(source_bytes(path))
    env = dict(os.environ, CARGO_TARGET_DIR=str(destination / "target"))
    if compiler is not None:
        compiler = Path(compiler).resolve()
        if not (compiler / "rustc").is_file():
            compiler = compiler / "bin"
        cargo, rustc = compiler / "cargo", compiler / "rustc"
        env["RUSTC"] = str(rustc)
    else:
        cargo, rustc = shutil.which("cargo"), shutil.which("rustc")
        if cargo is None or rustc is None:
            raise ValueError("Cargo and rustc are required")
        cargo, rustc = Path(cargo), Path(rustc)
        # Resolve a rustup driver to the selected actual toolchain so the
        # receipt hashes the compiler, not merely the rustup launcher.
        sysroot = Path(subprocess.check_output(
            [str(rustc), "--print", "sysroot"], env=env, text=True,
        ).strip())
        suffix = ".exe" if os.name == "nt" else ""
        actual_rustc, actual_cargo = sysroot / "bin" / ("rustc" + suffix), sysroot / "bin" / ("cargo" + suffix)
        if actual_rustc.is_file() and actual_cargo.is_file():
            rustc, cargo = actual_rustc, actual_cargo
        env["RUSTC"] = str(rustc)
    manifest = str(destination / "Cargo.toml")
    metadata_command = [str(cargo), "metadata", "--format-version", "1", "--manifest-path", manifest]
    if offline:
        metadata_command.append("--offline")
    metadata = subprocess.run(metadata_command, env=env, capture_output=True, text=True)
    (destination / "RESOLVE.log").write_text(metadata.stderr)
    metadata.check_returncode()
    (destination / "RESOLVED_METADATA.json").write_text(metadata.stdout)
    resolved = tomllib.loads((destination / "Cargo.lock").read_text())["package"]
    resolved_identities = {package_identity(row) for row in resolved}
    if not resolved_identities <= original_identities:
        raise ValueError("Isolated resolution introduced dependencies outside the pinned original lock")
    lock_sha = sha(destination / "Cargo.lock")
    command = [str(cargo), "build", "--locked", "-j", "1", "-p", "codex-hepta-neuron",
               "--example", "owner_host", "--manifest-path", manifest]
    if offline:
        command.append("--offline")
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    (destination / "BUILD.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    if sha(destination / "Cargo.lock") != lock_sha:
        raise ValueError("Locked compile changed dependency resolution")
    suffix = ".exe" if os.name == "nt" else ""
    binary = destination / "target/debug/examples" / ("owner_host" + suffix)
    receipt = {
        "schema": "hepta.joint-output.native-build.v1",
        "source_commit": SOURCE_COMMIT,
        "source_sha256": identities,
        "binary": str(binary), "binary_sha256": sha(binary),
        "compiler": subprocess.check_output([str(rustc), "--version"], env=env, text=True).strip(),
        "compiler_sha256": sha(rustc),
        "cargo": subprocess.check_output([str(cargo), "--version"], env=env, text=True).strip(),
        "command": command, "resolution_command": metadata_command,
        "resolved_dependencies": [list(row) for row in sorted(resolved_identities, key=str)],
        "all_dependencies_name_version_source_checksum_match": True,
        "owner_and_three_crates_unmodified": True,
        "host_sources_unmodified": True, "full_daemon_build": False,
        "lock_sha256": lock_sha,
        "repository_lock_sha256": hashlib.sha256(original_lock.encode()).hexdigest(),
        "build_log_sha256": sha(destination / "BUILD.log"),
        "resolution_log_sha256": sha(destination / "RESOLVE.log"),
    }
    (destination / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--offline", action="store_true")
    options = parser.parse_args()
    result = build(options.repository, options.destination, options.compiler, offline=options.offline)
    print(json.dumps({"binary": result["binary"], "sha256": result["binary_sha256"]}))
