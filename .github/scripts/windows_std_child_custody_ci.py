#!/usr/bin/env python3
"""Qualify the new synchronous child owner separately from the original167."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

from aggregate_windows_current_ci import read_bytes
from aggregate_windows_current_ci import single_nextest_run
from windows_current_ci import execute_groups
from windows_current_ci import selected_groups
from windows_current_ci import source
from windows_current_ci import valid_source


CASES = (
    "std_child_custody::tests::normal_leader_exit_cleans_descendants_and_preserves_an_unrelated_owner",
    "std_child_custody::tests::explicit_cleanup_kills_the_live_leader_and_its_descendant",
    "std_child_custody::tests::dropping_the_owner_cleans_its_live_descendant",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if sys.platform != "win32":
        raise RuntimeError("the new child-owner receipt requires actual Windows")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise ValueError("expected source must be one full commit SHA")
    if output.is_relative_to(root):
        raise ValueError("native evidence must stay outside the checkout")
    target = Path(os.environ["CARGO_TARGET_DIR"]).resolve()
    if target.is_relative_to(root):
        raise ValueError("this qualification requires its own target outside the checkout")
    workflow = {
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runnerName": os.environ.get("RUNNER_NAME"),
        "runnerOs": os.environ.get("RUNNER_OS"),
    }
    if (
        not all(re.fullmatch(r"[1-9][0-9]*", workflow[key] or "") for key in ("runId", "runAttempt"))
        or not workflow["runnerName"]
        or workflow["runnerOs"] != "Windows"
    ):
        raise RuntimeError("a current native Windows workflow identity is required")
    before = source(root)
    if before["head"] != args.expected_head or before["trackedChanges"]:
        raise RuntimeError("source differs from the requested clean head")
    output.mkdir(parents=True, exist_ok=False)
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")
    results = []
    error = None
    original_manifest_sha = None
    compiler_sha = None
    nextest_run = None
    try:
        compiler = subprocess.check_output(["rustc", "--version", "--verbose"])
        (output / "compiler.txt").write_bytes(compiler)
        compiler_sha = hashlib.sha256(compiler).hexdigest()
        if not compiler.startswith(b"rustc 1.96.0 "):
            raise RuntimeError("native compiler differs from Rust 1.96.0")
        original = (root / ".github/fixtures/windows-current-ci-scope.json").read_bytes()
        # Validate, but never extend, the existing 19-group/167-case partition.
        selected_groups(json.loads(original))
        original_manifest_sha = hashlib.sha256(original).hexdigest()
        group = {
            "id": "std-child-custody-owner",
            "package": "codex-utils-pty",
            "expectedTestCount": len(CASES),
            "requiredTests": list(CASES),
            "filter": " | ".join(f"test(={name})" for name in CASES),
        }
        # Reuse the exact existing Windows command/profile and strict result
        # assessment. Missing, failing, skipped or LEAK cases cannot pass.
        results = execute_groups(root, output, [group])
        raw = read_bytes(output / (group["id"] + ".log"))
        if len(results) != 1 or hashlib.sha256(raw).hexdigest() != results[0]["logSha256"]:
            raise ValueError("the actual new child-owner log does not match its receipt")
        nextest_run = single_nextest_run(group, raw.decode("utf-8"))
    except Exception as failure:
        error = {"type": type(failure).__name__, "message": str(failure)}
    after = None
    after_error = None
    try:
        after = source(root)
    except Exception as failure:
        after_error = {"type": type(failure).__name__, "message": str(failure)}
    (output / "source-after.json").write_text(json.dumps(after, indent=2) + "\n")
    intact = after is not None and valid_source(args.expected_head, before, after)
    passed = (
        error is None and intact and nextest_run is not None
        and len(results) == 1 and results[0]["passed"]
    )
    receipt = {
        "schema": "hepta.windows-std-child-custody-native.v1",
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "workflow": workflow,
        "status": "PASS_NEW_CHILD_OWNER_SCOPE" if passed else "FAIL_NEW_CHILD_OWNER_SCOPE",
        "sourceBefore": before,
        "sourceAfter": after,
        "sourceAfterError": after_error,
        "sourceUnchanged": intact,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "nativePaths": {"checkout": str(root), "target": str(target)},
        "compilerSha256": compiler_sha,
        "originalScopeManifestSha256": original_manifest_sha,
        "original167ExecutedByThisJob": False,
        "groups": results,
        "singleNextestRun": nextest_run,
        "error": error,
        "testRetries": 0,
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
