#!/usr/bin/env python3
"""Run the declared original Windows regressions; retain every nonzero result."""

from __future__ import annotations
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
import time

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def assess(group: dict, returncode: int, log: str) -> dict:
    text = ANSI.sub("", log)
    starts = re.findall(r"Starting (\d+) tests across", text)
    selected = int(starts[-1]) if starts else None
    terminal = re.findall(
        r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
        r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
        text,
        re.MULTILINE,
    )
    observed = sorted({name for status, _, name in terminal if status != "SKIP"})
    missing = sorted(set(group["requiredTests"]) - set(observed))
    failures = sorted({name for status, _, name in terminal if status != "PASS"})
    matches = (
        selected == group["expectedTestCount"]
        and len(observed) == selected
        and not missing
        and all(package == group["package"] for _, package, _ in terminal)
    )
    return {
        "id": group["id"],
        "package": group["package"],
        "exitCode": returncode,
        "expectedTestCount": group["expectedTestCount"],
        "selectedTestCount": selected,
        "observedTests": observed,
        "missingRequiredTests": missing,
        "nonPassingTests": failures,
        "selectionMatches": matches,
        "passed": returncode == 0 and matches and not failures,
    }


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], cwd=root, text=True
    ).strip()


def source(root: Path) -> dict:
    lock = root / "codex-rs/Cargo.lock"
    return {
        "head": git(root, "rev-parse", "HEAD"),
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
        "trackedChanges": git(root, "status", "--porcelain", "--untracked-files=no"),
        "cargoLockSha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
    }


def valid_source(expected: str, before: dict, after: dict) -> bool:
    return (
        before == after and before["head"] == expected and not before["trackedChanges"]
    )


def execute_groups(
    root: Path, output: Path, groups: list[dict], invoke=None
) -> list[dict]:
    results = []
    for group in groups:
        command = [
            "just",
            "test",
            "--locked",
            "-p",
            group["package"],
            "--lib",
            "--cargo-profile",
            "dev-small",
            "-E",
            group["filter"],
            "--test-threads",
            "1",
            "--no-tests",
            "fail",
            "--retries",
            "0",
        ]
        path = output / (group["id"] + ".log")
        started = time.monotonic()
        if invoke is None:
            with path.open("w", encoding="utf-8") as stream:
                process = subprocess.run(
                    command,
                    cwd=root / "codex-rs",
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            code = process.returncode
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            code, text = invoke(command)
            path.write_text(text, encoding="utf-8")
        result = assess(group, code, text)
        result.update(
            command=command, durationSeconds=round(time.monotonic() - started, 3)
        )
        results.append(result)
        (output / "groups.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        print("\n".join(text.splitlines()[-35:]), flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if sys.platform != "win32":
        raise RuntimeError("this receipt requires an actual Windows runner")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise ValueError("expected source must be one full commit SHA")
    if output.is_relative_to(root):
        raise ValueError("diagnostics must stay outside the checkout")
    before = source(root)
    if before["head"] != args.expected_head or before["trackedChanges"]:
        raise RuntimeError("source differs from the requested clean head")
    output.mkdir(parents=True, exist_ok=True)
    (output / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")
    compiler = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
    (output / "compiler.txt").write_text(compiler)
    if not compiler.startswith("rustc 1.96.0 "):
        raise RuntimeError("native compiler differs from Rust 1.96.0")
    manifest = json.loads(
        (root / ".github/fixtures/windows-current-ci-scope.json").read_text()
    )
    temporary = {
        "originalTemp": os.environ.get("TEMP"),
        "originalTmp": os.environ.get("TMP"),
        "runnerTemp": os.environ.get("RUNNER_TEMP"),
    }
    # Exercise the unchanged canonical/reparse admission on an actual canonical
    # private test root. The runner's inherited TEMP may use a short-name alias.
    case_temp = Path(os.environ["RUNNER_TEMP"]) / "hepta-original-case-temp"
    case_temp.mkdir(exist_ok=False)
    native_temp = case_temp.resolve(strict=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(native_temp)
    temporary["physicalCaseTemp"] = str(native_temp)
    (output / "temporary-environment.json").write_text(
        json.dumps(temporary, indent=2) + "\n"
    )
    results = execute_groups(root, output, manifest["groups"])
    after = source(root)
    intact = valid_source(args.expected_head, before, after)
    passed = intact and all(result["passed"] for result in results)
    receipt = {
        "schema": "hepta.windows-current-ci-receipt.v1",
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "PASS_DECLARED_WINDOWS_SCOPE"
        if passed
        else "FAIL_DECLARED_WINDOWS_SCOPE",
        "sourceBefore": before,
        "sourceAfter": after,
        "sourceUnchanged": intact,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "temporaryEnvironment": temporary,
        "groups": results,
        "testRetries": 0,
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
