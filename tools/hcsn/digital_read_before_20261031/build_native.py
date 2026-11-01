#!/usr/bin/env python3
"""Build the actual pinned Hepta runtime in a small, independently identified workspace.

The original repository `just test` and `just fmt` recipes and their launchers
are copied byte-for-byte. The temporary Cargo workspace includes only the three
pinned runtime crates and this research binary. Registry dependencies are really
compiled (or reused by Cargo after this build); a Cargo.lock binds their versions.
This is not a full-repository CI claim or an archival pre-reset cache claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
NATIVE = HERE / "native"
HELPERS = {
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "scripts/format.py": "d4eabe70b68605933240e9129245f7f4cccbde5d",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
    "scripts/just-shell.py": "bb2db6ebc4312a301ee39d2793fde16289d046d8",
}
WORKSPACE = '''[workspace]
resolver = "2"
members = ["hepta-types", "hepta-infer-core", "hepta-neuron", "digital-read-before-native"]
[workspace.package]
version = "0.0.0"
edition = "2024"
license = "Apache-2.0"
[workspace.lints.rust]
[workspace.dependencies]
serde = { version = "1", features = ["derive", "rc"] }
serde_json = { version = "1", features = ["float_roundtrip"] }
sha2 = "0.10"
pretty_assertions = "1.4.1"
libc = "0.2.182"
'''
CRATE = '''[package]
name = "hepta-digital-read-before-native"
version = "0.1.0"
edition = "2024"
publish = false
[dependencies]
codex-hepta-neuron = { path = "../hepta-neuron" }
codex-hepta-types = { path = "../hepta-types" }
serde = { workspace = true }
serde_json = { workspace = true }
libc = { workspace = true }
'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)


def run(command: list[str], cwd: Path, env: dict, logdir: Path, label: str) -> dict:
    start = time.perf_counter()
    process = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    text = process.stdout + process.stderr
    write(logdir / f"{label}.log", text)
    receipt = dict(command=command, cwd=str(cwd), returncode=process.returncode,
                   wall_seconds=time.perf_counter()-start,
                   log=str(logdir / f"{label}.log"), log_sha256=sha(text.encode()))
    print(json.dumps(dict(stage=label, returncode=process.returncode,
                         wall_seconds=receipt["wall_seconds"])), flush=True)
    if process.returncode:
        print(text[-16000:], flush=True)
        raise RuntimeError(f"{label} failed; full log: {receipt['log']}")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--rust-bin", type=Path)
    parser.add_argument("--tools-bin", type=Path)
    parser.add_argument("--cargo-home", type=Path)
    parser.add_argument("--allow-network", action="store_true",
                        help="Permit Cargo's ordinary dependency fetch; default is offline.")
    parser.add_argument("--receipt", type=Path, default=HERE / "evidence/NATIVE_BUILD.json")
    args = parser.parse_args()
    upstream, work = args.upstream_root.resolve(), args.work_dir.resolve()
    if work == upstream or work == HERE or work.is_relative_to(HERE):
        raise ValueError("build workspace must be a separate temporary directory")
    identity = json.loads((NATIVE / "UPSTREAM_SOURCE_IDENTITY.json").read_text())
    source_receipts = []
    for item in [*identity["files"], *[dict(path=p, git_blob_sha=h) for p, h in HELPERS.items()]]:
        data = (upstream / item["path"]).read_bytes()
        if git_blob(data) != item["git_blob_sha"]:
            raise ValueError(f"pinned Git source mismatch: {item['path']}")
        write(work / item["path"], data)
        source_receipts.append(dict(**item, sha256=sha(data), bytes=len(data)))
    write(work / "codex-rs/Cargo.toml", WORKSPACE)
    write(work / "codex-rs/digital-read-before-native/Cargo.toml", CRATE)
    # This bounded workspace has no unrelated product packages. Retain the
    # repository's local profile name without pretending unrelated CI overrides apply.
    write(work / "codex-rs/.config/nextest.toml",
          '[profile.local]\ninherits = "default"\nretries = 0\n')
    write(work / ".gitignore", "/codex-rs/target/\n/logs/\n/build-receipt.json\n")
    env = dict(os.environ)
    prefixes = [str(p) for p in (args.rust_bin, args.tools_bin) if p is not None]
    env["PATH"] = os.pathsep.join([*prefixes, env.get("PATH", "")])
    if args.cargo_home:
        env["CARGO_HOME"] = str(args.cargo_home.resolve())
    if not args.allow_network:
        env["CARGO_NET_OFFLINE"] = "true"
    env["RUST_MIN_STACK"] = "8388608"
    logdir = work / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    commands = []
    if not (work / ".git").exists():
        commands.append(run(["git", "init", "-q"], work, env, logdir, "git_init"))
        commands.append(run(["git", "add", "."], work, env, logdir, "git_initial_sources"))
        commands.append(run(["git", "-c", "user.name=Hepta Research Build",
                             "-c", "user.email=research-build@localhost", "commit", "-qm",
                             "Pinned runtime and unchanged repository gate entry points"],
                            work, env, logdir, "git_initial_commit"))
    for source in sorted(NATIVE.glob("*.rs")):
        write(work / "codex-rs/digital-read-before-native/src" / source.name, source.read_bytes())
    commands.append(run(["just", "fmt"], work, env, logdir, "just_fmt"))
    # Return formatting only to this namespace, never alter inherited crates.
    for source in sorted(NATIVE.glob("*.rs")):
        source.write_bytes((work / "codex-rs/digital-read-before-native/src" / source.name).read_bytes())
    commands.append(run(["just", "fmt", "--check"], work, env, logdir, "just_fmt_check"))
    cargo_root = work / "codex-rs"
    if (NATIVE / "Cargo.lock").exists():
        write(cargo_root / "Cargo.lock", (NATIVE / "Cargo.lock").read_bytes())
        commands.append(run(["cargo", "metadata", "--locked", "--no-deps", "--format-version=1"],
                            cargo_root, env, logdir, "cargo_locked_metadata"))
    else:
        commands.append(run(["cargo", "generate-lockfile", *([] if args.allow_network else ["--offline"])],
                            cargo_root, env, logdir, "cargo_lock"))
    lock = (cargo_root / "Cargo.lock").read_bytes()
    native_sources = [dict(path=p.name, sha256=sha(p.read_bytes()), bytes=p.stat().st_size)
                      for p in sorted(NATIVE.glob("*.rs"))]
    binding = dict(upstream_identity=identity, native_sources=native_sources,
                   cargo_lock_sha256=sha(lock), workspace_sha256=sha(WORKSPACE.encode()),
                   crate_sha256=sha(CRATE.encode()))
    source_digest = sha(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode())
    env["HEPTA_TASK_NATIVE_SOURCE_DIGEST"] = source_digest
    commands.append(run(["cargo", "build", "--locked", "--release", "-p",
                         "hepta-digital-read-before-native"], cargo_root, env, logdir, "cargo_build"))
    commands.append(run(["just", "test", "--locked", "-p", "hepta-digital-read-before-native",
                         "-p", "codex-hepta-neuron", "-p", "codex-hepta-infer-core", "-p", "codex-hepta-types"],
                        work, env, logdir, "just_test"))
    binary = cargo_root / "target/release/hepta-digital-read-before-native"
    versions = {}
    for name, command in {"rustc": ["rustc", "-Vv"], "cargo": ["cargo", "-V"],
                          "just": ["just", "--version"], "nextest": ["cargo", "nextest", "--version"]}.items():
        versions[name] = subprocess.check_output(command, env=env, text=True).strip()
    receipt = dict(schema="digital-read-before-native-build-v1", source_digest=source_digest,
                   binding=binding, pinned_sources=source_receipts, commands=commands,
                   binary=str(binary), binary_sha256=sha(binary.read_bytes()), versions=versions,
                   cargo_lock_sha256=sha(lock), cargo_lock=str(cargo_root / "Cargo.lock"),
                   build_wrapper_sha256=sha(Path(__file__).read_bytes()),
                   dependency_build="actual Cargo compilation, isolated workspace, lockfile bound; no archival cache claim",
                   gates="unchanged pinned just test and just fmt recipes/launchers; scoped four-crate workspace",
                   nextest_profile="local inherits default, retries=0; unrelated product overrides excluded",
                   full_repository_ci=False, production_activation=False)
    encoded = json.dumps(receipt, indent=2)+"\n"
    write(args.receipt, encoded)
    write(work / "build-receipt.json", encoded)
    write(NATIVE / "Cargo.lock", lock)
    print(json.dumps(dict(binary=str(binary), source_digest=source_digest, receipt=str(args.receipt))), flush=True)


if __name__ == "__main__":
    main()
