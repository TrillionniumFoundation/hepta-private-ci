#!/usr/bin/env python3
"""Synchronize kernel.evidence status projections from one canonical source.

The checked-in source records repository implementation facts and persistent
external evidence gates. It never manufactures CI qualification or governance
authority. Exact-source and deterministic-merge workflow receipts overlay the
same fields at execution time and retain the source-file digest in their
artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "qualification/kernel-evidence/STATUS_SOURCE.json"
DASHBOARD_PATH = ROOT / "qualification/kernel-evidence/RELEASE_DASHBOARD.md"
PROJECTION_PATHS = (
    ROOT / "docs/modules/kernel.evidence/TECHNICAL.md",
    ROOT / "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md",
    ROOT / "qualification/kernel-evidence/TRACEABILITY.md",
    ROOT / "qualification/module-execution-dossiers/detail/kernel.evidence.md",
)
STATUS_BEGIN = "<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->"
STATUS_END = "<!-- END GENERATED KERNEL EVIDENCE STATUS -->"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

CAPABILITIES = (
    ("recoveryFrontierV2", "Recovery-frontier v2 signing domain"),
    ("externalMonotonicBackendAdapter", "External monotonic CAS backend adapter"),
    ("productionFailClosedMode", "Fail-closed Agentd production mode"),
    ("immutableLocalFrontierAcceptance", "Immutable local frontier acceptance history"),
    ("thresholdSignerRotation", "Distinct-principal threshold and key-epoch rotation"),
    ("productionReadOnlyMigrationPreflight", "Read-only production migration preflight"),
    ("stableCursorPagination", "Stable append-sequence cursor pagination"),
    ("appendOnlyDatabaseTriggers", "Database update/delete denial triggers"),
    ("sqliteAuthorizer", "SQLite authorizer callback"),
    ("diskFullFaultInjection", "Disk-full fault injection"),
    ("multiProcessContentionBenchmark", "Multi-process contention benchmark"),
)
GATES = (
    ("exactSourceQualified", "Exact-source qualification"),
    ("mergeCandidateQualified", "Deterministic-merge qualification"),
    ("independentAcceptance", "Independent acceptance"),
    ("externalFrontierActive", "External frontier active"),
    ("backupRestoreDrilled", "Backup/restore drill"),
    ("canaryAccepted", "Canary accepted"),
    ("releaseApproved", "Release approved"),
)
EXTERNAL_GATES = tuple(key for key, _ in GATES[2:])


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
    )
    if not isinstance(value, dict):
        raise ValueError("canonical status root must be an object")
    return value


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=ROOT, text=True
    ).strip()


def validate_receipt(name: str, receipt: Any, status: dict[str, Any]) -> None:
    if not isinstance(receipt, dict):
        raise ValueError(f"{name} requires an evidence receipt object")
    required = {
        "sha256",
        "issuerPrincipalId",
        "candidateCommit",
        "candidateTree",
        "observedAt",
    }
    if set(receipt) != required:
        raise ValueError(f"{name} receipt keys must be {sorted(required)}")
    if not isinstance(receipt["sha256"], str) or not HEX64.fullmatch(
        receipt["sha256"]
    ):
        raise ValueError(f"{name} receipt digest must be lowercase SHA-256")
    if (
        not isinstance(receipt["issuerPrincipalId"], str)
        or not receipt["issuerPrincipalId"]
        or not isinstance(receipt["observedAt"], str)
        or not receipt["observedAt"]
    ):
        raise ValueError(f"{name} receipt identity and observation are required")
    if receipt["candidateCommit"] != status["asOfCommit"] or receipt[
        "candidateTree"
    ] != status["asOfTree"]:
        raise ValueError(f"{name} receipt is not bound to the status source anchor")


def validate_status(status: dict[str, Any], *, check_git: bool = True) -> None:
    required = {
        "schema",
        "schemaVersion",
        "module",
        "asOfCommit",
        "asOfTree",
        "workflowRunId",
        "artifactDigest",
        "exactSourceQualified",
        "mergeCandidateQualified",
        "independentAcceptance",
        "externalFrontierActive",
        "backupRestoreDrilled",
        "canaryAccepted",
        "releaseApproved",
        "sourcePaths",
        "capabilities",
        "evidenceReceipts",
        "claimBoundary",
    }
    if set(status) != required:
        missing = sorted(required - set(status))
        extra = sorted(set(status) - required)
        raise ValueError(f"canonical status keys differ; missing={missing}, extra={extra}")
    if (
        status["schema"] != "hepta.kernel-evidence-status-source.v1"
        or status["schemaVersion"] != 1
        or status["module"] != "kernel.evidence"
    ):
        raise ValueError("canonical status schema or module identity is invalid")
    for key in ("asOfCommit", "asOfTree"):
        if not isinstance(status[key], str) or HEX40.fullmatch(status[key]) is None:
            raise ValueError(f"{key} must be a lowercase 40-character Git object id")
    for key, _ in GATES:
        if type(status[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    capabilities = status["capabilities"]
    if not isinstance(capabilities, dict) or set(capabilities) != {
        key for key, _ in CAPABILITIES
    }:
        raise ValueError("capability inventory is not closed-world")
    if any(type(value) is not bool for value in capabilities.values()):
        raise ValueError("every capability value must be boolean")
    source_paths = status["sourcePaths"]
    if (
        not isinstance(source_paths, list)
        or not source_paths
        or source_paths != sorted(set(source_paths))
        or any(not isinstance(path, str) or not path for path in source_paths)
    ):
        raise ValueError("sourcePaths must be a nonempty sorted unique string list")
    receipts = status["evidenceReceipts"]
    if not isinstance(receipts, dict) or set(receipts) - set(EXTERNAL_GATES):
        raise ValueError("evidenceReceipts contains an unknown external gate")
    for gate in EXTERNAL_GATES:
        if status[gate]:
            validate_receipt(gate, receipts.get(gate), status)
        elif gate in receipts:
            raise ValueError(f"false gate {gate} must not retain an authority receipt")

    qualified = status["exactSourceQualified"] and status["mergeCandidateQualified"]
    if status["exactSourceQualified"] != status["mergeCandidateQualified"]:
        raise ValueError("persistent source and merge qualification must advance together")
    if qualified:
        if (
            not isinstance(status["workflowRunId"], str)
            or not status["workflowRunId"].isdigit()
            or int(status["workflowRunId"]) <= 0
            or not isinstance(status["artifactDigest"], str)
            or HEX64.fullmatch(status["artifactDigest"]) is None
        ):
            raise ValueError("qualified status requires a workflow run and artifact digest")
    elif status["workflowRunId"] is not None or status["artifactDigest"] is not None:
        raise ValueError("unqualified persistent status cannot retain workflow authority")

    dependencies = {
        "independentAcceptance": qualified,
        "externalFrontierActive": qualified,
        "backupRestoreDrilled": status["externalFrontierActive"],
        "canaryAccepted": (
            status["independentAcceptance"]
            and status["externalFrontierActive"]
            and status["backupRestoreDrilled"]
        ),
        "releaseApproved": status["canaryAccepted"],
    }
    for gate, prerequisite in dependencies.items():
        if status[gate] and not prerequisite:
            raise ValueError(f"{gate} is true without its prerequisite evidence")
    boundary = status["claimBoundary"]
    expected_boundary = {
        "repositoryImplementationDoesNotProveDeployment": True,
        "workflowReceiptDoesNotGrantRelease": True,
        "externalAuthorityRequiredForAcceptance": True,
    }
    if boundary != expected_boundary:
        raise ValueError("claimBoundary must preserve the non-self-issuing policy")

    if not check_git:
        return
    if git("cat-file", "-t", status["asOfCommit"]) != "commit":
        raise ValueError("asOfCommit is not a commit object")
    if git("rev-parse", f"{status['asOfCommit']}^{{tree}}") != status["asOfTree"]:
        raise ValueError("asOfTree does not match asOfCommit")
    git("merge-base", "--is-ancestor", status["asOfCommit"], "HEAD")
    for path in source_paths:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError(f"source path escapes the repository: {path}")
        if not (ROOT / path).is_file():
            raise ValueError(f"missing source path: {path}")
        git("cat-file", "-e", f"{status['asOfCommit']}:{path}")
    changed = git(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        status["asOfCommit"],
        "HEAD",
        "--",
        *source_paths,
    )
    if changed:
        raise ValueError("canonical status source is stale for: " + changed)


def status_sha256() -> str:
    return hashlib.sha256(STATUS_PATH.read_bytes()).hexdigest()


def render_block(status: dict[str, Any]) -> str:
    lines = [
        STATUS_BEGIN,
        "## Canonical kernel.evidence status",
        "",
        "This block is generated from",
        "`qualification/kernel-evidence/STATUS_SOURCE.json` by",
        "`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot",
        "override these facts. Workflow receipts may prove the current candidate, but",
        "cannot self-issue independent acceptance, deployment, canary or release.",
        "",
        f"- Source anchor commit: `{status['asOfCommit']}`",
        f"- Source anchor tree: `{status['asOfTree']}`",
        f"- Canonical status SHA-256: `{status_sha256()}`",
        f"- Workflow run ID: `{status['workflowRunId'] or 'none'}`",
        f"- Retained artifact digest: `{status['artifactDigest'] or 'none'}`",
        "",
        "### Repository implementation capabilities",
        "",
        "| Capability | Implemented |",
        "| --- | --- |",
    ]
    for key, label in CAPABILITIES:
        lines.append(f"| {label} | `{str(status['capabilities'][key]).lower()}` |")
    lines.extend(
        [
            "",
            "### Qualification, deployment and governance gates",
            "",
            "| Gate | State | Persistent authority receipt |",
            "| --- | --- | --- |",
        ]
    )
    receipts = status["evidenceReceipts"]
    for key, label in GATES:
        receipt = receipts.get(key)
        digest = f"`{receipt['sha256']}`" if isinstance(receipt, dict) else "none"
        lines.append(f"| {label} | `{str(status[key]).lower()}` | {digest} |")
    lines.extend(
        [
            "",
            "> Repository implementation is not deployment evidence. A CI workflow receipt",
            "> is not independent acceptance or release authority.",
            STATUS_END,
        ]
    )
    return "\n".join(lines)


def project(text: str, block: str) -> str:
    pattern = re.compile(re.escape(STATUS_BEGIN) + r".*?" + re.escape(STATUS_END), re.S)
    if pattern.search(text):
        return pattern.sub(block, text, count=1)
    return text.rstrip() + "\n\n" + block + "\n"


def dashboard(block: str) -> str:
    return (
        "# kernel.evidence release dashboard\n\n"
        "This file is wholly generated. Do not edit it directly.\n\n"
        + block
        + "\n"
    )


def sync(status: dict[str, Any]) -> None:
    block = render_block(status)
    for path in PROJECTION_PATHS:
        path.write_text(project(path.read_text(encoding="utf-8"), block), encoding="utf-8")
    DASHBOARD_PATH.write_text(dashboard(block), encoding="utf-8")


def verify(status: dict[str, Any]) -> None:
    block = render_block(status)
    failures: list[str] = []
    for path in PROJECTION_PATHS:
        actual = path.read_text(encoding="utf-8")
        expected = project(actual, block)
        if actual != expected:
            failures.append(str(path.relative_to(ROOT)))
    if not DASHBOARD_PATH.is_file() or DASHBOARD_PATH.read_text(
        encoding="utf-8"
    ) != dashboard(block):
        failures.append(str(DASHBOARD_PATH.relative_to(ROOT)))
    if failures:
        raise ValueError(
            "kernel.evidence status projections are stale: " + ", ".join(failures)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "verify", "print"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        status = load_json(STATUS_PATH)
        validate_status(status)
        if args.command == "sync":
            sync(status)
        elif args.command == "verify":
            verify(status)
        else:
            print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"kernel.evidence canonical status failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
