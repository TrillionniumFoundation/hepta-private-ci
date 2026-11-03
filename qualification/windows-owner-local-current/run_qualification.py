#!/usr/bin/env python3
"""Run original owner-local consumers against the exact dependency-union source."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "codex-rs"
INPUTS = [
    "codex-rs/uds", "codex-rs/hepta-matrixd", "codex-rs/hepta-matrix-sdk",
    "codex-rs/hepta-matrix-store", "codex-rs/hepta-matrix-protocol",
    "codex-rs/hepta-fleet", "codex-rs/hepta-paths", "codex-rs/hepta-contracts",
    "codex-rs/hepta-automation", "codex-rs/keyring-store",
    "codex-rs/third_party/keyring-3.6.3", "codex-rs/third_party/dbus-secret-service-4.1.0",
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
    "codex-rs/.config/nextest.toml", "justfile", "defs.bzl", "MODULE.bazel",
    "MODULE.bazel.lock", "scripts/run-nextest.py", "scripts/just-shell.py",
    "scripts/check-module-bazel-lock.sh", ".github/scripts/run_bazel_with_buildbuddy.py",
    "qualification/keyring-sync-provider/build_pinned_client.py", "third_party/dbus",
    "qualification/windows-owner-local-current",
    ".github/workflows/hepta-windows-owner-local-qualification.yml",
]
REQUIRED = {
    "codex-uds": {
        "owner_local::tests::authenticated_owner_local_stream_round_trips_application_bytes",
        "owner_local::tests::live_owner_local_listener_cannot_be_replaced",
    },
    "codex-hepta-matrixd": {
        "control::tests::health_tracks_real_task_state_and_owner_uds_serves_exact_identity",
    },
    "codex-hepta-fleet": {
        "registry::tests::workspace_sweep_agrees_with_pairwise_oracle_for_nested_and_sibling_paths",
    },
    "codex-hepta-automation": {
        "store::migration_convergence_tests::canonical_cut_before_rebind_reopens",
        "store::migration_convergence_tests::canonical_cut_after_rebind_reopens",
        "store::migration_convergence_tests::displaced_cut_before_rebind_reopens",
        "store::migration_convergence_tests::displaced_cut_after_rebind_reopens",
    },
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot():
    names = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-files", "-z", "--", *INPUTS], cwd=ROOT
    ).decode().split("\0")
    return {name: digest((ROOT / name).read_bytes()) for name in names if name}


def read_junit(path, output, package):
    raw = path.read_bytes()
    (output / f"{package}.junit.xml").write_bytes(raw)
    tree = ET.fromstring(raw)
    cases = tree.findall(".//testcase")
    names = {case.get("name") for case in cases}
    invalid = [case.get("name") for case in cases
               if any(child.tag in {"failure", "error", "skipped"} for child in case)]
    result = {"count": len(cases), "names": sorted(names), "failed_or_skipped": invalid,
              "sha256": digest(raw), "required_present": REQUIRED[package] <= names}
    if (not cases or int(tree.get("tests", "-1")) != len(cases)
            or len(names) != len(cases) or invalid or not result["required_present"]):
        raise RuntimeError(f"{package}: failed, skipped, duplicate or missing original tests")
    if package == "codex-uds" and len(cases) != (14 if os.name == "nt" else 10):
        raise RuntimeError("UDS original test inventory changed")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["native", "bazel"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    commit = subprocess.check_output(
        ["git", "--no-replace-objects", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    receipt = {"source_commit": commit, "mode": args.mode, "platform": platform.platform(),
               "source_before": before, "commands": [], "status": "failed",
               "scope": "Original scoped consumers; no whole-Windows, private-state or production admission claim."}

    def run(name, argv, cwd=WORKSPACE, required=True):
        started = time.monotonic()
        path = output / f"{name}.log"
        with path.open("wb") as stream:
            result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"name": name, "argv": argv, "exit_code": result.returncode,
                                    "seconds": time.monotonic() - started,
                                    "log_sha256": digest(path.read_bytes())})
        if result.returncode and required:
            raise RuntimeError(f"{name} exited {result.returncode}")
        return result.returncode

    try:
        expected = os.environ.get("HEPTA_EXPECTED_COMMIT", commit)
        if expected != commit:
            raise RuntimeError("checked out source is not the requested immutable commit")
        run("initial-tracked-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD"], ROOT)
        if args.mode == "bazel":
            old_lock = (ROOT / "MODULE.bazel.lock").read_bytes()
            first = run("committed-lock-first", ["just", "bazel-lock-check"], ROOT, required=False)
            run("original-lock-update", ["just", "bazel-lock-update"], ROOT)
            lock = (ROOT / "MODULE.bazel.lock").read_bytes()
            (output / "MODULE.bazel.lock").write_bytes(lock)
            receipt["generated_lock"] = {"bytes": len(lock), "sha256": digest(lock),
                                         "equals_committed": lock == old_lock}
            run("original-lock-check", ["just", "bazel-lock-check"], ROOT)
            if first or lock != old_lock:
                raise RuntimeError("actual generated lock must be adopted and committed-first validation rerun")
            wrapper = str(ROOT / ".github/scripts/run_bazel_with_buildbuddy.py")
            targets = [f"//codex-rs/{name}:{name}-unit-tests"
                       for name in ["uds", "hepta-matrixd", "hepta-fleet", "hepta-automation"]]
            run("original-owner-targets", [sys.executable, wrapper, "test", *targets], ROOT)
        else:
            run("rustc-version", ["rustc", "--version", "--verbose"])
            if not (output / "rustc-version.log").read_text().startswith("rustc 1.96.0 "):
                raise RuntimeError("qualification requires the actual selected Rust 1.96.0")
            metadata = subprocess.run(
                ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"],
                cwd=WORKSPACE, capture_output=True)
            (output / "metadata.stderr").write_bytes(metadata.stderr)
            (output / "metadata.json.gz").write_bytes(gzip.compress(metadata.stdout, mtime=0))
            receipt["metadata"] = {"exit_code": metadata.returncode,
                                   "sha256": digest(metadata.stdout)}
            if metadata.returncode:
                raise RuntimeError("the actual locked workspace graph failed")
            graph = json.loads(metadata.stdout)
            receipt["metadata"]["package_count"] = len(graph["packages"])
            if sys.platform.startswith("linux"):
                native = output.parent / "owner-local-pinned-dbus-client"
                try:
                    run("pinned-dbus-client", [sys.executable, str(ROOT / "qualification/keyring-sync-provider/build_pinned_client.py"), "--output", str(native)])
                finally:
                    if (native / "receipt.json").is_file():
                        shutil.copyfile(native / "receipt.json", output / "pinned-dbus-receipt.json")
                os.environ["PKG_CONFIG_PATH"] = str(native / "lib/pkgconfig")
            receipt["tests"] = {}
            for package in REQUIRED:
                # Nextest's store.dir is relative to the workspace and is
                # independent of Cargo's configured build target directory.
                junit = WORKSPACE / "target/nextest/local/junit.xml"
                junit.unlink(missing_ok=True)
                argv = ["just", "test", "--locked", "-p", package, "--lib", "--no-tests=fail", "--retries", "0", "--success-output=final"]
                if package in {"codex-uds", "codex-hepta-matrixd"}:
                    argv += ["--test-threads", "1"]
                code = run(package, argv, required=False)
                receipt["tests"][package] = read_junit(junit, output, package)
                if "skipping test:" in (output / f"{package}.log").read_text(errors="replace").lower():
                    raise RuntimeError("an existing test returned early without exercising its original operation")
                if code:
                    raise RuntimeError(f"original {package} library tests exited {code}")
            run("scoped-clippy-fix", ["just", "fix", "--locked", "-p", "codex-uds", "-p", "codex-hepta-matrixd", "-p", "codex-hepta-automation", "--no-deps"])
        receipt["source_after"] = snapshot()
        if receipt["source_after"] != before:
            raise RuntimeError("qualification modified a bound production or harness input")
        run("final-tracked-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD"], ROOT)
        receipt["status"] = "passed"
    finally:
        receipt.setdefault("source_after", snapshot())
        receipt["source_unchanged"] = receipt["source_after"] == before
        receipt["resource_environment"] = {key: os.environ.get(key) for key in [
            "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG"]}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
