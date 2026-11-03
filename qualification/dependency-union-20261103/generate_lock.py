#!/usr/bin/env python3
"""Generate the combined Bazel lock with the repository's original commands."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]


def snapshot():
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "MODULE.bazel", ".bazelrc", ".bazelversion",
         "defs.bzl", "cargo_bazel_template", "justfile", "codex-rs/Cargo.toml",
         "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml", "codex-rs/**/Cargo.toml",
         "codex-rs/third_party", "patches", "scripts/update_cargo_bazel.py",
         "scripts/check-module-bazel-lock.sh", ".github/scripts/run_bazel_with_buildbuddy.py",
         ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
         ".github/actions/prepare-bazel-ci", ".github/workflows/hepta-dependency-union-lock.yml",
         "qualification/dependency-union-20261103/generate_lock.py"], cwd=ROOT,
    ).decode().split("\0")
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names if name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    original_lock = (ROOT / "MODULE.bazel.lock").read_bytes()
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    (output / "source-commit.txt").write_text(commit + "\n")
    receipt = {"commit": commit, "status": "failed", "steps": [],
               "committed_lock_sha256": hashlib.sha256(original_lock).hexdigest()}
    try:
        for name, command in [
            ("original-lock-update", ["just", "bazel-lock-update"]),
            ("original-lock-check", ["./scripts/check-module-bazel-lock.sh"]),
        ]:
            started = time.monotonic()
            with (output / f"{name}.stdout").open("wb") as stdout, (output / f"{name}.stderr").open("wb") as stderr:
                result = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr)
            receipt["steps"].append({"name": name, "command": command, "exit": result.returncode,
                                     "elapsed_seconds": time.monotonic() - started})
            if result.returncode:
                raise RuntimeError(f"{name} exited {result.returncode}")
            if name == "original-lock-update":
                shutil.copyfile(ROOT / "MODULE.bazel.lock", output / "MODULE.bazel.lock")
        generated = (output / "MODULE.bazel.lock").read_bytes()
        json.loads(generated)
        if (ROOT / "MODULE.bazel.lock").read_bytes() != generated:
            raise RuntimeError("the original lock check changed the generated lock")
        if snapshot() != before:
            raise RuntimeError("lock generation changed a non-lock input")
        receipt.update(status="passed", generated_lock_sha256=hashlib.sha256(generated).hexdigest(),
                       generated_lock_bytes=len(generated), committed_lock_matches=generated == original_lock)
    finally:
        receipt["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
