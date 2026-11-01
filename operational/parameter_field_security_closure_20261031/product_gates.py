"""Run actual product regressions or regenerate and verify the real Bazel lock."""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import tarfile
import time

from . import prepare
from . import resolve
from . import semantic


PRODUCT_GROUPS = (
    ("zip_permission_boundary", "codex-core-plugins",
     "test(=startup_sync::zip_tests::extract_zipball_strips_privileged_modes_and_preserves_regular_permissions)",
     ("extract_zipball_strips_privileged_modes_and_preserves_regular_permissions",)),
    ("zip_existing_product_paths", "codex-core-plugins", "test(startup_sync::tests::)", ()),
    ("aws_product_signing", "codex-aws-auth", None,
     ("sign_adds_sigv4_headers_and_preserves_existing_headers", "sign_includes_session_token_when_credentials_have_one")),
    ("matrix_product_adapter", "codex-hepta-matrix-sdk", None, ()),
)


def run(root, resolved, output, phase, expected_machine):
    root, resolved, output = root.resolve(), resolved.resolve(), output.resolve()
    if output.exists() or root == output or root in output.parents:
        raise ValueError("product gate evidence directory must be new and external")
    output.mkdir(parents=True)
    plan = json.loads((prepare.HERE / "INPUTS.json").read_text())
    capture = resolve.load_module(root, "scripts/capture_cargo_deny_diagnostic.py", "product_capture", plan["capture_git_blob"])
    receipt = {"schema": "hepta.dependency-security-product-gate.1", "phase": phase,
               "status": "in_progress", "qualification": False, "commands": [], "tests": {},
               "source_head": prepare.git(root, "rev-parse", "HEAD").decode().strip(),
               "machine": platform.machine(), "run_id": os.environ.get("GITHUB_RUN_ID"),
               "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    started = time.monotonic()

    def save():
        receipt["wall_seconds"] = time.monotonic() - started
        (output / "PRODUCT_GATE.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    def invoke(label, command, cwd=root, timeout=1800):
        save()
        result = capture.capture(command, cwd, output, label, timeout=timeout, limit=32 * 1024 * 1024)
        result["label"] = label
        receipt["commands"].append(result)
        save()
        if result["exit_code"] or result["timed_out"]:
            raise ValueError("actual product gate command failed: " + label)
        return result

    save()
    try:
        if platform.machine() != expected_machine:
            raise ValueError("actual runner architecture differs from the declared gate")
        resolver = semantic.restore_candidate(root, resolved, plan)
        receipt["product_cargo_lock"] = resolver["cargo_lock"]
        before_lock = (root / "codex-rs/Cargo.lock").read_bytes()
        before_bazel = (root / "MODULE.bazel.lock").read_bytes()
        (output / "Cargo.lock").write_bytes(before_lock)
        (output / "MODULE.bazel.lock.before").write_bytes(before_bazel)
        invoke("locked_product_metadata", ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"],
               root / "codex-rs", 1200)
        if phase == "product":
            junit = root / "codex-rs/target/nextest/local/junit.xml"
            for label, package, expression, required in PRODUCT_GROUPS:
                if junit.exists():
                    raise ValueError("unexpected stale product JUnit evidence")
                command = ["just", "test", "--locked", "--lib", "-p", package, "--retries", "0",
                           "--test-threads", "1" if label == "zip_permission_boundary" else "2",
                           "--no-tests=fail", "--failure-output", "immediate", "--success-output", "immediate"]
                if expression:
                    command += ["-E", expression]
                invoke(label, command, timeout=3000)
                retained = output / (label + ".junit.xml")
                if not junit.is_file():
                    raise ValueError("actual product regression produced no JUnit")
                shutil.copyfile(junit, retained)
                receipt["tests"][label] = semantic.check_tests(retained, required)
                junit.unlink()
                save()
            for path, expected in plan["candidate_files"].items():
                prepare.check((root / path).read_bytes(), expected, path)
        elif phase == "bazel":
            # Run the repository's actual requested formatter. Retain every
            # resulting byte change; never relabel this as the earlier tested
            # unformatted source identity or silently rewrite the source plan.
            before = {path: (root / path).read_bytes() for path in plan["candidate_files"]}
            invoke("repository_just_fmt", ["just", "fmt"], timeout=1200)
            invoke("repository_just_fmt_check", ["just", "fmt", "--check"], timeout=1200)
            changes = {}
            for path, previous in before.items():
                current = (root / path).read_bytes()
                if current != previous:
                    if not path.endswith(".rs"):
                        raise ValueError("Rust formatter changed non-Rust candidate data")
                    changes[path] = {"before": prepare.identity(previous), "after": prepare.identity(current)}
            (output / "FORMAT_DELTA.json").write_text(json.dumps(changes, indent=2, sort_keys=True) + "\n")
            receipt["format_changes"] = changes
            receipt["formatted_source_adoption_requires_review"] = bool(changes)
            invoke("bazel_lock_update", ["just", "bazel-lock-update"], timeout=1800)
            updated = (root / "MODULE.bazel.lock").read_bytes()
            (output / "MODULE.bazel.lock").write_bytes(updated)
            invoke("bazel_lock_check", ["just", "bazel-lock-check"], timeout=1200)
            if (root / "MODULE.bazel.lock").read_bytes() != updated:
                raise ValueError("Bazel check changed the freshly generated lock")
            receipt["bazel_lock"] = prepare.identity(updated)
            receipt["bazel_lock_before"] = prepare.identity(before_bazel)
            files = sorted(set(plan["candidate_files"]) | {"codex-rs/Cargo.lock", "MODULE.bazel.lock"})
            identities = {path: prepare.identity((root / path).read_bytes()) for path in files}
            (output / "FORMATTED_SOURCE_MANIFEST.json").write_text(json.dumps(identities, indent=2, sort_keys=True) + "\n")
            with tarfile.open(output / "FORMATTED_SOURCE.tar.gz", "w:gz") as archive:
                for path in files:
                    archive.add(root / path, arcname=path, recursive=False)
            receipt["formatted_source_archive"] = prepare.identity((output / "FORMATTED_SOURCE.tar.gz").read_bytes())
        else:
            raise ValueError("unknown product qualification phase")
        if (root / "codex-rs/Cargo.lock").read_bytes() != before_lock:
            raise ValueError("a product gate changed the resolved Cargo lock")
        for path in plan["policy_files_unchanged"] + ["codex-rs/keyring-store/Cargo.toml", "codex-rs/keyring-store/src/lib.rs"]:
            prepare.check((root / path).read_bytes(), plan["base_files"][path], path)
        receipt["status"] = "complete"
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)
        raise
    finally:
        if (root / "MODULE.bazel.lock").is_file():
            (output / "MODULE.bazel.lock.observed").write_bytes((root / "MODULE.bazel.lock").read_bytes())
        save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("product", "bazel"), required=True)
    parser.add_argument("--expected-machine", choices=("x86_64", "aarch64"), required=True)
    args = parser.parse_args()
    result = run(args.repo, args.resolved, args.output, args.phase, args.expected_machine)
    print(json.dumps({"phase": args.phase, "status": result["status"], "qualification": False}))


if __name__ == "__main__":
    main()
