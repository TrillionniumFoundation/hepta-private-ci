#!/usr/bin/env python3
"""Run original private-state and Agentd consumers on the dependency union."""
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
    "codex-rs", "justfile", "defs.bzl", "MODULE.bazel", "MODULE.bazel.lock",
    ".bazelrc", ".bazelversion", "bazel", "patches", "third_party/dbus",
    "scripts/run-nextest.py", "scripts/just-shell.py", "scripts/check-module-bazel-lock.sh",
    ".github/actions/prepare-bazel-ci", ".github/actions/setup-ci", ".github/actions/setup-bazel-ci",
    ".github/scripts/run_bazel_with_buildbuddy.py",
    ".github/scripts/check_windows_private_state_acquisition.py",
    ".github/scripts/test_check_windows_private_state_acquisition.py",
    ".github/fixtures/windows-private-state-acquisition",
    "qualification/keyring-sync-provider/build_pinned_client.py",
    "qualification/windows-private-state-current",
    ".github/workflows/hepta-windows-private-state-qualification.yml",
]
PACKAGES = ["codex-utils-path", "codex-hepta-contracts", "codex-hepta-prompt-registry", "codex-hepta-agentd"]
REQUIRED = {
    "codex-utils-path": set(),
    "codex-hepta-contracts": {"agent_id::tests::canonical_id_is_stable_across_display_parse_and_serde"},
    "codex-hepta-prompt-registry": set(),
    "codex-hepta-agentd": {
        "control::native_tests::ordinary_control_preserves_server_identity_and_launch_generation",
        "control::native_tests::saturated_ordinary_control_returns_original_overload_and_recovers",
        "control::peer_auth_tests::control_peer_check_runs_before_control_frames",
        "cognitive_ranker::tests::running_socket_uses_launch_bound_model_and_isolates_ranker_revocation",
    },
}
WINDOWS_REQUIRED = {
    "codex-utils-path": {
        "private_state_windows::directory::tests::rejects_ancestor_substitution_at_retained_open",
        "private_state_windows::directory::tests::rejects_junction_before_creating_private_leaf",
        "private_state_windows::tests::retained_directory_pins_root_and_ancestor_until_drop",
        "private_state_windows::security_tests::opening_existing_objects_never_rewrites_their_security",
    },
    "codex-hepta-contracts": {
        "final_use::store::windows::tests::windows_nonce_burn_persists_across_real_private_store_reopen",
        "final_use::store::windows::tests::windows_final_use_denies_issuer_or_epoch_substitution",
        "final_use::store::windows::tests::windows_final_use_rejects_hardlinked_claims_before_nonce_replay",
        "authority_lease::windows::tests::private_authority_lease_roundtrip_reopens_with_exact_frontier",
        "authority_lease::windows::tests::hardlink_alias_of_authority_state_is_rejected_before_reopen",
    },
    "codex-hepta-prompt-registry": {
        "durable::windows::tests::full_private_registry_roundtrip_reopens_without_resetting_owner_history",
        "durable::windows::tests::hard_link_is_rejected_before_registry_bytes_are_read",
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
    required = REQUIRED[package] | (WINDOWS_REQUIRED.get(package, set()) if os.name == "nt" else set())
    result = {"count": len(cases), "names": sorted(names), "failed_or_skipped": invalid,
              "sha256": digest(raw), "required_present": required <= names}
    if (not cases or int(tree.get("tests", "-1")) != len(cases)
            or len(names) != len(cases) or invalid or not result["required_present"]):
        raise RuntimeError(f"{package}: failed, skipped, duplicate or missing original tests")
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
               "scope": "Original complete four libraries and acquisition negative controls; not whole CI or production admission."}

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
        if os.environ.get("HEPTA_EXPECTED_COMMIT", commit) != commit:
            raise RuntimeError("checked out source is not the requested immutable commit")
        run("initial-tracked-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD"], ROOT)
        if args.mode == "bazel":
            old_lock = (ROOT / "MODULE.bazel.lock").read_bytes()
            first = run("committed-lock-first", ["just", "bazel-lock-check"], ROOT, required=False)
            run("original-lock-update", ["just", "bazel-lock-update"], ROOT)
            lock = (ROOT / "MODULE.bazel.lock").read_bytes()
            (output / "MODULE.bazel.lock").write_bytes(lock)
            receipt["generated_lock"] = {"bytes": len(lock), "sha256": digest(lock), "equals_committed": lock == old_lock}
            run("original-lock-check", ["just", "bazel-lock-check"], ROOT)
            if first or lock != old_lock:
                raise RuntimeError("actual generated lock must be adopted and committed-first validation rerun")
            targets = ["//codex-rs/utils/path-utils:path-utils-unit-tests",
                       "//codex-rs/hepta-contracts:hepta-contracts-unit-tests",
                       "//codex-rs/hepta-prompt-registry:hepta-prompt-registry-unit-tests",
                       "//codex-rs/hepta-agentd:hepta-agentd-unit-tests"]
            wrapper = str(ROOT / ".github/scripts/run_bazel_with_buildbuddy.py")
            run("original-private-state-targets", [sys.executable, wrapper, "test", "--nocache_test_results", "--test_output=all", *targets], ROOT)
        else:
            run("rustc-version", ["rustc", "--version", "--verbose"])
            if not (output / "rustc-version.log").read_text().startswith("rustc 1.96.0 "):
                raise RuntimeError("qualification requires the actual selected Rust 1.96.0")
            metadata = subprocess.run(["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"], cwd=WORKSPACE, capture_output=True)
            (output / "metadata.stderr").write_bytes(metadata.stderr)
            (output / "metadata.json.gz").write_bytes(gzip.compress(metadata.stdout, mtime=0))
            receipt["metadata"] = {"exit_code": metadata.returncode, "sha256": digest(metadata.stdout)}
            if metadata.returncode:
                raise RuntimeError("the actual locked workspace graph failed")
            receipt["metadata"]["package_count"] = len(json.loads(metadata.stdout)["packages"])
            if sys.platform.startswith("linux"):
                native = output.parent / "private-state-pinned-dbus-client"
                try:
                    run("pinned-dbus-client", [sys.executable, str(ROOT / "qualification/keyring-sync-provider/build_pinned_client.py"), "--output", str(native)])
                finally:
                    if (native / "receipt.json").is_file():
                        shutil.copyfile(native / "receipt.json", output / "pinned-dbus-receipt.json")
                os.environ["PKG_CONFIG_PATH"] = str(native / "lib/pkgconfig")
            if os.name == "nt":
                run("acquisition-verifier-controls", [sys.executable, "-m", "unittest", "discover", "-s", ".github/scripts", "-p", "test_check_windows_private_state_acquisition.py", "-v"], ROOT)
                run("actual-acquisition-attacks", [sys.executable, str(ROOT / ".github/scripts/check_windows_private_state_acquisition.py"), str(output / "acquisition")], ROOT)
                acquisition = json.loads((output / "acquisition/manifest.json").read_bytes())
                if not acquisition["qualified"] or not acquisition["restored"] or acquisition["source_head"] != commit:
                    raise RuntimeError("original acquisition controls did not qualify or restore the exact source")
            receipt["tests"] = {}
            for package in PACKAGES:
                junit = WORKSPACE / "target/nextest/local/junit.xml"
                junit.unlink(missing_ok=True)
                argv = ["just", "test", "--locked", "-p", package, "--lib", "--no-tests=fail", "--retries", "0", "--success-output=final"]
                if package == "codex-hepta-agentd":
                    argv += ["--test-threads", "1"]
                code = run(package, argv, required=False)
                receipt["tests"][package] = read_junit(junit, output, package)
                if "skipping test:" in (output / f"{package}.log").read_text(errors="replace").lower():
                    raise RuntimeError("an existing test returned early without its original operation")
                if code:
                    raise RuntimeError(f"original {package} library tests exited {code}")
            run("scoped-clippy-fix", ["just", "fix", "--locked", *[arg for package in PACKAGES for arg in ["-p", package]], "--no-deps"])
        receipt["source_after"] = snapshot()
        if receipt["source_after"] != before:
            raise RuntimeError("qualification modified a bound production or harness input")
        run("final-tracked-source", ["git", "--no-replace-objects", "diff", "--exit-code", "HEAD"], ROOT)
        receipt["status"] = "passed"
    finally:
        receipt.setdefault("source_after", snapshot())
        receipt["source_unchanged"] = receipt["source_after"] == before
        receipt["resource_environment"] = {key: os.environ.get(key) for key in ["CARGO_BUILD_JOBS", "CARGO_INCREMENTAL", "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG"]}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
