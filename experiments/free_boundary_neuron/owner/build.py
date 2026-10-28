"""Build the original native owner with a separately identified research readout.

The three native crates and Agentd owner are copied byte for byte. Dependencies
are vendored from the repository lock, checksum checked, and built offline. This
is a source-composed research host, not a complete daemon or production build.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import tomllib
import urllib.request


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def closure(packages, roots):
    selected = {}

    def visit(name, version=None):
        candidates = [
            p
            for p in packages
            if p["name"] == name and (version is None or p["version"] == version)
        ]
        if len(candidates) != 1:
            raise ValueError(f"Ambiguous repository lock dependency: {name} {version}")
        package = candidates[0]
        key = (name, package["version"])
        if key in selected:
            return
        selected[key] = package
        for dependency in package.get("dependencies", []):
            fields = dependency.split()
            visit(fields[0], fields[1] if len(fields) > 1 else None)

    for name in roots:
        visit(name)
    return list(selected.values())


def vendor(packages, destination):
    destination.mkdir()
    for package in packages:
        if "source" not in package:
            continue
        if package["source"] != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError("Only repository-locked registry packages are allowed")
        name, version = package["name"], package["version"]
        archive = destination / f"{name}-{version}.crate"
        with urllib.request.urlopen(
            f"https://static.crates.io/crates/{name}/{name}-{version}.crate", timeout=60
        ) as response:
            archive.write_bytes(response.read())
        if sha(archive) != package["checksum"]:
            raise ValueError(f"Registry checksum mismatch: {name}")
        with tarfile.open(archive) as source:
            source.extractall(destination, filter="data")
        archive.unlink()
        directory = destination / f"{name}-{version}"
        checksums = {
            str(p.relative_to(directory)): sha(p)
            for p in directory.rglob("*")
            if p.is_file()
        }
        (directory / ".cargo-checksum.json").write_text(
            json.dumps({"files": checksums, "package": package["checksum"]})
        )


def build(repository, destination, compiler):
    destination.mkdir(parents=True, exist_ok=False)
    roots = ("codex-hepta-types", "codex-hepta-infer-core", "codex-hepta-neuron")
    packages = tomllib.loads((repository / "codex-rs/Cargo.lock").read_text())[
        "package"
    ]
    identities = {}
    for name in ("hepta-types", "hepta-infer-core", "hepta-neuron"):
        source = repository / "codex-rs" / name
        shutil.copytree(source, destination / name)
        identities.update(
            {
                str(p.relative_to(repository)): sha(p)
                for p in source.rglob("*")
                if p.is_file()
            }
        )
    (destination / "Cargo.toml").write_text("""[workspace]
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
""")
    vendor(closure(packages, roots), destination / "vendor")
    (destination / ".cargo").mkdir()
    (destination / ".cargo/config.toml").write_text(
        '[source.crates-io]\nreplace-with="vendor"\n[source.vendor]\ndirectory="vendor"\n'
    )
    examples = destination / "hepta-neuron/examples"
    examples.mkdir(exist_ok=True)
    sources = {
        "original_owner.rs": repository / "codex-rs/hepta-agentd/src/neuron_runtime.rs",
        "measure.rs": repository
        / "experiments/multimodal_output_portfolio/abc_next/native/measure.rs",
    }
    sources.update({p.name: p for p in Path(__file__).parent.glob("*.rs")})
    for name, source in sources.items():
        shutil.copyfile(source, examples / name)
        identities[str(source.relative_to(repository))] = sha(source)
    env = dict(
        os.environ,
        CARGO_HOME=str(destination / "cargo-home"),
        RUSTC=str(compiler / "rustc"),
    )
    command = [
        str(compiler / "cargo"),
        "build",
        "--offline",
        "-j",
        "1",
        "-p",
        "codex-hepta-neuron",
        "--example",
        "free_boundary_host",
    ]
    started = time.monotonic_ns()
    result = subprocess.run(
        command, cwd=destination, env=env, capture_output=True, text=True
    )
    (destination / "BUILD.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Build failed; preserved log: {destination / 'BUILD.log'}")
    resolved = tomllib.loads((destination / "Cargo.lock").read_text())["package"]

    def identity(p):
        return (p["name"], p["version"], p.get("source"), p.get("checksum"))

    if not {identity(p) for p in resolved} <= {identity(p) for p in packages}:
        raise ValueError("Dependency identity drift from original repository lock")
    binary = destination / "target/debug/examples/free_boundary_host"
    receipt = {
        "schema": "hepta.free-boundary.owner-build.v1",
        "command": command,
        "source_sha256": identities,
        "binary": str(binary),
        "binary_sha256": sha(binary),
        "compiler": subprocess.check_output(
            [str(compiler / "rustc"), "--version"], text=True
        ).strip(),
        "compiler_sha256": sha(compiler / "rustc"),
        "lock_sha256": sha(destination / "Cargo.lock"),
        "repository_lock_sha256": sha(repository / "codex-rs/Cargo.lock"),
        "all_dependencies_match_repository_lock": True,
        "native_sources_unmodified": True,
        "full_daemon_build": False,
        "build_wall_ns": time.monotonic_ns() - started,
        "build_log_sha256": sha(destination / "BUILD.log"),
    }
    (destination / "BUILD_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return receipt


def rebuild(repository, destination, compiler):
    """Reuse verified dependencies, retain each earlier build receipt and log."""
    previous = json.loads((destination / "BUILD_RECEIPT.json").read_text())
    if (
        sha(compiler / "rustc") != previous["compiler_sha256"]
        or sha(destination / "Cargo.lock") != previous["lock_sha256"]
        or sha(repository / "codex-rs/Cargo.lock") != previous["repository_lock_sha256"]
    ):
        raise ValueError("Compiler or dependency lock changed during offline rebuild")
    copies = destination / "hepta-neuron/examples"
    identities = dict(previous["source_sha256"])
    for relative, expected in identities.items():
        if relative.startswith("codex-rs/"):
            source = repository / relative
            copied = (
                copies / "original_owner.rs"
                if relative.endswith("hepta-agentd/src/neuron_runtime.rs")
                else destination / Path(relative).relative_to("codex-rs")
            )
            if sha(source) != expected or sha(copied) != expected:
                raise ValueError(f"Native source changed: {relative}")
    for source in Path(__file__).parent.glob("*.rs"):
        shutil.copyfile(source, copies / source.name)
        identities[str(source.relative_to(repository))] = sha(source)
    allocator = "experiments/multimodal_output_portfolio/abc_next/native/measure.rs"
    if (
        sha(repository / allocator) != identities[allocator]
        or sha(copies / "measure.rs") != identities[allocator]
    ):
        raise ValueError("Original allocator instrumentation changed")
    revision = len(list(destination.glob("BUILD_RECEIPT.previous.*.json")))
    shutil.copyfile(
        destination / "BUILD_RECEIPT.json",
        destination / f"BUILD_RECEIPT.previous.{revision}.json",
    )
    shutil.copyfile(
        destination / "BUILD.log", destination / f"BUILD.previous.{revision}.log"
    )
    env = dict(
        os.environ,
        CARGO_HOME=str(destination / "cargo-home"),
        RUSTC=str(compiler / "rustc"),
    )
    command = [
        str(compiler / "cargo"),
        "build",
        "--offline",
        "--locked",
        "-j",
        "1",
        "-p",
        "codex-hepta-neuron",
        "--example",
        "free_boundary_host",
    ]
    started = time.monotonic_ns()
    result = subprocess.run(
        command, cwd=destination, env=env, capture_output=True, text=True
    )
    (destination / "BUILD.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    receipt = dict(
        previous,
        command=command,
        source_sha256=identities,
        binary_sha256=sha(Path(previous["binary"])),
        build_log_sha256=sha(destination / "BUILD.log"),
        build_wall_ns=time.monotonic_ns() - started,
        build_revision=revision + 1,
    )
    (destination / "BUILD_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("repository", "destination", "compiler"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--reuse-dependencies", action="store_true")
    args = parser.parse_args()
    operation = rebuild if args.reuse_dependencies else build
    receipt = operation(
        args.repository.resolve(), args.destination.resolve(), args.compiler.resolve()
    )
    print(
        json.dumps(
            {
                "binary": receipt["binary"],
                "binary_sha256": receipt["binary_sha256"],
                "build_wall_ns": receipt["build_wall_ns"],
                "native_sources_unmodified": receipt["native_sources_unmodified"],
            },
            indent=2,
        )
    )
