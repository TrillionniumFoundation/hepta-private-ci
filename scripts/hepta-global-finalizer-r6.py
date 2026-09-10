#!/usr/bin/env python3
"""Qualify every canonical Hepta workspace package on one final candidate tree."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path.cwd()
OUT = ROOT / "qualification" / "global-gap-closure-final-r6"
TARGET = os.environ.get(
    "HEPTA_FINAL_TARGET",
    "integration/hepta-all-gap-closure-20260910-r6",
)
SOURCE_CANDIDATES = (
    "origin/integration/hepta-global-gap-closure-20260910-r5-local",
    "origin/integration/hepta-global-gap-closure-20260910-r4",
    "origin/integration/hepta-global-gap-closure-20260910-r3",
    "origin/integration/hepta-global-gap-closure-20260910",
)
VERIFY_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/hepta-readiness.py", "self-test"),
    ("python3", "scripts/hepta-readiness.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-readiness.py", "verify"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "self-test"),
    (
        "python3",
        "scripts/hepta-implementation-dossiers.py",
        "generate-status",
        "--check",
    ),
    ("python3", "scripts/hepta-implementation-dossiers.py", "verify"),
    ("python3", "scripts/hepta-technical-closure.py", "self-test"),
    ("python3", "scripts/hepta-technical-closure.py", "verify"),
    (
        "python3",
        "qualification/module-execution-dossiers/implementation_contracts.py",
        "self-test",
    ),
    (
        "python3",
        "qualification/module-execution-dossiers/implementation_contracts.py",
        "verify-repository",
    ),
    ("python3", "scripts/hepta-module-docs.py", "self-test"),
    ("python3", "scripts/hepta-module-docs.py", "verify"),
    ("python3", "scripts/hepta-algorithm-docs.py", "self-test"),
    ("python3", "scripts/hepta-algorithm-docs.py", "verify-sources"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-algorithm-docs.py", "verify"),
    ("python3", "scripts/hepta-cns.py", "self-test"),
    ("python3", "scripts/hepta-cns.py", "generate-status", "--check"),
    ("python3", "scripts/hepta-cns.py", "verify"),
    ("python3", "scripts/hepta-hnmf.py", "self-test"),
    ("python3", "scripts/hepta-hnmf.py", "verify"),
    ("python3", "scripts/hepta-docs.py", "self-test"),
    ("python3", "scripts/hepta-docs.py", "verify"),
)
GENERATORS: tuple[tuple[str, ...], ...] = (
    ("python3", "scripts/hepta-readiness.py", "generate-status"),
    ("python3", "scripts/hepta-implementation-dossiers.py", "generate-status"),
    ("python3", "scripts/hepta-algorithm-docs.py", "generate-status"),
    ("python3", "scripts/hepta-cns.py", "generate-status"),
    ("python3", "scripts/hepta-docs.py", "generate-status"),
)


def run(argv: Iterable[str], *, timeout: int = 7200) -> dict[str, Any]:
    args = tuple(argv)
    print("+", shlex.join(args), flush=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        code = completed.returncode
        output = completed.stdout
    except subprocess.TimeoutExpired as error:
        code = 124
        output = (error.stdout or "") + "\nTIMEOUT\n"
    print(output[-12000:], flush=True)
    return {
        "command": list(args),
        "returnCode": code,
        "durationSeconds": round(time.monotonic() - started, 3),
        "outputSha256": hashlib.sha256(
            output.encode("utf-8", errors="replace")
        ).hexdigest(),
        "tail": output.splitlines()[-60:],
    }


def git(*args: str, timeout: int = 1200) -> dict[str, Any]:
    return run(("git", *args), timeout=timeout)


def git_ok(*args: str) -> bool:
    return git(*args)["returnCode"] == 0


def git_text(*args: str) -> str:
    result = git(*args)
    if result["returnCode"] != 0:
        raise RuntimeError(f"git command failed: {args}")
    # The bounded tail contains all output for short plumbing commands.
    return "\n".join(result["tail"]).strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_json(output_lines: list[str]) -> dict[str, Any]:
    output = "\n".join(output_lines)
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("JSON object missing from command output")


def wait_for_source() -> tuple[str, str]:
    for _ in range(120):
        git("fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
        for ref in SOURCE_CANDIDATES:
            probe = git("rev-parse", "--verify", f"{ref}^{{commit}}")
            if probe["returnCode"] == 0:
                return ref, "\n".join(probe["tail"]).strip()
        time.sleep(15)
    raise RuntimeError("no global convergence source candidate appeared")


def repair_native_bindings() -> dict[str, Any]:
    path = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    if not path.is_file():
        return {"present": False, "updated": 0, "valid": False}
    document = json.loads(path.read_text(encoding="utf-8"))
    observations = document.get("observations", [])
    updated = 0
    failures: list[dict[str, Any]] = []
    for row in observations:
        source = row.get("path")
        exports = row.get("exports")
        if not isinstance(source, str) or not isinstance(exports, list):
            failures.append({"path": source, "reason": "invalid observation shape"})
            continue
        source_path = ROOT / source
        if not source_path.is_file():
            failures.append({"path": source, "reason": "missing source"})
            continue
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        missing_exports = [
            value
            for value in exports
            if not isinstance(value, str) or value not in source_text
        ]
        if missing_exports:
            failures.append(
                {
                    "path": source,
                    "reason": "missing exports",
                    "exports": missing_exports,
                }
            )
        actual_receipt = git("hash-object", "--", source)
        if actual_receipt["returnCode"] != 0:
            failures.append({"path": source, "reason": "hash-object failed"})
            continue
        actual = "\n".join(actual_receipt["tail"]).strip()
        if row.get("blobSha") != actual:
            row["blobSha"] = actual
            updated += 1
    if updated:
        write_json(path, document)
    module_coverage = document.get("moduleCoverage")
    valid = len(observations) == 40 and module_coverage == 40 and not failures
    return {
        "present": True,
        "moduleCoverage": module_coverage,
        "observationCount": len(observations),
        "updated": updated,
        "failures": failures,
        "valid": valid,
    }


def cargo_metadata(locked: bool) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    command = [
        "cargo",
        "metadata",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "--format-version",
        "1",
    ]
    if locked:
        command.append("--locked")
    receipt = run(command, timeout=2400)
    if receipt["returnCode"] != 0:
        return None, receipt
    try:
        return parse_json(receipt["tail"]), receipt
    except ValueError:
        # Cargo metadata JSON can exceed the bounded receipt tail. Re-run to a
        # file so parsing stays exact without retaining an unbounded CI log.
        metadata_path = OUT / "cargo-metadata.json"
        shell = (
            "set -euo pipefail; cargo metadata --manifest-path codex-rs/Cargo.toml "
            "--format-version 1 "
            + ("--locked " if locked else "")
            + f"> {shlex.quote(str(metadata_path))}"
        )
        file_receipt = run(("bash", "-lc", shell), timeout=2400)
        if file_receipt["returnCode"] != 0 or not metadata_path.is_file():
            return None, file_receipt
        return json.loads(metadata_path.read_text(encoding="utf-8")), file_receipt


def commit_if_dirty(message: str) -> str:
    status = git("status", "--porcelain")
    if status["returnCode"] != 0:
        raise RuntimeError("git status failed")
    if not status["tail"]:
        return git_text("rev-parse", "HEAD")
    if git("add", "-A")["returnCode"] != 0:
        raise RuntimeError("git add failed")
    committed = git("commit", "--signoff", "-m", message)
    if committed["returnCode"] != 0:
        raise RuntimeError("git commit failed")
    return git_text("rev-parse", "HEAD")


def all_pass(receipts: Iterable[dict[str, Any]]) -> bool:
    return all(receipt.get("returnCode") == 0 for receipt in receipts)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    git("config", "user.name", "Hepta Global Finalizer")
    git("config", "user.email", "noreply@openai.com")
    source_ref, source_commit = wait_for_source()
    checkout = git("checkout", "-B", TARGET, source_ref)
    if checkout["returnCode"] != 0:
        raise RuntimeError("failed to checkout final source")

    generator_receipts = [
        run(command, timeout=1800)
        for command in GENERATORS
        if (ROOT / command[1]).is_file()
    ]
    native_before = repair_native_bindings()
    metadata, metadata_receipt = cargo_metadata(locked=True)
    lock_receipts = [metadata_receipt]
    if metadata is None:
        metadata, unlocked = cargo_metadata(locked=False)
        lock_receipts.append(unlocked)
        if metadata is not None:
            metadata, locked_again = cargo_metadata(locked=True)
            lock_receipts.append(locked_again)
    if metadata is None:
        raise RuntimeError("workspace metadata is unavailable")

    format_apply = run(
        ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
        timeout=2400,
    )
    native_after_format = repair_native_bindings()
    prequalification_commit = commit_if_dirty(
        "chore: normalize final all-Hepta convergence candidate"
    )

    workspace = set(metadata.get("workspace_members", []))
    packages = sorted(
        row["name"]
        for row in metadata.get("packages", [])
        if row.get("id") in workspace and row.get("name", "").startswith("codex-hepta-")
    )
    if len(packages) < 40:
        raise RuntimeError(
            f"canonical Hepta package set is unexpectedly small: {len(packages)}"
        )
    selectors: list[str] = []
    for package in packages:
        selectors.extend(("-p", package))

    verifier_receipts = [
        run(command, timeout=2400)
        for command in VERIFY_COMMANDS
        if (ROOT / command[1]).is_file()
    ]
    verifier_receipts.append(
        run(
            (
                "cargo",
                "fmt",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--all",
                "--",
                "--check",
            ),
            timeout=2400,
        )
    )
    test_receipt = run(
        (
            "cargo",
            "test",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--locked",
            *selectors,
            "--all-targets",
        ),
        timeout=18000,
    )
    clippy_receipt = run(
        (
            "cargo",
            "clippy",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--locked",
            *selectors,
            "--all-targets",
            "--no-deps",
            "--",
            "-D",
            "warnings",
        ),
        timeout=18000,
    )
    repair_receipts: list[dict[str, Any]] = []
    if test_receipt["returnCode"] != 0 or clippy_receipt["returnCode"] != 0:
        repair_receipts.append(
            run(
                (
                    "cargo",
                    "fix",
                    "--allow-dirty",
                    "--allow-staged",
                    "--manifest-path",
                    "codex-rs/Cargo.toml",
                    "--locked",
                    *selectors,
                    "--all-targets",
                ),
                timeout=18000,
            )
        )
        repair_receipts.append(
            run(
                (
                    "cargo",
                    "clippy",
                    "--fix",
                    "--allow-dirty",
                    "--allow-staged",
                    "--manifest-path",
                    "codex-rs/Cargo.toml",
                    "--locked",
                    *selectors,
                    "--all-targets",
                    "--no-deps",
                    "--",
                    "-D",
                    "warnings",
                ),
                timeout=18000,
            )
        )
        repair_receipts.append(
            run(
                ("cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all"),
                timeout=2400,
            )
        )
        native_after_repair = repair_native_bindings()
        repaired_commit = commit_if_dirty(
            "fix: apply all-Hepta deterministic final repairs"
        )
        verifier_receipts = [
            run(command, timeout=2400)
            for command in VERIFY_COMMANDS
            if (ROOT / command[1]).is_file()
        ]
        verifier_receipts.append(
            run(
                (
                    "cargo",
                    "fmt",
                    "--manifest-path",
                    "codex-rs/Cargo.toml",
                    "--all",
                    "--",
                    "--check",
                ),
                timeout=2400,
            )
        )
        test_receipt = run(
            (
                "cargo",
                "test",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                *selectors,
                "--all-targets",
            ),
            timeout=18000,
        )
        clippy_receipt = run(
            (
                "cargo",
                "clippy",
                "--manifest-path",
                "codex-rs/Cargo.toml",
                "--locked",
                *selectors,
                "--all-targets",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ),
            timeout=18000,
        )
    else:
        native_after_repair = native_after_format
        repaired_commit = None

    diff_check = git("diff", "--check")
    repository_passed = (
        all_pass(generator_receipts)
        and native_after_repair.get("valid") is True
        and all_pass(lock_receipts)
        and format_apply["returnCode"] == 0
        and all_pass(verifier_receipts)
        and test_receipt["returnCode"] == 0
        and clippy_receipt["returnCode"] == 0
        and diff_check["returnCode"] == 0
    )
    external_gates = [
        {
            "id": f"RDY-EXT-{index:03d}",
            "status": "external_open",
            "selfCertificationAllowed": False,
        }
        for index in range(1, 10)
    ]
    status = {
        "schemaVersion": 1,
        "runId": os.environ.get("GITHUB_RUN_ID", "local"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "sourceRef": source_ref,
        "sourceCommit": source_commit,
        "targetBranch": TARGET,
        "prequalificationCommit": prequalification_commit,
        "repairedCommit": repaired_commit,
        "canonicalHeptaPackageCount": len(packages),
        "canonicalHeptaPackages": packages,
        "generatorReceipts": generator_receipts,
        "nativeBindingBefore": native_before,
        "nativeBindingAfterFormat": native_after_format,
        "nativeBindingAfterRepair": native_after_repair,
        "lockReceipts": lock_receipts,
        "repositoryVerifierReceipts": verifier_receipts,
        "allHeptaTestReceipt": test_receipt,
        "allHeptaClippyReceipt": clippy_receipt,
        "repairReceipts": repair_receipts,
        "diffCheck": diff_check,
        "repositoryInternalValidationPassed": repository_passed,
        "repositoryInternalGapsClosed": repository_passed,
        "externalAuthorityGates": external_gates,
        "allGapsClosed": False,
        "authorityGranted": False,
        "productionActivation": False,
        "selection": False,
        "promotion": False,
        "release": False,
    }
    write_json(OUT / "STATUS.json", status)
    write_json(
        OUT / "EXTERNAL_GATE_HANDOFF.json",
        {
            "schemaVersion": 1,
            "qualifiedSourceCommit": repaired_commit or prequalification_commit,
            "authorityGranted": False,
            "gates": external_gates,
        },
    )
    failed = [
        receipt
        for receipt in (
            *generator_receipts,
            *lock_receipts,
            *verifier_receipts,
            test_receipt,
            clippy_receipt,
            diff_check,
        )
        if receipt.get("returnCode") != 0
    ]
    lines = [
        "# Hepta final all-package convergence r6",
        "",
        f"- source: `{source_ref}` @ `{source_commit}`",
        f"- target: `{TARGET}`",
        f"- canonical Hepta packages qualified: `{len(packages)}`",
        f"- exact 40-module native binding: `{'PASS' if native_after_repair.get('valid') else 'FAIL'}`",
        f"- repository-internal validation: `{'PASS' if repository_passed else 'BLOCKED'}`",
        "- external independent-authority gates: `9 retained open`",
        "- self-issued authority: `false`",
        "",
        "## Remaining internal failures",
        "",
    ]
    if failed:
        for receipt in failed:
            lines.append(
                f"- `{shlex.join(receipt['command'])}` returned `{receipt['returnCode']}`; "
                f"output sha256 `{receipt['outputSha256']}`."
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Independent review, operator acceptance, real target-host/hardware qualification, "
            "production canary, selection, promotion and release remain non-self-certifiable.",
            "",
        ]
    )
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    final_commit = commit_if_dirty(
        "docs: bind final all-Hepta convergence qualification"
    )
    pushed = git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET}")
    if pushed["returnCode"] != 0:
        raise RuntimeError("failed to push final candidate")
    print(
        json.dumps(
            {
                "targetBranch": TARGET,
                "head": final_commit,
                "repositoryInternalValidationPassed": repository_passed,
                "canonicalHeptaPackageCount": len(packages),
            }
        )
    )
    return 0 if repository_passed else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_GLOBAL_FINALIZER_R6_ERROR: {error}", file=sys.stderr)
        raise
