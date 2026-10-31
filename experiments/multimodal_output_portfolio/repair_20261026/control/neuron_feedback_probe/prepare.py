"""Build exact checkout crates in a new, offline, isolated research workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib


CRATES = ("hepta-types", "hepta-infer-core", "hepta-neuron")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(repository, destination, compiler, cached_registry):
    repository, destination = repository.resolve(), destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    source = repository / "codex-rs"
    inventory = {}
    for crate in CRATES:
        shutil.copytree(source / crate, destination / crate)
        for path in sorted((source / crate).rglob("*")):
            if path.is_file():
                relative = path.relative_to(source)
                inventory[str(relative)] = sha(path)
                if sha(destination / relative) != inventory[str(relative)]:
                    raise ValueError("Copied native source differs")
    manifest = '''[workspace]
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
'''
    (destination / "Cargo.toml").write_text(manifest)
    example = destination / "hepta-neuron/examples/feedback_probe.rs"
    example.parent.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("native.rs"), example)
    cargo_home = destination / "cargo-home"
    shutil.copytree(cached_registry, cargo_home / "registry")
    env = dict(os.environ, CARGO_HOME=str(cargo_home), RUSTC=str(compiler / "rustc"))
    command = [str(compiler / "cargo"), "build", "--offline", "-p", "codex-hepta-neuron",
               "--example", "feedback_probe", "--manifest-path", str(destination / "Cargo.toml")]
    completed = subprocess.run(command, env=env, capture_output=True, text=True)
    (destination / "BUILD.log").write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    original = tomllib.loads((source / "Cargo.lock").read_text())["package"]
    extracted = tomllib.loads((destination / "Cargo.lock").read_text())["package"]
    key = lambda x: (x["name"], x["version"], x.get("source"), x.get("checksum"))
    allowed = {key(row) for row in original}
    if any(key(row) not in allowed for row in extracted):
        raise ValueError("Isolated build used a dependency absent from the repository lock")
    binary = destination / "target/debug/examples/feedback_probe"
    receipt = {"schema": "hepta.repair.neuron-feedback.build.v1", "command": command,
        "repository": str(repository), "source_sha256": inventory,
        "original_sparse_sha256": inventory["hepta-neuron/src/sparse.rs"],
        "original_lock_sha256": sha(source / "Cargo.lock"), "isolated_lock_sha256": sha(destination / "Cargo.lock"),
        "dependency_name_version_source_checksum_match_repository_lock": True,
        "native_probe_sha256": sha(example), "binary": str(binary), "binary_sha256": sha(binary),
        "compiler": subprocess.check_output([str(compiler / "rustc"), "--version"], text=True).strip(),
        "compiler_sha256": sha(compiler / "rustc"), "build_log_sha256": sha(destination / "BUILD.log"),
        "original_crates_unmodified": True, "native_owner_integration": False,
        "full_product_workspace_build_or_qualification": False}
    (destination / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"binary": str(binary), "source_files": len(inventory), "binary_sha256": sha(binary)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--cached-registry", type=Path, required=True)
    arguments = parser.parse_args()
    prepare(arguments.repository, arguments.destination, arguments.compiler, arguments.cached_registry)
