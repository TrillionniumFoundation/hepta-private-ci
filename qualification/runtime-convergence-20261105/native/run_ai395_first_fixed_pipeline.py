#!/usr/bin/env python3
"""Run one original-recipe native validation phase on the task-owned candidate.

Negative controls restore only production code, retain all candidate tests, and
restore the exact formatted candidate in finally. Each phase has its own durable
receipt; a nonzero Cargo/compiler exit alone is never called a successful red.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


TASK = Path("/home/qq/work/hepta-convergence-20261105-0c901b")
SOURCE = TASK / "source"
HEAD = "facba0d32c1cd0e8163a6186d7ba91fa311f2e2e"
BASE = "4e31abc907f09740d402d1ddef7a1d2fe0a366a6"
PACKAGES = [
    "codex-hepta-agentd", "codex-hepta-runtime",
    "codex-hepta-intelligence-eval", "codex-hepta-intelligence",
]
PATCHES_B64 = {'red-b1': 'LS0tIGEvY29kZXgtcnMvaGVwdGEtaW50ZWxsaWdlbmNlLWV2YWwvc3JjL3Byb2R1Y3RfcnVubmVyLnJzCisrKyBiL2NvZGV4LXJzL2hlcHRhLWludGVsbGlnZW5jZS1ldmFsL3NyYy9wcm9kdWN0X3J1bm5lci5ycwpAQCAtMzc0LDggKzM3NCw2IEBACiAgICAgICAgIHByb2R1Y3RfcGxhbi52YWxpZGF0ZV9pbnRlZ3JpdHkoKT87CiAgICAgICAgIGlmIGNhbmRpZGF0ZV9wbGFuLnBsYW5fZGlnZXN0ICE9IHByb2R1Y3RfcGxhbi5jYW5kaWRhdGVfdGVtcG9yYWxfcGxhbl9kaWdlc3QKICAgICAgICAgICAgIHx8IGJhc2VsaW5lX3BsYW4ucGxhbl9kaWdlc3QgIT0gcHJvZHVjdF9wbGFuLmJhc2VsaW5lX3RlbXBvcmFsX3BsYW5fZGlnZXN0Ci0gICAgICAgICAgICB8fCBjYW5kaWRhdGVfcGxhbi5wbGFuX2RpZ2VzdCAhPSBjYW5kaWRhdGVfcGxhbi5jYW5vbmljYWxfZGlnZXN0KCk/Ci0gICAgICAgICAgICB8fCBiYXNlbGluZV9wbGFuLnBsYW5fZGlnZXN0ICE9IGJhc2VsaW5lX3BsYW4uY2Fub25pY2FsX2RpZ2VzdCgpPwogICAgICAgICAgICAgfHwgY2FuZGlkYXRlX3BsYW4ub2JqZWN0aXZlX2RpZ2VzdCAhPSBwcm9kdWN0X3BsYW4uZnJvemVuX3BsYW4ub2JqZWN0aXZlX2RpZ2VzdAogICAgICAgICAgICAgfHwgYmFzZWxpbmVfcGxhbi5vYmplY3RpdmVfZGlnZXN0ICE9IHByb2R1Y3RfcGxhbi5mcm96ZW5fcGxhbi5vYmplY3RpdmVfZGlnZXN0CiAgICAgICAgIHsK', 'red-b2': 'LS0tIGEvY29kZXgtcnMvaGVwdGEtaW50ZWxsaWdlbmNlLWV2YWwvc3JjL3Byb2R1Y3RfcnVubmVyLnJzCisrKyBiL2NvZGV4LXJzL2hlcHRhLWludGVsbGlnZW5jZS1ldmFsL3NyYy9wcm9kdWN0X3J1bm5lci5ycwpAQCAtMjgsNyArMjgsNiBAQAogdXNlIGNyYXRlOjpGaW5hbEhvbGRvdXRKb3VybmFsUmVjZWlwdFYxOwogdXNlIGNyYXRlOjpIZWxkT3V0VGFyZ2V0OwogdXNlIGNyYXRlOjpJbmRlcGVuZGVudEV2YWx1YXRpb25CdW5kbGVWMTsKLXVzZSBjcmF0ZTo6SW5kZXBlbmRlbnRFdmFsdWF0aW9uRGlzcG9zaXRpb25WMTsKIHVzZSBjcmF0ZTo6TG9uZ2l0dWRpbmFsVGltZUV2aWRlbmNlVjE7CiB1c2UgY3JhdGU6Ok1ldHJpY0NvbnRyYWN0VjE7CiB1c2UgY3JhdGU6Ok1ldHJpY0dhdGVWMTsKQEAgLTU1MSw3ICs1NTAsNyBAQAogfQogCiBmbiBwcm9kdWN0X3F1YWxpZmljYXRpb25fZXZpZGVuY2VfZGlnZXN0KHJlY2VpcHQ6ICZQcm9kdWN0UXVhbGlmaWNhdGlvblJlY2VpcHRWMSkgLT4gRGlnZXN0MzIgewotICAgIGxldCBtdXQgYnl0ZXMgPSBiImhlcHRhLmludGVsbGlnZW5jZS1ldmFsLnByb2R1Y3QtcXVhbGlmaWNhdGlvbi52NCIudG9fdmVjKCk7CisgICAgbGV0IG11dCBieXRlcyA9IGIiaGVwdGEuaW50ZWxsaWdlbmNlLWV2YWwucHJvZHVjdC1xdWFsaWZpY2F0aW9uLnYzIi50b192ZWMoKTsKICAgICBmb3IgZGlnZXN0IGluIFsKICAgICAgICAgcmVjZWlwdC50ZW1wb3JhbF9leGVjdXRpb25fZGlnZXN0LAogICAgICAgICByZWNlaXB0Lm9iamVjdGl2ZV9kaWdlc3QsCkBAIC01NjMsMjMgKzU2Miw2IEBACiAgICAgXSB7CiAgICAgICAgIGJ5dGVzLmV4dGVuZF9mcm9tX3NsaWNlKGRpZ2VzdC5hc19hcnJheSgpKTsKICAgICB9Ci0gICAgLy8gVGhlIGV2YWx1YXRvciBldmlkZW5jZSBkaWdlc3QgaXMgb3BhcXVlIGhlcmUuIEJpbmQgdGhlIGNvbXBsZXRlIHB1YmxpYwotICAgIC8vIGRlY2lzaW9uIGFzIHdlbGwsIHNvIGNoYW5naW5nIGl0cyBkaXNwb3NpdGlvbiBvciBsaW5lYWdlIGNhbm5vdCBwcmVzZXJ2ZQotICAgIC8vIGEgdGVybWluYWwgcmVjZWlwdCB0aGF0IGRvd25zdHJlYW0gY29uc3VtZXJzIHRyZWF0IGFzIHF1YWxpZmllZC4KLSAgICBsZXQgZGVjaXNpb24gPSAmcmVjZWlwdC5kZWNpc2lvbi5kZWNpc2lvbjsKLSAgICBmb3IgaWQgaW4gWwotICAgICAgICAmZGVjaXNpb24uZXZhbHVhdGlvbl9pZCwKLSAgICAgICAgJmRlY2lzaW9uLmNhbmRpZGF0ZV9pZCwKLSAgICAgICAgJmRlY2lzaW9uLmJhc2VsaW5lX2lkLAotICAgIF0gewotICAgICAgICBwdXNoX2lkKCZtdXQgYnl0ZXMsIGlkKTsKLSAgICB9Ci0gICAgYnl0ZXMucHVzaChtYXRjaCBkZWNpc2lvbi5kaXNwb3NpdGlvbiB7Ci0gICAgICAgIEluZGVwZW5kZW50RXZhbHVhdGlvbkRpc3Bvc2l0aW9uVjE6OkVsaWdpYmxlRm9ySW5kZXBlbmRlbnRTZWxlY3Rpb24gPT4gMCwKLSAgICAgICAgSW5kZXBlbmRlbnRFdmFsdWF0aW9uRGlzcG9zaXRpb25WMTo6SW5lbGlnaWJsZSA9PiAxLAotICAgICAgICBJbmRlcGVuZGVudEV2YWx1YXRpb25EaXNwb3NpdGlvblYxOjpJbnN1ZmZpY2llbnRFdmlkZW5jZSA9PiAyLAotICAgIH0pOwotICAgIHB1c2hfaWRzKCZtdXQgYnl0ZXMsICZkZWNpc2lvbi5mYWlsZWRfbWV0cmljcyk7CiAgICAgcHVzaF9pZCgmbXV0IGJ5dGVzLCAmcmVjZWlwdC5jYW5kaWRhdGVfaWQpOwogICAgIHB1c2hfcHJpbmNpcGFsKCZtdXQgYnl0ZXMsICZyZWNlaXB0LmV2YWx1YXRvcik7CiAgICAgcHVzaF9wcmluY2lwYWwoJm11dCBieXRlcywgJnJlY2VpcHQuZ2VuZXJhdG9yKTsKQEAgLTU5NCw3ICs1NzYsNyBAQAogfQogCiBmbiBwcm9kdWN0X3F1YWxpZmljYXRpb25fc2VhbChyZWNlaXB0OiAmUHJvZHVjdFF1YWxpZmljYXRpb25SZWNlaXB0VjEpIC0+IERpZ2VzdDMyIHsKLSAgICBsZXQgbXV0IGJ5dGVzID0gYiJoZXB0YS5pbnRlbGxpZ2VuY2UtZXZhbC5wcm9kdWN0LXF1YWxpZmljYXRpb24tcmVjZWlwdC52MiIudG9fdmVjKCk7CisgICAgbGV0IG11dCBieXRlcyA9IGIiaGVwdGEuaW50ZWxsaWdlbmNlLWV2YWwucHJvZHVjdC1xdWFsaWZpY2F0aW9uLXJlY2VpcHQudjEiLnRvX3ZlYygpOwogICAgIGJ5dGVzLmV4dGVuZF9mcm9tX3NsaWNlKHByb2R1Y3RfcXVhbGlmaWNhdGlvbl9ldmlkZW5jZV9kaWdlc3QocmVjZWlwdCkuYXNfYXJyYXkoKSk7CiAgICAgYnl0ZXMuZXh0ZW5kX2Zyb21fc2xpY2UocmVjZWlwdC5ldmlkZW5jZV9kaWdlc3QuYXNfYXJyYXkoKSk7CiAgICAgRGlnZXN0MzI6Om9mX2J5dGVzKCZieXRlcykK'}
NEGATIVE_CASES = {
    "red-a": {
        "packages": ["codex-hepta-agentd"],
        "production": "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
        "tests": [
            "rejected_terminal_observation_preserves_recovered_uncertainty",
            "last_available_revision_accepts_terminal_observation_once",
            "cancellation_deadline_overflow_preserves_dispatched_run",
            "last_representable_cancel_deadline_remains_reconcilable",
            "revision_overflow_preserves_pre_dispatch_state",
            "revision_overflow_preserves_dispatched_and_cancelling_state",
            "bulk_deadline_error_retains_completed_prefix_and_failed_record",
            "bulk_unknown_error_retains_completed_prefix_and_failed_record",
        ],
    },
    "red-b1": {
        "packages": ["codex-hepta-intelligence-eval"],
        "production": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "tests": ["product_runner_rejects_changed_plans_before_consuming_or_releasing_holdout"],
    },
    "red-b2": {
        "packages": ["codex-hepta-intelligence-eval", "codex-hepta-intelligence"],
        "production": "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "tests": [
            "product_runner_binds_estimator_receipts_and_persists_signed_decision",
            "ineligible_qualification_cannot_be_relabelled_to_enter_ports_or_record_a_decision",
        ],
    },
    "red-c": {
        "packages": ["codex-hepta-runtime"],
        "production": "codex-rs/hepta-runtime/src/lib.rs",
        "tests": [
            "public_governed_topology_denies_before_grant_consumption_or_callbacks",
            "public_topology_recovery_denies_before_grant_consumption_or_callbacks",
        ],
    },
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main(phase):
    if phase not in {"desktop-regression", "green", "fix"}:
        raise SystemExit("unrecognized native phase")
    if (SOURCE / ".git/index.lock").exists():
        raise SystemExit("task checkout still locked")
    fmt_path = TASK / "evidence/native-desktop-source-v2/receipt.json"
    fmt = json.loads(fmt_path.read_text())
    if fmt.get("state") != "desktop-source-formatted":
        raise SystemExit("completed exact formatter receipt is required")
    expected = fmt["after"]
    if phase == "green-after-fix":
        fixed = json.loads((TASK / "evidence/native-fix-v1/receipt.json").read_text())
        if fixed.get("state") != "fix-complete":
            raise SystemExit("completed scoped fix receipt is required")
        expected = fixed["after"]
    expected_by_path = {item["path"]: item for item in expected}
    attempt = 2 if phase == "green" else 1
    evidence = TASK / "evidence" / f"native-{phase}-v{attempt}"
    evidence.mkdir(exist_ok=False)
    manifest = {
        "schema": "hepta.runtime-convergence-native-validation.v1",
        "phase": phase, "source": str(SOURCE), "implementation_commit": HEAD,
        "format_receipt_sha256": sha(fmt_path.read_bytes()),
        "state": "preflight", "steps": [], "source_before": expected,
        "negative_loops": "A failed test does not separately observe every loop branch.",
    }

    def save():
        (evidence / "receipt.json").write_text(json.dumps(manifest, indent=2) + "\n")

    env = os.environ.copy()
    toolchain_path = TASK / "evidence/ai395-tools-attempt-1/receipt.json"
    toolchain = json.loads(toolchain_path.read_text())
    if toolchain.get("state") not in {
        "ready-exact-native-tools"
    }:
        raise SystemExit("verified exact toolchain receipt is required")
    env["RUSTUP_HOME"] = toolchain["selected_rustup_home"]
    env["RUSTUP_TOOLCHAIN"] = "1.96.0"
    env["PATH"] = str(TASK / "tools/bin") + ":/home/qq/.cargo/bin:" + env.get("PATH", "/usr/bin:/bin")
    env["CARGO_BUILD_JOBS"] = "2"
    env["CARGO_TARGET_DIR"] = str(TASK / "target")
    env["GIT_TERMINAL_PROMPT"] = "0"
    repair_path = TASK / "evidence/clang-headers-attempt-1/receipt.json"
    repair = json.loads(repair_path.read_text())
    if repair.get("state") != "ready-task-local-clang-resource-headers":
        raise SystemExit("verified task-local Clang resource headers are required")
    if sha(Path(repair["stddef_header"]).read_bytes()) != repair["stddef_header_sha256"]:
        raise SystemExit("task-local Clang resource header changed")
    repair_args = repair["environment"]["BINDGEN_EXTRA_CLANG_ARGS"]
    if env.get("BINDGEN_EXTRA_CLANG_ARGS") not in {None, "", repair_args}:
        raise SystemExit("pre-existing bindgen arguments differ from the approved environment repair")
    env["BINDGEN_EXTRA_CLANG_ARGS"] = repair_args
    manifest["environment_repair"] = {
        "receipt_sha256": sha(repair_path.read_bytes()),
        "package": repair["package"], "version": repair["version"],
        "apt_expected_sha256": repair["apt_expected_sha256"],
        "resource_directory": repair["resource_directory"],
        "BINDGEN_EXTRA_CLANG_ARGS": repair_args,
        "repository_source_or_features_changed": False,
    }
    openssl_path = TASK / "evidence/openssl-dev-attempt-1/receipt.json"
    openssl = json.loads(openssl_path.read_text())
    if openssl.get("state") != "ready-task-local-matched-openssl-development-prefix":
        raise SystemExit("verified matching task-local OpenSSL development prefix is required")
    openssl_libdir = Path(openssl["environment"]["OPENSSL_LIB_DIR"])
    for library in openssl["runtime_library_identity"]:
        if sha((openssl_libdir / library["name"]).read_bytes()) != library["sha256"]:
            raise SystemExit("task-local matched OpenSSL runtime changed")
    for key, value in openssl["environment"].items():
        if env.get(key) not in {None, "", value}:
            raise SystemExit("pre-existing OpenSSL environment differs from approved repair: " + key)
        env[key] = value
    manifest["openssl_environment_repair"] = {
        "receipt_sha256": sha(openssl_path.read_bytes()),
        "version": openssl["version"],
        "apt_expected_sha256": openssl["apt_expected_sha256"],
        "runtime_library_identity": openssl["runtime_library_identity"],
        "environment": openssl["environment"],
        "repository_source_features_or_backend_changed": False,
    }
    manifest["environment"] = {key: env[key] for key in (
        "RUSTUP_HOME", "RUSTUP_TOOLCHAIN", "CARGO_BUILD_JOBS", "CARGO_TARGET_DIR",
        "BINDGEN_EXTRA_CLANG_ARGS",
        "OPENSSL_LIB_DIR", "OPENSSL_INCLUDE_DIR", "CPATH",
    )}
    manifest["inherited_compile_options"] = {
        key: value for key, value in env.items()
        if key in {"RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"}
        or key.startswith("CARGO_PROFILE_")
    }
    save()

    def run(name, args, *, required=True, stdin=None, cwd=SOURCE):
        out, err = evidence / f"{name}.stdout", evidence / f"{name}.stderr"
        started = time.time()
        print(json.dumps({"stage": "start", "name": name, "args": args}), flush=True)
        with out.open("wb") as stdout, err.open("wb") as stderr:
            result = subprocess.run(args, cwd=cwd, env=env, stdout=stdout,
                                    stderr=stderr, input=stdin)
        item = {"name": name, "args": args, "exit_code": result.returncode,
                "elapsed_seconds": time.time() - started,
                "stdout_sha256": sha(out.read_bytes()),
                "stderr_sha256": sha(err.read_bytes())}
        manifest["steps"].append(item)
        save()
        print(json.dumps(item), flush=True)
        if required and result.returncode:
            print(err.read_text(errors="replace")[-12000:], flush=True)
            raise RuntimeError(f"{name} failed with exit {result.returncode}")
        return result.returncode, out.read_bytes(), err.read_bytes()

    def check_candidate():
        for path, item in expected_by_path.items():
            if sha((SOURCE / path).read_bytes()) != item["sha256"]:
                raise RuntimeError(f"candidate source drift: {path}")

    def snapshot():
        return [{"path": path, "sha256": sha((SOURCE / path).read_bytes())}
                for path in expected_by_path]

    backup = None
    mutated_path = None
    mutated_digest = None
    lock_before = (SOURCE / "codex-rs/Cargo.lock").read_bytes()
    try:
        check_candidate()
        _, head, _ = run("head", ["git", "rev-parse", "HEAD"])
        if head.decode().strip() != HEAD:
            raise RuntimeError("candidate HEAD is not the fixed implementation commit")
        _, rustc, _ = run("rustc", ["rustc", "-Vv"], cwd=SOURCE / "codex-rs")
        _, cargo, _ = run("cargo", ["cargo", "-V"], cwd=SOURCE / "codex-rs")
        if not rustc.startswith(b"rustc 1.96.0 ") or not cargo.startswith(b"cargo 1.96.0 "):
            raise RuntimeError("native invocation did not select exact Rust/Cargo 1.96.0")
        manifest["versions"] = {"rustc": rustc.decode().strip(), "cargo": cargo.decode().strip()}
        _, changed, _ = run("preflight-changed", ["git", "diff", "--name-only", "-z"])
        if set(changed.decode().split("\0")) - set(expected_by_path) - {""}:
            raise RuntimeError("unexpected pre-existing tracked change")

        if phase in NEGATIVE_CASES:
            case = NEGATIVE_CASES[phase]
            mutated_path = SOURCE / case["production"]
            backup = mutated_path.read_bytes()
            (evidence / "production-before.rs").write_bytes(backup)
            manifest["state"] = "preparing-negative-control"
            manifest["production_path"] = case["production"]
            save()
            if phase == "red-a":
                _, old, _ = run("original-production", ["git", "show", f"{BASE}:{case['production']}"])
                mutated_path.write_bytes(old)
            elif phase in PATCHES_B64:
                patch = base64.b64decode(PATCHES_B64[phase])
                (evidence / "negative.patch").write_bytes(patch)
                run("negative-apply-check", ["git", "apply", "--check", "-"], stdin=patch)
                run("negative-apply", ["git", "apply", "-"], stdin=patch)
            else:
                guard = b"        topology_execution::require_control_lifecycle_admission_v1()?;\n"
                if backup.count(guard) != 2:
                    raise RuntimeError("expected exactly two public lifecycle guards")
                mutated_path.write_bytes(backup.replace(guard, b""))
            mutated_digest = sha(mutated_path.read_bytes())
            manifest["negative_production_sha256"] = mutated_digest
            if mutated_digest == sha(backup):
                raise RuntimeError("negative control did not alter production code")
            for path, item in expected_by_path.items():
                if path != case["production"] and sha((SOURCE / path).read_bytes()) != item["sha256"]:
                    raise RuntimeError(f"negative control changed unrelated source or tests: {path}")
            tests = case["tests"]
            expression = "test(/(^|::)(" + "|".join(tests) + ")$/)"
            command = ["just", "test", "--locked"]
            for package in case["packages"]:
                command.extend(["-p", package])
            command.extend(["-E", expression])
            manifest["requested_tests"] = tests
            manifest["state"] = "negative-control-running"
            save()
            code, stdout, stderr = run("just-test", command, required=False)
            clean = re.sub(r"\x1b\[[0-9;]*m", "", (stdout + b"\n" + stderr).decode(errors="replace"))
            fail_lines = [line for line in clean.splitlines() if re.search(r"\bFAIL\b", line)]
            observed = [name for name in tests if any(name in line for line in fail_lines)]
            manifest["test_exit_code"] = code
            manifest["observed_named_failures"] = observed
            manifest["failure_lines"] = fail_lines[-30:]
            manifest["state"] = (
                "named-test-failure-observed-review-required" if code and observed
                else "negative-control-did-not-prove-test-failure"
            )
            # Actual assertion and failure location must be reviewed before
            # counting the negative control as regression evidence.
            result = 0 if code and observed else 1
        else:
            command = ["just", "fix" if phase == "fix" else "test", "--locked"]
            selected_packages = ["codex-hepta-agentd"] if phase == "desktop-regression" else PACKAGES
            for package in selected_packages:
                command.extend(["-p", package])
            if phase == "desktop-regression":
                command.extend(["-E", "test(/(^|::)(desktop_policy_two_successors_keep_one_original_issuer_then_revocation_fences_the_pair)$/)"])
            manifest["state"] = "running-" + phase
            save()
            code, positive_stdout, positive_stderr = run("just-" + phase, command, required=False)
            manifest["command_exit_code"] = code
            if phase == "fix":
                run("just-fmt-after-fix", ["just", "fmt", "--base", BASE])
                _, paths, _ = run("changed-after-fix", ["git", "diff", "--name-only", "-z"])
                unexpected = set(paths.decode().split("\0")) - set(expected_by_path) - {""}
                _, patch, _ = run("fix-patch", ["git", "diff", "--binary", "--no-ext-diff"])
                (evidence / "native-fix.patch").write_bytes(patch)
                manifest["unexpected_changed_paths"] = sorted(unexpected)
                manifest["after"] = snapshot()
                manifest["source_changed_by_fix"] = any(
                    item["sha256"] != expected_by_path[item["path"]]["sha256"]
                    for item in manifest["after"]
                )
                manifest["state"] = "fix-complete" if code == 0 and not unexpected else "fix-blocked"
                result = 0 if manifest["state"] == "fix-complete" else 1
            else:
                check_candidate()
                clean = re.sub(r"\x1b\[[0-9;]*m", "", (positive_stdout + b"\n" + positive_stderr).decode(errors="replace"))
                summaries = list(re.finditer(r"Summary\s+\[[^\n]+?\]\s+(\d+) tests? run:([^\n]+)", clean))
                run_count = int(summaries[-1].group(1)) if summaries else 0
                required = (["desktop_policy_two_successors_keep_one_original_issuer_then_revocation_fences_the_pair"]
                            if phase == "desktop-regression" else
                            [name for case in NEGATIVE_CASES.values() for name in case["tests"]] + ["desktop_policy_two_successors_keep_one_original_issuer_then_revocation_fences_the_pair"])
                pass_lines = [line for line in clean.splitlines() if re.match(r"^\s*(?:TRY \d+ )?(?:PASS|FLAKY)\b", line)]
                observed = [name for name in required if any(re.search(r"(?:\s|::)" + re.escape(name) + r"\s*$", line) for line in pass_lines)]
                passed = code == 0 and run_count > 0 and set(observed) == set(required)
                if phase == "desktop-regression":
                    passed = passed and run_count == 1
                manifest["positive_observation"] = {"summary": summaries[-1].group(0) if summaries else None,
                    "run_count": run_count, "required_tests": required, "observed_passes": observed}
                label = "desktop-regression" if phase == "desktop-regression" else "green"
                manifest["state"] = label + "-complete" if passed else label + "-failed"
                result = 0 if passed else 1
        if (SOURCE / "codex-rs/Cargo.lock").read_bytes() != lock_before:
            raise RuntimeError("Cargo.lock changed during the native phase")
        manifest["exit_code"] = result
    except Exception as error:
        manifest["state"] = "native-phase-blocked"
        manifest["error"] = str(error)
        manifest["exit_code"] = 1
        result = 1
    finally:
        if backup is not None and mutated_path is not None:
            current = mutated_path.read_bytes()
            if mutated_digest is None or sha(current) in {mutated_digest, sha(backup)}:
                mutated_path.write_bytes(backup)
                manifest["restored_candidate"] = sha(mutated_path.read_bytes()) == sha(backup)
            else:
                manifest["restored_candidate"] = False
                manifest["restore_refusal"] = "production changed unexpectedly during negative test"
                manifest["exit_code"] = 1
                result = 1
        save()
        print(json.dumps(manifest), flush=True)
    return result


if __name__ == "__main__":
    for native_phase in ("desktop-regression", "green", "fix"):
        outcome = main(native_phase)
        if outcome:
            sys.exit(outcome)
    sys.exit(0)
