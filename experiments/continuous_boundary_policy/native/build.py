"""Build a separate score-only example using verified frozen native dependencies."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import tomllib

BASE = "5898cd8b0f724c3152b6cc52856721f72e5e08be"
OLD_BINARY_SHA256 = "1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_bytes(repository, path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=repository)


def verify_existing(repository, native_build):
    receipt = json.loads((native_build / "BUILD_RECEIPT.json").read_text())
    if receipt["base_commit"] != BASE or receipt["binary_sha256"] != OLD_BINARY_SHA256:
        raise ValueError("Unexpected frozen original native build")
    old_binary = native_build / "target/release/examples/continuous_host"
    if sha(old_binary.read_bytes()) != OLD_BINARY_SHA256:
        raise ValueError("Frozen continuous_host executable changed")
    sources = {}
    for relative, expected in receipt["source_sha256"].items():
        if not relative.startswith("codex-rs/"):
            continue
        original = git_bytes(repository, relative)
        if sha(original) != expected:
            raise ValueError(f"Original native source mismatch: {relative}")
        if relative.endswith("Cargo.toml"):
            continue
        target = native_build / Path(relative).relative_to("codex-rs")
        if relative == "codex-rs/hepta-agentd/src/neuron_runtime.rs":
            target = native_build / "hepta-neuron/examples/original_owner.rs"
        if sha(target.read_bytes()) != expected:
            raise ValueError(f"Cached native source mismatch: {relative}")
        sources[relative] = expected
    for relative, identities in receipt["generated_build_manifests"].items():
        target = native_build / Path(relative).relative_to("codex-rs")
        if sha(target.read_bytes()) != identities["build_sha256"]:
            raise ValueError(f"Cached generated manifest changed: {relative}")
    original_lock = git_bytes(repository, "codex-rs/Cargo.lock")
    resolved_lock = (native_build / "Cargo.lock").read_bytes()
    if (
        sha(original_lock) != receipt["repository_lock_sha256"]
        or sha(resolved_lock) != receipt["resolved_lock_sha256"]
    ):
        raise ValueError("Native lockfile identity mismatch")
    original = tomllib.loads(original_lock.decode())["package"]
    resolved = tomllib.loads(resolved_lock.decode())["package"]
    identities = {
        (p["name"], p["version"], p.get("source"), p.get("checksum")) for p in original
    }
    for package in resolved:
        if "source" not in package:
            continue
        identity = (
            package["name"],
            package["version"],
            package["source"],
            package["checksum"],
        )
        if identity not in identities:
            raise ValueError("Native dependency identity drift")
        directory = native_build / "vendor" / f"{package['name']}-{package['version']}"
        sums = json.loads((directory / ".cargo-checksum.json").read_text())
        if sums["package"] != package["checksum"]:
            raise ValueError("Vendor package checksum mismatch")
        for relative, expected in sums["files"].items():
            if sha((directory / relative).read_bytes()) != expected:
                raise ValueError(f"Vendor source changed: {directory.name}/{relative}")
    return receipt, sources


def build(repository, native_build, output_dir, compiler=None):
    repository, native_build, output_dir = (
        Path(p).resolve() for p in (repository, native_build, output_dir)
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    original, sources = verify_existing(repository, native_build)
    compiler = (
        Path(compiler).resolve() if compiler else Path(original["command"][0]).parent
    )
    if sha((compiler / "rustc").read_bytes()) != original["compiler_sha256"]:
        raise ValueError("Pinned Rust compiler identity changed")
    examples = native_build / "hepta-neuron/examples"
    module_dir = examples / "boundary_policy_score"
    module_dir.mkdir(exist_ok=True)
    source_root = Path(__file__).resolve().parent
    for name in ("score_host.rs", "protocol.rs", "decision.rs"):
        source = source_root / name
        raw = source.read_bytes()
        relative = str(source.relative_to(repository))
        sources[relative] = sha(raw)
        target = (
            examples / "boundary_policy_score_host.rs"
            if name == "score_host.rs"
            else module_dir / name
        )
        target.write_bytes(raw)
    manifest = json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()
    (output_dir / "SOURCE_MANIFEST.json").write_bytes(manifest)
    env = dict(
        os.environ,
        CARGO_HOME=str(native_build / "cargo-home"),
        RUSTC=str(compiler / "rustc"),
        POLICY_NATIVE_SOURCE_COMMIT=BASE,
        POLICY_NATIVE_SOURCE_DIGEST=sha(manifest),
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
        "boundary_policy_score_host",
    ]
    started = time.perf_counter()
    with (output_dir / "BUILD.log").open("wb") as log:
        process = subprocess.Popen(
            command, cwd=native_build, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    wall = time.perf_counter() - started
    verify_existing(repository, native_build)
    if process.returncode:
        raise RuntimeError(f"Native score build failed; see {output_dir / 'BUILD.log'}")
    binary = native_build / "target/release/examples/boundary_policy_score_host"
    receipt = {
        "schema": "hepta.boundary-policy.native-score-build.v1",
        "base_commit": BASE,
        "source_sha256": sources,
        "source_manifest_digest": sha(manifest),
        "binary": str(binary),
        "binary_sha256": sha(binary.read_bytes()),
        "compiler": original["compiler"],
        "compiler_sha256": original["compiler_sha256"],
        "original_binary_sha256": OLD_BINARY_SHA256,
        "original_binary_unchanged": True,
        "original_native_sources_unchanged": True,
        "external_dependencies_match_original_lock": True,
        "repository_lock_sha256": original["repository_lock_sha256"],
        "resolved_lock_sha256": original["resolved_lock_sha256"],
        "generated_build_manifests": original["generated_build_manifests"],
        "command": command,
        "build_wall_seconds": wall,
        "build_child_user_cpu_seconds": usage.ru_utime,
        "build_child_system_cpu_seconds": usage.ru_stime,
        "build_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "execution": "original NDU only; no sparse kernel; no durable owner",
    }
    (output_dir / "BUILD_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--native-build", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compiler", type=Path)
    args = parser.parse_args()
    receipt = build(args.repository, args.native_build, args.output_dir, args.compiler)
    print(
        json.dumps(
            {
                key: receipt[key]
                for key in (
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
