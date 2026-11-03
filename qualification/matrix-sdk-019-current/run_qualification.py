#!/usr/bin/env python3
"""Run source-bound Matrix migration checks and retain original failures."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "codex-rs"
QUALIFICATION = Path(__file__).resolve().parent


def snapshot():
    roots = [
        "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "MODULE.bazel",
        "codex-rs/rust-toolchain.toml", "codex-rs/.config/nextest.toml",
        "justfile", "scripts/run-nextest.py", "scripts/check-module-bazel-lock.sh",
        "codex-rs/hepta-matrix-sdk", "codex-rs/hepta-matrix-store",
        "codex-rs/hepta-matrix-protocol", "codex-rs/hepta-matrixd",
        "codex-rs/state", "codex-rs/execpolicy",
        "codex-rs/third_party/matrix-sdk-0.19.1",
        "codex-rs/third_party/matrix-sdk-sqlite-0.18.0",
        "codex-rs/third_party/sqlx-sqlite-0.9.0",
        "codex-rs/third_party/starlark-0.14.2",
        "qualification/matrix-sdk-019-current/legacy-generator",
        "qualification/matrix-sdk-019-current/run_qualification.py",
        "qualification/matrix-sdk-019-current/run-crypto-migration.sh",
        ".github/workflows/hepta-matrix-security-qualification.yml",
    ]
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *roots], cwd=ROOT
    ).decode().split("\0")
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in names if name
    }


def execute(name, argv, output, commands, cwd=WORKSPACE):
    started = time.monotonic()
    path = output / f"{name}.log"
    with path.open("wb") as stream:
        result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    commands.append({
        "name": name, "argv": argv, "exit_code": result.returncode,
        "seconds": time.monotonic() - started,
        "log_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    if result.returncode:
        raise RuntimeError(f"{name} exited {result.returncode}; see {path.name}")


def verify_junit(output, name, expected=None):
    path = WORKSPACE / "target/nextest/local/junit.xml"
    document = ET.parse(path)
    cases = document.findall(".//testcase")
    if not cases or (expected is not None and len(cases) != expected):
        raise RuntimeError(f"unexpected {name} test count: {len(cases)}")
    if any(child.tag in {"failure", "error", "skipped"} for case in cases for child in case):
        raise RuntimeError(f"{name} contains a failure, error or skipped test")
    if int(document.getroot().get("tests", "-1")) != len(cases):
        raise RuntimeError(f"{name} JUnit aggregate disagrees with actual cases")
    target = output / f"{name}.junit.xml"
    shutil.copyfile(path, target)
    return {"count": len(cases), "zero_skipped": True,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "names": [case.get("name") for case in cases]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["owners", "sqlite-starlark", "crypto-migration", "synapse-protocol", "bazel"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    receipt = {"mode": args.mode, "source_commit": commit, "source_before": before,
               "commands": [], "status": "failed", "scope": "No paired-host admission or full-platform acceptance is implied."}
    (output / "source-commit.txt").write_text(commit + "\n")
    started = time.monotonic()
    try:
        if args.mode == "bazel":
            execute("original-lock-update", ["just", "bazel-lock-update"], output, receipt["commands"], ROOT)
            shutil.copyfile(ROOT / "MODULE.bazel.lock", output / "MODULE.bazel.lock")
            execute("original-lock-check", ["just", "bazel-lock-check"], output, receipt["commands"], ROOT)
            wrapper = str(ROOT / ".github/scripts/run_bazel_with_buildbuddy.py")
            execute("production-dependencies", [wrapper, "build", "@crates//:matrix-sdk", "@crates//:sqlx-sqlite", "@crates//:starlark"], output, receipt["commands"], ROOT)
            execute("matrix-regressions", [wrapper, "test", "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-crypto_advisory-test", "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-event_handler_context-test", "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-sdk_store_upgrade-test"], output, receipt["commands"], ROOT)
        else:
            rustc = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
            (output / "rustc-version.txt").write_text(rustc)
            if not rustc.startswith("rustc 1.96.0 "):
                raise RuntimeError("the official SDK requires the selected Rust 1.96.0 toolchain")
            metadata = subprocess.run(["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"], cwd=WORKSPACE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (output / "metadata.stderr").write_bytes(metadata.stderr)
            (output / "metadata.json.gz").write_bytes(gzip.compress(metadata.stdout, mtime=0))
            if metadata.returncode:
                raise RuntimeError("locked production metadata failed")
            graph = json.loads(metadata.stdout)
            packages = graph["packages"]
            if any(p["name"] in {"anymap2"} for p in packages):
                raise RuntimeError("abandoned typemap remains in the product graph")
            for name, version in [("matrix-sdk", "0.19.1"), ("matrix-sdk-crypto", "0.19.1"), ("matrix-sdk-sqlite", "0.19.1"), ("anymap3", "1.1.0"), ("libsqlite3-sys", "0.38.2")]:
                if [p["version"] for p in packages if p["name"] == name] != [version]:
                    raise RuntimeError(f"unexpected {name} version selection")
            nodes = {node["id"]: node for node in graph["resolve"]["nodes"]}
            for name in ["matrix-sdk", "sqlx-sqlite", "starlark"]:
                package = next(p for p in packages if p["name"] == name)
                if package["source"] is not None:
                    raise RuntimeError(f"reviewed {name} path package is not selected")
            if any("high_entropy_passphrase" in node["features"] for node in nodes.values()):
                raise RuntimeError("passphrase format must not change during this migration")
            (WORKSPACE / "target/nextest/local/junit.xml").unlink(missing_ok=True)
            expected = None
            if args.mode == "owners":
                command = ["just", "test", "--locked", "--no-tests=fail", "--retries", "0", "-p", "codex-hepta-matrix-protocol", "-p", "codex-hepta-matrix-sdk", "-p", "codex-hepta-matrix-store", "-p", "codex-hepta-matrixd"]
            elif args.mode == "sqlite-starlark":
                command = ["just", "test", "--locked", "--no-tests=fail", "--retries", "0", "-p", "codex-state", "-p", "codex-execpolicy", "--lib"]
            elif args.mode == "crypto-migration":
                command = ["bash", str(QUALIFICATION / "run-crypto-migration.sh")]
                expected = 1
            else:
                command = ["bash", str(WORKSPACE / "hepta-matrix-sdk/tests/support/run-synapse-sdk.sh")]
                expected = 1
            execute(args.mode, command, output, receipt["commands"])
            receipt["tests"] = verify_junit(output, args.mode, expected)
            if args.mode == "owners":
                execute("scoped-clippy-fix", ["just", "fix", "-p", "codex-hepta-matrix-sdk", "-p", "codex-hepta-matrix-store", "-p", "codex-hepta-matrix-protocol", "--locked", "--no-deps"], output, receipt["commands"])
        receipt["source_after"] = snapshot()
        if receipt["source_after"] != before:
            raise RuntimeError("tracked production or qualification inputs changed")
        receipt["status"] = "passed"
    finally:
        receipt["seconds"] = time.monotonic() - started
        receipt["resource_environment"] = {k: os.environ.get(k) for k in ["CARGO_BUILD_JOBS", "CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG"]}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
