#!/usr/bin/env python3
"""Generate or qualify the original Bazel lock for the isolated lint workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def snapshot():
    names = subprocess.check_output([
        "git", "ls-files", "-z", "--", "MODULE.bazel", "BUILD.bazel", ".bazelrc", ".bazelversion", "defs.bzl",
        "bazel", "third_party", "cargo_bazel_template", "justfile", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
        "codex-rs/rust-toolchain.toml", "codex-rs/**/Cargo.toml", "codex-rs/third_party", "patches",
        "tools/argument-comment-lint", "scripts/update_cargo_bazel.py", "scripts/check-module-bazel-lock.sh",
        ".github/scripts/run_bazel_with_buildbuddy.py", ".github/actions/setup-ci",
        ".github/actions/setup-bazel-ci", ".github/actions/prepare-bazel-ci", ".github/workflows/rust-ci.yml",
        ".github/workflows/rust-ci-full.yml", ".github/workflows/rust-release-argument-comment-lint.yml",
        ".github/workflows/hepta-dylint-lock-qualification.yml", "qualification/dylint-20261103",
    ], cwd=ROOT).decode().split("\0")
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names if name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-committed", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    original = (ROOT / "MODULE.bazel.lock").read_bytes()
    receipt = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "index_tree": subprocess.check_output(["git", "write-tree"], cwd=ROOT, text=True).strip(),
        "committed_lock_required": args.require_committed,
        "committed_lock_sha256": hashlib.sha256(original).hexdigest(),
        "status": "failed", "steps": [],
    }
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    (output / "committed-MODULE.bazel.lock").write_bytes(original)
    try:
        commands = []
        if args.require_committed:
            commands.append(("committed-lock-check", ["./scripts/check-module-bazel-lock.sh"]))
        commands.extend([
            ("original-lock-update", ["just", "bazel-lock-update"]),
            ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"]),
        ])
        for name, command in commands:
            started = time.monotonic()
            with (output / (name + ".stdout")).open("wb") as stdout, (output / (name + ".stderr")).open("wb") as stderr:
                result = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr)
            receipt["steps"].append({"name": name, "command": command, "exit": result.returncode,
                                     "elapsed_seconds": time.monotonic() - started})
            if result.returncode:
                raise RuntimeError(f"{name} exited {result.returncode}")
            if name == "original-lock-update":
                shutil.copyfile(ROOT / "MODULE.bazel.lock", output / "MODULE.bazel.lock")
        generated = (output / "MODULE.bazel.lock").read_bytes()
        json.loads(generated)
        if (ROOT / "MODULE.bazel.lock").read_bytes() != generated or snapshot() != before:
            raise RuntimeError("original checking changed the generated lock or another source input")
        if args.require_committed and generated != original:
            raise RuntimeError("regeneration changed the committed lock")
        receipt.update(status="passed" if args.require_committed else "generated-not-committed-qualification",
                       generated_lock_sha256=hashlib.sha256(generated).hexdigest(),
                       generated_lock_bytes=len(generated), committed_lock_matches=generated == original)
    finally:
        receipt["source_after"] = snapshot()
        receipt["source_inputs_unchanged"] = receipt["source_after"] == before
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
