#!/usr/bin/env python3
"""Run the original AWS consumer and source-bound DPoP qualification."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import tomllib
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "codex-rs"
HARNESS = Path(__file__).resolve().parent


def snapshot():
    paths = subprocess.check_output(
        [
            "git", "ls-files", "-z", "--", "codex-rs/Cargo.toml",
            "codex-rs/Cargo.lock", "codex-rs/aws-auth", "codex-rs/.config/nextest.toml",
            "codex-rs/third_party/aws-config-1.8.12", "qualification/aws-dpop",
            "codex-rs/rust-toolchain.toml", "justfile", "scripts/run-nextest.py",
            ".github/workflows/hepta-aws-p256-qualification.yml",
        ],
        cwd=REPO,
    ).decode().split("\0")
    return {
        name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
        for name in paths if name
    }


def run(command, log, cwd=WORKSPACE):
    with log.open("wb") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{command!r} exited {result.returncode}; see {log.name}")


def retain_junit(workspace, name, expected, output):
    source = workspace / "target/nextest/local/junit.xml"
    document = ET.parse(source)
    cases = document.findall(".//testcase")
    if len(cases) != expected or any(
        child.tag in {"failure", "error", "skipped"}
        for case in cases for child in case
    ):
        raise RuntimeError(f"{name}: expected {expected} passing tests and zero skips")
    if document.getroot().get("tests") != str(expected):
        raise RuntimeError(f"{name}: JUnit aggregate differs from actual cases")
    shutil.copyfile(source, output / f"{name}.junit.xml")
    return [case.get("name") for case in cases]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    (output / "source-inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    (output / "source-commit.txt").write_text(commit + "\n")
    rustc = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
    (output / "rustc-version.txt").write_text(rustc)
    toolchain = tomllib.loads((WORKSPACE / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    if not rustc.startswith(f"rustc {toolchain} "):
        raise RuntimeError(f"qualification requires the committed Rust {toolchain} toolchain")
    started = time.time()
    receipt = {"commit": commit, "status": "failed", "tests": {}}
    try:
        (WORKSPACE / "target/nextest/local/junit.xml").unlink(missing_ok=True)
        run(["just", "test", "-p", "codex-aws-auth", "--locked", "--no-tests=fail", "--retries", "0"], output / "aws-auth.log")
        receipt["tests"]["aws_auth"] = retain_junit(WORKSPACE, "aws-auth", 5, output)
        (HARNESS / "target/nextest/local/junit.xml").unlink(missing_ok=True)
        run([
            "just", "test", "--manifest-path", str(HARNESS / "Cargo.toml"),
            "--config-file", str(HARNESS / ".config/nextest.toml"), "--locked",
            "--no-tests=fail", "--retries", "0",
        ], output / "dpop.log")
        receipt["tests"]["dpop"] = retain_junit(HARNESS, "dpop", 8, output)
        command = ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"]
        result = subprocess.run(command, cwd=WORKSPACE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output / "metadata.stderr").write_bytes(result.stderr)
        with (output / "production-metadata.json.gz").open("wb") as target:
            target.write(gzip.compress(result.stdout, mtime=0))
        if result.returncode:
            raise RuntimeError("locked production metadata failed")
        metadata = json.loads(result.stdout)
        selected = [p for p in metadata["packages"] if p["name"] in {"p256", "crypto-bigint", "aws-config"}]
        versions = {p["name"]: [q["version"] for q in selected if q["name"] == p["name"]] for p in selected}
        if versions != {"aws-config": ["1.8.12"], "crypto-bigint": ["0.7.10"], "p256": ["0.14.0"]}:
            raise RuntimeError(f"unexpected production crypto graph: {versions}")
        rng_versions = [p["version"] for p in metadata["packages"] if p["name"] == "chacha20" and p["version"].startswith("0.10.")]
        if rng_versions != ["0.10.2"]:
            raise RuntimeError(f"unexpected ChaCha RNG backend: {rng_versions}")
        aws = next(p for p in selected if p["name"] == "aws-config")
        nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
        if aws["source"] is not None or "credentials-login" not in nodes[aws["id"]]["features"]:
            raise RuntimeError("the patched AWS login provider is not selected")
        if snapshot() != before:
            raise RuntimeError("qualification changed tracked source inputs")
        receipt.update(status="passed", production_versions=versions, chacha_rng_versions=rng_versions, zero_skipped=True)
    finally:
        receipt["elapsed_seconds"] = time.time() - started
        receipt["resource_environment"] = {key: os.environ.get(key) for key in (
            "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG",
        )}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
