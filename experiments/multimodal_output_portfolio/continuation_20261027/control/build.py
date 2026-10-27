"""Compile unchanged owner/runtime sources with a separately identified study host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(repository, destination, compiler, prior_archive):
    destination.mkdir(parents=True, exist_ok=False)
    crates = ("hepta-types", "hepta-infer-core", "hepta-neuron")
    identities = {}
    for name in crates:
        source = repository / "codex-rs" / name
        shutil.copytree(source, destination / name)
        identities.update({str(p.relative_to(repository)): sha(p) for p in source.rglob("*") if p.is_file()})
    (destination / "Cargo.toml").write_text('''[workspace]
members = ["hepta-types", "hepta-infer-core", "hepta-neuron"]
resolver = "2"
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = {version = "=1.0.228", features = ["rc"]}
serde_json = "=1.0.149"
sha2 = "=0.10.9"
pretty_assertions = "=1.4.1"
[workspace.lints.rust]
[profile.dev]
debug = 0
incremental = false
''')
    with tarfile.open(prior_archive) as archive:
        lock = archive.extractfile("neuron-feedback-run-001/Cargo.lock").read()
    (destination / "Cargo.lock").write_bytes(lock)
    examples = destination / "hepta-neuron/examples"
    examples.mkdir(exist_ok=True)
    sources = {
        "original_owner.rs": repository / "codex-rs/hepta-agentd/src/neuron_runtime.rs",
        "measure.rs": repository / "experiments/multimodal_output_portfolio/abc_next/native/measure.rs",
    }
    sources.update({p.name: p for p in Path(__file__).parent.glob("*.rs")})
    for name, source in sources.items():
        shutil.copyfile(source, examples / name)
        identities[str(source.relative_to(repository))] = sha(source)
    env = dict(os.environ, CARGO_HOME=str(destination / "cargo-home"), RUSTC=str(compiler / "rustc"))
    command = [str(compiler / "cargo"), "build", "--locked", "-j", "1", "-p", "codex-hepta-neuron",
               "--example", "owner_host", "--manifest-path", str(destination / "Cargo.toml")]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    (destination / "BUILD.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    original = tomllib.loads((repository / "codex-rs/Cargo.lock").read_text())["package"]
    resolved = tomllib.loads((destination / "Cargo.lock").read_text())["package"]
    identity = lambda row: (row["name"], row["version"], row.get("source"), row.get("checksum"))
    if not {identity(row) for row in resolved} <= {identity(row) for row in original}:
        raise ValueError("Dependency identity differs from original repository lock")
    binary = destination / "target/debug/examples/owner_host"
    receipt = {"schema": "hepta.continuation.owner-build.v1", "command": command,
        "source_sha256": identities, "binary_sha256": sha(binary), "binary": str(binary),
        "compiler": subprocess.check_output([str(compiler / "rustc"), "--version"], text=True).strip(),
        "compiler_sha256": sha(compiler / "rustc"), "lock_sha256": sha(destination / "Cargo.lock"),
        "repository_lock_sha256": sha(repository / "codex-rs/Cargo.lock"),
        "all_dependencies_name_version_source_checksum_match": True,
        "owner_and_three_crates_unmodified": True, "full_daemon_build": False,
        "build_log_sha256": sha(destination / "BUILD.log")}
    (destination / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"binary": str(binary), "sha256": sha(binary)}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("repository", "destination", "compiler", "prior-archive"):
        p.add_argument("--" + name, required=True, type=Path)
    args = p.parse_args()
    build(args.repository, args.destination, args.compiler, args.prior_archive)
