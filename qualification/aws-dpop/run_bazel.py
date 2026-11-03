#!/usr/bin/env python3
"""Retain real lock generation and AWS Bazel results with immutable inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import run_native


REPO = Path(__file__).resolve().parents[2]


def snapshot():
    result = run_native.snapshot()
    paths = subprocess.check_output(
        [
            "git", "ls-files", "-z", "--", "MODULE.bazel", "MODULE.bazel.lock", ".bazelrc",
            "defs.bzl", "cargo_bazel_template", "codex-rs/**/Cargo.toml",
            ".github/actions/prepare-bazel-ci", ".github/scripts/run_bazel_with_buildbuddy.py",
            "scripts/check-module-bazel-lock.sh", "scripts/update_cargo_bazel.py",
        ],
        cwd=REPO,
    ).decode().split("\0")
    result.update({name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in paths if name})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    committed_lock = (REPO / "MODULE.bazel.lock").read_bytes()
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    (output / "source-commit.txt").write_text(commit + "\n")
    receipt = {"commit": commit, "status": "failed", "steps": []}
    wrapper = "./.github/scripts/run_bazel_with_buildbuddy.py"
    commands = [
        ("committed-lock-check", ["./scripts/check-module-bazel-lock.sh"]),
        ("lock-update", ["just", "bazel-lock-update"]),
        ("lock-check", ["./scripts/check-module-bazel-lock.sh"]),
        ("aws-config-build", [wrapper, "build", "@crates//:aws-config"]),
        ("aws-auth-test", [wrapper, "test", "//codex-rs/aws-auth:aws-auth-unit-tests"]),
        ("generated-target", [wrapper, "query", "deps(@crates//:aws-config, 5)", "--output=build"]),
    ]
    try:
        for name, command in commands:
            started = time.time()
            log = output / f"{name}.log"
            with log.open("wb") as stream:
                result = subprocess.run(command, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT)
            receipt["steps"].append({"name": name, "command": command, "exit": result.returncode, "elapsed_seconds": time.time() - started})
            if result.returncode:
                raise RuntimeError(f"{name} exited {result.returncode}")
            if name == "lock-update":
                if (REPO / "MODULE.bazel.lock").read_bytes() != committed_lock:
                    raise RuntimeError("regeneration changed the committed Bazel lock")
                shutil.copyfile(REPO / "MODULE.bazel.lock", output / "MODULE.bazel.lock")
        if snapshot() != before:
            raise RuntimeError("Bazel qualification changed an input other than its generated lock")
        if (REPO / "MODULE.bazel.lock").read_bytes() != (output / "MODULE.bazel.lock").read_bytes():
            raise RuntimeError("Bazel lock changed after generation")
        receipt["status"] = "passed"
    finally:
        receipt["outputs"] = {
            p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(output.iterdir()) if p.is_file() and p.name != "receipt.json"
        }
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
