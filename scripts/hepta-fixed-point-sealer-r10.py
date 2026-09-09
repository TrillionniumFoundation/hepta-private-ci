#!/usr/bin/env python3
"""Seal two independently qualified all-Hepta repair passes at a stable fixed point."""
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
R8_REF = os.environ.get(
    "HEPTA_R8_REF",
    "origin/integration/hepta-all-gap-closure-20260910-r8",
)
R9_REF = os.environ.get(
    "HEPTA_R9_REF",
    "origin/integration/hepta-all-gap-closure-20260910-r9",
)
TARGET = os.environ.get(
    "HEPTA_SEALED_TARGET",
    "integration/hepta-all-gap-closure-20260910-sealed-r10",
)
STATUS_CANDIDATES = (
    "qualification/global-gap-closure-final-r8/STATUS.json",
    "qualification/global-gap-closure-final-r7/STATUS.json",
    "qualification/global-gap-closure-final-r6/STATUS.json",
)
OUT = ROOT / "qualification" / "global-gap-closure-seal-r10"
EXCLUDED_PREFIXES = (
    "qualification/global-gap-closure",
    "qualification/global-gap-closure-final",
    "qualification/global-gap-closure-seal",
)


def run(argv: Iterable[str], *, check: bool = True, timeout: int = 1800) -> str:
    args = tuple(argv)
    print("+", shlex.join(args), flush=True)
    completed = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    print(completed.stdout[-12000:], flush=True)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {shlex.join(args)}"
        )
    return completed.stdout.strip()


def git(*args: str, check: bool = True, timeout: int = 1800) -> str:
    return run(("git", *args), check=check, timeout=timeout)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ref_exists(ref: str) -> bool:
    completed = subprocess.run(
        ("git", "rev-parse", "--verify", f"{ref}^{{commit}}"),
        cwd=ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def wait_for_refs() -> None:
    for _ in range(360):
        git(
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            check=False,
        )
        if ref_exists(R8_REF) and ref_exists(R9_REF):
            return
        time.sleep(10)
    raise RuntimeError("r8/r9 convergence refs did not both appear")


def read_status(ref: str) -> tuple[str, dict[str, Any]]:
    for path in STATUS_CANDIDATES:
        content = git("show", f"{ref}:{path}", check=False)
        if not content:
            continue
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return path, value
    raise RuntimeError(f"no bound convergence STATUS.json found on {ref}")


def qualified_source(status: dict[str, Any]) -> str:
    for key in (
        "qualifiedSourceCommit",
        "sourceCommit",
        "repairedCommit",
        "prequalificationCommit",
    ):
        value = status.get(key)
        if isinstance(value, str) and len(value) == 40:
            if ref_exists(value):
                return value
    raise RuntimeError("status does not name an existing qualified source commit")


def filtered_surface(commit: str) -> tuple[str, list[str], int]:
    listing = git("ls-tree", "-r", "--full-tree", commit)
    rows: list[str] = []
    paths: list[str] = []
    for line in listing.splitlines():
        if "\t" not in line:
            continue
        metadata, path = line.split("\t", 1)
        if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        rows.append(f"{metadata}\t{path}")
        paths.append(path)
    encoded = ("\n".join(rows) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), paths, len(rows)


def diff_paths(left: str, right: str) -> list[str]:
    output = git("diff", "--name-only", left, right, check=False)
    return sorted(
        path
        for path in output.splitlines()
        if path and not any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
    )


def status_passed(status: dict[str, Any]) -> bool:
    return (
        status.get("repositoryInternalValidationPassed") is True
        and status.get("repositoryInternalGapsClosed") is True
        and int(status.get("canonicalHeptaPackageCount", 0)) >= 40
        and status.get("authorityGranted") is False
        and status.get("productionActivation") is False
        and status.get("selection") is False
        and status.get("promotion") is False
        and status.get("release") is False
    )


def commit_if_dirty(message: str) -> str:
    if not git("status", "--porcelain", check=False):
        return git("rev-parse", "HEAD")
    git("add", "-A")
    git("commit", "--signoff", "-m", message)
    return git("rev-parse", "HEAD")


def main() -> int:
    git("config", "user.name", "Hepta Fixed-Point Sealer")
    git("config", "user.email", "noreply@openai.com")
    wait_for_refs()
    r8_status_path, r8_status = read_status(R8_REF)
    r9_status_path, r9_status = read_status(R9_REF)
    r8_source = qualified_source(r8_status)
    r9_source = qualified_source(r9_status)
    r8_digest, r8_paths, r8_count = filtered_surface(r8_source)
    r9_digest, r9_paths, r9_count = filtered_surface(r9_source)
    drift = diff_paths(r8_source, r9_source)
    stable = (
        status_passed(r8_status)
        and status_passed(r9_status)
        and r8_digest == r9_digest
        and r8_paths == r9_paths
        and not drift
    )

    git("checkout", "-B", TARGET, R9_REF)
    status = {
        "schemaVersion": 1,
        "runId": os.environ.get("GITHUB_RUN_ID", "local"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "r8Ref": R8_REF,
        "r8StatusPath": r8_status_path,
        "r8QualifiedSource": r8_source,
        "r8FilteredSurfaceSha256": r8_digest,
        "r8FilteredEntryCount": r8_count,
        "r8InternalPassed": status_passed(r8_status),
        "r9Ref": R9_REF,
        "r9StatusPath": r9_status_path,
        "r9QualifiedSource": r9_source,
        "r9FilteredSurfaceSha256": r9_digest,
        "r9FilteredEntryCount": r9_count,
        "r9InternalPassed": status_passed(r9_status),
        "driftPaths": drift,
        "fixedPointStable": stable,
        "repositoryInternalValidationPassed": stable,
        "repositoryInternalGapsClosed": stable,
        "externalAuthorityGatesRetained": True,
        "allGapsClosed": False,
        "authorityGranted": False,
        "productionActivation": False,
        "modelInvocationAuthority": False,
        "providerDispatchAuthority": False,
        "productionWriterAuthorityAdded": False,
        "selection": False,
        "promotion": False,
        "release": False,
    }
    write_json(OUT / "STATUS.json", status)
    write_json(
        OUT / "EXTERNAL_GATE_HANDOFF.json",
        {
            "schemaVersion": 1,
            "sealedQualifiedSource": r9_source if stable else None,
            "selfCertificationAllowed": False,
            "authorityGranted": False,
            "gates": [
                {
                    "id": f"RDY-EXT-{index:03d}",
                    "status": "external_open",
                    "selfCertificationAllowed": False,
                }
                for index in range(1, 10)
            ],
        },
    )
    lines = [
        "# Hepta fixed-point convergence seal r10",
        "",
        f"- r8 qualified source: `{r8_source}`",
        f"- r9 qualified source: `{r9_source}`",
        f"- r8 internal validation: `{'PASS' if status_passed(r8_status) else 'BLOCKED'}`",
        f"- r9 internal validation: `{'PASS' if status_passed(r9_status) else 'BLOCKED'}`",
        f"- filtered surface r8: `{r8_digest}` ({r8_count} entries)",
        f"- filtered surface r9: `{r9_digest}` ({r9_count} entries)",
        f"- fixed point: `{'STABLE' if stable else 'DRIFTED_OR_BLOCKED'}`",
        "- external independent-authority gates: `retained open`",
        "- self-issued authority: `false`",
        "",
        "## Drift paths",
        "",
    ]
    if drift:
        lines.extend(f"- `{path}`" for path in drift)
    else:
        lines.append("- none outside convergence-receipt directories")
    lines.extend(
        [
            "",
            "## Authority ceiling",
            "",
            "This seal proves only repository-internal fixed-point convergence over the bound "
            "source surfaces and receipts. It does not self-certify independent semantic review, "
            "runtime/model identity, future-time validity, target-host/hardware qualification, "
            "remote-owner consent, operator acceptance, production canary, selection, promotion, "
            "release, provider dispatch, model invocation, or an additional production writer.",
            "",
        ]
    )
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    receipt_commit = commit_if_dirty(
        "docs: bind fixed-point all-Hepta convergence seal r10"
    )
    git("push", "--force-with-lease", "origin", f"HEAD:refs/heads/{TARGET}")
    print(
        json.dumps(
            {
                "targetBranch": TARGET,
                "receiptCommit": receipt_commit,
                "fixedPointStable": stable,
                "r8Source": r8_source,
                "r9Source": r9_source,
                "surfaceSha256": r9_digest if stable else None,
            }
        )
    )
    return 0 if stable else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_FIXED_POINT_SEALER_R10_ERROR: {error}", file=sys.stderr)
        raise
