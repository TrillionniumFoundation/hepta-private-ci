"""Build unchanged pinned native sources in an isolated workspace, with exact crates.

Only generated build manifests omit test-only dependencies. Every compiled native
Rust source is byte-identical to the pinned repository commit. Dependencies are
verified against the original Cargo.lock, even when reused from local caches.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tarfile
import time
import tomllib
import urllib.request

BASE = "5898cd8b0f724c3152b6cc52856721f72e5e08be"
CRATES = [
    "hepta-types",
    "hepta-infer-core",
    "hepta-neuron",
    "hepta-contracts",
    "hepta-ndu",
]
EXTERNAL = {
    "serde": "1.0.228",
    "serde_json": "1.0.149",
    "sha2": "0.10.9",
    "ed25519-dalek": "2.2.0",
    "rustix": "1.1.4",
    "zeroize": "1.8.2",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_bytes(repository, path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=repository)


def registry_closure(packages):
    found = {}

    def visit(name, version=None):
        choices = [
            p
            for p in packages
            if p["name"] == name and (version is None or p["version"] == version)
        ]
        if len(choices) != 1:
            raise ValueError(f"Ambiguous original dependency {name} {version}")
        p = choices[0]
        key = (name, p["version"])
        if key in found:
            return
        if p.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError(f"Non-registry external dependency: {key}")
        found[key] = p
        for dependency in p.get("dependencies", []):
            fields = dependency.split()
            visit(fields[0], fields[1] if len(fields) > 1 else None)

    for name, version in EXTERNAL.items():
        visit(name, version)
    return list(found.values())


def verified_vendor(packages, destination, caches):
    destination.mkdir()
    for package in packages:
        name = f"{package['name']}-{package['version']}"
        target = destination / name
        copied = False
        for cache in caches:
            directory = cache / name
            checksum_file = directory / ".cargo-checksum.json"
            if not checksum_file.exists():
                continue
            sums = json.loads(checksum_file.read_text())
            if sums.get("package") != package["checksum"] or not sums.get("files"):
                continue
            for rel, digest in sums["files"].items():
                if sha((directory / rel).read_bytes()) != digest:
                    raise ValueError(f"Cached dependency source changed: {name}/{rel}")
            shutil.copytree(directory, target)
            copied = True
            break
        if copied:
            continue
        archive = destination / f"{name}.crate"
        url = f"https://static.crates.io/crates/{package['name']}/{name}.crate"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive.write_bytes(response.read())
        if sha(archive.read_bytes()) != package["checksum"]:
            raise ValueError(f"Registry archive checksum mismatch: {name}")
        with tarfile.open(archive) as tar:
            tar.extractall(destination, filter="data")
        archive.unlink()
        sums = {
            str(p.relative_to(target)): sha(p.read_bytes())
            for p in target.rglob("*")
            if p.is_file()
        }
        (target / ".cargo-checksum.json").write_text(
            json.dumps({"package": package["checksum"], "files": sums})
        )


def build(repository, destination, compiler, caches):
    destination.mkdir(parents=True, exist_ok=False)
    source_hashes = {}
    generated_manifests = {}
    for name in CRATES:
        tree = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", BASE, f"codex-rs/{name}"],
            cwd=repository,
            text=True,
        ).splitlines()
        for rel in tree:
            data = git_bytes(repository, rel)
            source_hashes[rel] = sha(data)
            target = destination / Path(rel).relative_to("codex-rs")
            target.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith("Cargo.toml"):
                original = data.decode()
                data = re.sub(
                    r"(?ms)^\[dev-dependencies\].*?(?=^\[|\Z)", "", original
                ).encode()
                generated_manifests[rel] = {
                    "original_sha256": source_hashes[rel],
                    "build_sha256": sha(data),
                    "change": "omit test-only dependency table for this non-test research executable",
                }
            target.write_bytes(data)
    owner_rel = "codex-rs/hepta-agentd/src/neuron_runtime.rs"
    owner = git_bytes(repository, owner_rel)
    source_hashes[owner_rel] = sha(owner)
    examples = destination / "hepta-neuron/examples"
    examples.mkdir(exist_ok=True)
    (examples / "original_owner.rs").write_bytes(owner)
    for file in Path(__file__).parent.glob("*.rs"):
        data = file.read_bytes()
        source_hashes[str(file.relative_to(repository))] = sha(data)
        (examples / file.name).write_bytes(data)
    members = ", ".join(json.dumps(x) for x in CRATES)
    manifest = f"""[workspace]
members = [{members}]
resolver = "2"
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.dependencies]
serde = {{version="=1.0.228", features=["rc"]}}
serde_json = "=1.0.149"
sha2 = "=0.10.9"
ed25519-dalek = {{version="=2.2.0", features=["pkcs8"]}}
rustix = {{version="=1.1.4", features=["net"]}}
zeroize = "=1.8.2"
[workspace.lints.rust]
[profile.release]
debug = 0
incremental = false
strip = true
"""
    (destination / "Cargo.toml").write_text(manifest)
    neuron_manifest = destination / "hepta-neuron/Cargo.toml"
    with neuron_manifest.open("a") as stream:
        stream.write('\n[dependencies.codex-hepta-ndu]\npath = "../hepta-ndu"\n')
    generated_manifests["codex-rs/hepta-neuron/Cargo.toml"]["build_sha256"] = sha(
        neuron_manifest.read_bytes()
    )
    generated_manifests["codex-rs/hepta-neuron/Cargo.toml"]["change"] += (
        "; add original NDU crate for the research example only"
    )
    lock_bytes = git_bytes(repository, "codex-rs/Cargo.lock")
    packages = tomllib.loads(lock_bytes.decode())["package"]
    vendors = registry_closure(packages)
    verified_vendor(vendors, destination / "vendor", caches)
    (destination / ".cargo").mkdir()
    (destination / ".cargo/config.toml").write_text(
        '[source.crates-io]\nreplace-with="vendor"\n[source.vendor]\ndirectory="vendor"\n'
    )
    manifest_bytes = json.dumps(
        source_hashes, sort_keys=True, separators=(",", ":")
    ).encode()
    env = dict(
        os.environ,
        CARGO_HOME=str(destination / "cargo-home"),
        RUSTC=str(compiler / "rustc"),
        CONTINUOUS_NATIVE_SOURCE_COMMIT=BASE,
        CONTINUOUS_NATIVE_SOURCE_DIGEST=sha(manifest_bytes),
    )
    (destination / "SOURCE_MANIFEST.json").write_bytes(manifest_bytes)
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    lock = subprocess.run(
        [str(compiler / "cargo"), "generate-lockfile", "--offline"],
        cwd=destination,
        env=env,
        capture_output=True,
        text=True,
    )
    (destination / "LOCK.log").write_text(lock.stdout + lock.stderr)
    lock.check_returncode()
    resolved = tomllib.loads((destination / "Cargo.lock").read_text())["package"]

    def identity(p):
        return (p["name"], p["version"], p.get("source"), p.get("checksum"))

    if not {identity(p) for p in resolved if "source" in p} <= {
        identity(p) for p in packages if "source" in p
    }:
        raise ValueError("External dependency identity drift")
    command = [
        str(compiler / "cargo"),
        "build",
        "--release",
        "--locked",
        "--offline",
        "-j",
        "2",
        "-p",
        "codex-hepta-neuron",
        "--example",
        "continuous_host",
    ]
    done = subprocess.run(
        command, cwd=destination, env=env, capture_output=True, text=True
    )
    (destination / "BUILD.log").write_text(done.stdout + done.stderr)
    done.check_returncode()
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    binary = destination / "target/release/examples/continuous_host"
    receipt = {
        "schema": "hepta.continuous-boundary.native-build.v1",
        "base_commit": BASE,
        "source_sha256": source_hashes,
        "generated_build_manifests": generated_manifests,
        "native_rust_sources_unmodified": True,
        "full_daemon_build": False,
        "repository_lock_sha256": sha(lock_bytes),
        "resolved_lock_sha256": sha((destination / "Cargo.lock").read_bytes()),
        "external_dependencies_match_original_lock": True,
        "registry_package_count": len(vendors),
        "compiler": subprocess.check_output(
            [str(compiler / "rustc"), "--version"], text=True
        ).strip(),
        "compiler_sha256": sha((compiler / "rustc").read_bytes()),
        "command": command,
        "binary": str(binary),
        "binary_sha256": sha(binary.read_bytes()),
        "build_wall_seconds": time.perf_counter() - started,
        "build_child_cpu_seconds": cpu_after.ru_utime
        + cpu_after.ru_stime
        - cpu_before.ru_utime
        - cpu_before.ru_stime,
    }
    (destination / "BUILD_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return receipt


def rebuild(repository, destination, compiler):
    manifest_path = destination / "SOURCE_MANIFEST.json"
    identities = json.loads(manifest_path.read_text())
    for rel, expected in identities.items():
        if not rel.startswith("codex-rs/"):
            continue
        actual = git_bytes(repository, rel)
        if sha(actual) != expected:
            raise ValueError(f"Pinned source identity changed: {rel}")
        if rel.endswith("Cargo.toml"):
            continue
        target = destination / Path(rel).relative_to("codex-rs")
        if rel.endswith("hepta-agentd/src/neuron_runtime.rs"):
            target = destination / "hepta-neuron/examples/original_owner.rs"
        if sha(target.read_bytes()) != expected:
            raise ValueError(f"Build native source changed: {rel}")
    for file in Path(__file__).parent.glob("*.rs"):
        data = file.read_bytes()
        identities[str(file.relative_to(repository))] = sha(data)
        (destination / "hepta-neuron/examples" / file.name).write_bytes(data)
    manifest_bytes = json.dumps(
        identities, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest_path.write_bytes(manifest_bytes)
    env = dict(
        os.environ,
        CARGO_HOME=str(destination / "cargo-home"),
        RUSTC=str(compiler / "rustc"),
        CONTINUOUS_NATIVE_SOURCE_COMMIT=BASE,
        CONTINUOUS_NATIVE_SOURCE_DIGEST=sha(manifest_bytes),
    )
    history = len(list(destination.glob("BUILD.previous.*.log")))
    if (destination / "BUILD.log").exists():
        shutil.copyfile(
            destination / "BUILD.log", destination / f"BUILD.previous.{history}.log"
        )
    if (destination / "BUILD_RECEIPT.json").exists():
        shutil.copyfile(
            destination / "BUILD_RECEIPT.json",
            destination / f"BUILD_RECEIPT.previous.{history}.json",
        )
    command = [
        str(compiler / "cargo"),
        "build",
        "--release",
        "--locked",
        "--offline",
        "-j",
        "2",
        "-p",
        "codex-hepta-neuron",
        "--example",
        "continuous_host",
    ]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    done = subprocess.run(
        command, cwd=destination, env=env, capture_output=True, text=True
    )
    (destination / "BUILD.log").write_text(done.stdout + done.stderr)
    done.check_returncode()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    binary = destination / "target/release/examples/continuous_host"
    original = tomllib.loads(git_bytes(repository, "codex-rs/Cargo.lock").decode())[
        "package"
    ]
    resolved = tomllib.loads((destination / "Cargo.lock").read_text())["package"]
    identity = lambda x: (x["name"], x["version"], x.get("source"), x.get("checksum"))
    if not {identity(x) for x in resolved if "source" in x} <= {
        identity(x) for x in original if "source" in x
    }:
        raise ValueError("Rebuild dependency identity drift")
    manifests = {}
    for name in CRATES:
        rel = f"codex-rs/{name}/Cargo.toml"
        manifests[rel] = {
            "original_sha256": identities[rel],
            "build_sha256": sha((destination / name / "Cargo.toml").read_bytes()),
            "change": "test-only dependencies omitted; research example additionally links original NDU",
        }
    receipt = {
        "schema": "hepta.continuous-boundary.native-build.v1",
        "base_commit": BASE,
        "source_sha256": identities,
        "generated_build_manifests": manifests,
        "native_rust_sources_unmodified": True,
        "full_daemon_build": False,
        "external_dependencies_match_original_lock": True,
        "repository_lock_sha256": sha(git_bytes(repository, "codex-rs/Cargo.lock")),
        "resolved_lock_sha256": sha((destination / "Cargo.lock").read_bytes()),
        "compiler": subprocess.check_output(
            [str(compiler / "rustc"), "--version"], text=True
        ).strip(),
        "compiler_sha256": sha((compiler / "rustc").read_bytes()),
        "command": command,
        "binary": str(binary),
        "binary_sha256": sha(binary.read_bytes()),
        "build_wall_seconds": time.perf_counter() - start,
        "build_child_cpu_seconds": after.ru_utime
        + after.ru_stime
        - before.ru_utime
        - before.ru_stime,
        "prior_build_logs": [
            x.name for x in sorted(destination.glob("BUILD.previous.*.log"))
        ],
    }
    (destination / "BUILD_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--vendor-cache", type=Path, action="append", default=[])
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    receipt = (
        rebuild(
            args.repository.resolve(),
            args.destination.resolve(),
            args.compiler.resolve(),
        )
        if args.reuse
        else build(
            args.repository.resolve(),
            args.destination.resolve(),
            args.compiler.resolve(),
            args.vendor_cache,
        )
    )
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "binary",
                    "binary_sha256",
                    "build_wall_seconds",
                    "build_child_cpu_seconds",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
