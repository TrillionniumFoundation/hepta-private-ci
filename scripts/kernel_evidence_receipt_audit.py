#!/usr/bin/env python3
"""Audit retained kernel.evidence receipts against their exact on-disk logs.

This is the final byte-binding layer for the repository-controlled readiness
claim.  Receipt fields are treated as untrusted metadata until every identity,
integer, path, byte count, digest, command marker, and authority boundary is
revalidated against files retained by the same workflow attempt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile
from typing import Any

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

QUALIFICATION_LOGS = {
    "exact_source": Path("source/tests.log"),
    "deterministic_merge": Path("merge/tests.log"),
    "metadata": Path("metadata/metadata.log"),
    "publication_diagnostics": Path("publication/publication.log"),
}

REQUIRED_CRASH_SCENARIOS = (
    "sqlite_process_kill",
    "wal_rollback_journal",
    "fsync_rename_directory_fsync",
    "disk_full",
    "damaged_frontier",
    "damaged_database",
    "stale_valid_frontier",
    "legacy_import",
    "simultaneous_database_frontier_rollback",
    "backup_restore",
    "multi_process_contention",
    "repair_append_concurrency",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".receipt-audit-"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def is_exact_int(value: object, *, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def require_oid(value: str | None, label: str, errors: list[str], *, optional: bool = False) -> None:
    if optional and not value:
        return
    if not isinstance(value, str) or OID.fullmatch(value) is None:
        errors.append(f"{label} must be a full lowercase Git object id")


def validate_timestamp_range(value: dict[str, Any], prefix: str, errors: list[str]) -> None:
    started = value.get("startedAtUnixMs")
    finished = value.get("finishedAtUnixMs")
    if not is_exact_int(started, minimum=1):
        errors.append(f"{prefix}.startedAtUnixMs must be a positive integer, not bool")
    if not is_exact_int(finished, minimum=1):
        errors.append(f"{prefix}.finishedAtUnixMs must be a positive integer, not bool")
    if is_exact_int(started, minimum=1) and is_exact_int(finished, minimum=1):
        if finished < started:
            errors.append(f"{prefix} timestamps are inverted")


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def strict_regular_file(
    records_root: Path,
    raw_path: str | Path,
    *,
    label: str,
    expected: Path | None = None,
    allowed_root: Path | None = None,
) -> Path:
    root = records_root.resolve(strict=True)
    boundary_path = _lexical_absolute(allowed_root or root)
    try:
        boundary_relative = boundary_path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} boundary escapes the retained-artifact root") from error
    current = root
    for component in boundary_relative.parts:
        current = current / component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            raise ValueError(f"{label} boundary is absent: {current}") from error
        if stat.S_ISLNK(mode):
            raise ValueError(f"{label} boundary must not traverse a symlink: {current}")
    if not boundary_path.is_dir():
        raise ValueError(f"{label} boundary must be a directory")
    boundary = boundary_path.resolve(strict=True)

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = _lexical_absolute(candidate)
    try:
        relative = candidate.relative_to(boundary_path)
    except ValueError as error:
        raise ValueError(f"{label} escapes its retained-artifact boundary") from error

    current = boundary_path
    for component in relative.parts:
        current = current / component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as error:
            raise ValueError(f"{label} is absent: {current}") from error
        if stat.S_ISLNK(mode):
            raise ValueError(f"{label} must not traverse a symlink: {current}")
    mode = os.lstat(candidate).st_mode
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular file")
    resolved = candidate.resolve(strict=True)
    if expected is not None:
        expected_resolved = strict_regular_file(
            records_root,
            expected,
            label=f"expected {label}",
            allowed_root=allowed_root,
        )
        if resolved != expected_resolved:
            raise ValueError(f"{label} does not name the exact retained file")
    return resolved


def expect(value: dict[str, Any], key: str, expected: object, prefix: str, errors: list[str]) -> None:
    if value.get(key) != expected:
        errors.append(f"{prefix}.{key} does not match the immutable candidate")


def validate_authority_false(value: dict[str, Any], keys: tuple[str, ...], prefix: str, errors: list[str]) -> None:
    for key in keys:
        if value.get(key) is not False:
            errors.append(f"{prefix}.{key} must be exactly false")


def identity_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "sourceHeadSha": args.source_head_sha,
        "sourceHeadTree": args.source_head_tree,
        "baseSha": args.base_sha,
        "deterministicMergeSha": args.deterministic_merge_sha or None,
        "githubSyntheticMergeSha": args.github_synthetic_merge_sha or None,
        "workflowSha": args.workflow_sha,
        "finalMergeSha": args.final_merge_sha or None,
        "workflowRunId": args.workflow_run_id,
        "workflowRunAttempt": args.workflow_run_attempt,
        "runnerImage": args.runner_image,
        "targetTriple": args.target_triple,
    }


def validate_identity(identity: dict[str, Any], errors: list[str]) -> None:
    require_oid(identity.get("sourceHeadSha"), "source head", errors)
    require_oid(identity.get("sourceHeadTree"), "source tree", errors)
    require_oid(identity.get("baseSha"), "base", errors)
    require_oid(identity.get("deterministicMergeSha"), "deterministic merge", errors)
    require_oid(identity.get("githubSyntheticMergeSha"), "GitHub synthetic merge", errors, optional=True)
    require_oid(identity.get("workflowSha"), "workflow", errors)
    require_oid(identity.get("finalMergeSha"), "final merge", errors, optional=True)
    for key in ("workflowRunId", "workflowRunAttempt", "runnerImage", "targetTriple"):
        if not isinstance(identity.get(key), str) or not identity[key]:
            errors.append(f"{key} must be a non-empty string")


def audit_qualification_receipt(
    records_root: Path,
    kind: str,
    identity: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    prefix = f"qualification.{kind}"
    receipt_path = records_root / f"{kind}.json"
    expected_log = records_root / QUALIFICATION_LOGS[kind]
    entry: dict[str, Any] = {
        "receiptPath": str(receipt_path),
        "logPath": str(expected_log),
        "passed": False,
    }
    try:
        receipt_file = strict_regular_file(records_root, receipt_path, label=f"{prefix} receipt")
        receipt = load_json(receipt_file)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(str(error))
        entry["errors"] = errors
        return entry, errors

    expected_merge = identity["deterministicMergeSha"] if kind == "deterministic_merge" else None
    expected_tested = expected_merge if kind == "deterministic_merge" else identity["sourceHeadSha"]
    expected_values = {
        "schemaVersion": 2,
        "module": "kernel.evidence",
        "receiptKind": "candidate_qualification",
        "kind": kind,
        "sourceHeadSha": identity["sourceHeadSha"],
        "sourceHeadTree": identity["sourceHeadTree"],
        "baseSha": identity["baseSha"],
        "deterministicMergeSha": expected_merge,
        "testedObjectSha": expected_tested,
        "workflowSha": identity["workflowSha"],
        "workflowRunId": identity["workflowRunId"],
        "workflowRunAttempt": identity["workflowRunAttempt"],
        "runnerImage": identity["runnerImage"],
        "targetTriple": identity["targetTriple"],
        "status": "passed",
        "passed": True,
    }
    for key, expected in expected_values.items():
        expect(receipt, key, expected, prefix, errors)
    if not is_exact_int(receipt.get("exitCode"), minimum=0) or receipt.get("exitCode") != 0:
        errors.append(f"{prefix}.exitCode must be integer zero, not bool")
    if not isinstance(receipt.get("command"), str) or not receipt["command"]:
        errors.append(f"{prefix}.command must be non-empty")
    validate_timestamp_range(receipt, prefix, errors)
    validate_authority_false(
        receipt,
        (
            "qualificationGranted",
            "independentAcceptanceGranted",
            "productionActivationGranted",
            "releaseGranted",
        ),
        prefix,
        errors,
    )

    try:
        log = strict_regular_file(
            records_root,
            receipt.get("logPath", ""),
            label=f"{prefix} log",
            expected=expected_log,
        )
        actual_sha = sha256_file(log)
        actual_bytes = log.stat().st_size
        if actual_bytes <= 0:
            errors.append(f"{prefix} retained log is empty")
        if receipt.get("logSha256") != actual_sha:
            errors.append(f"{prefix}.logSha256 does not match retained log bytes")
        if not is_exact_int(receipt.get("logBytes"), minimum=0):
            errors.append(f"{prefix}.logBytes must be an integer, not bool")
        elif receipt.get("logBytes") != actual_bytes:
            errors.append(f"{prefix}.logBytes does not match retained log bytes")
        entry.update(
            {
                "receiptSha256": sha256_file(receipt_file),
                "logSha256": actual_sha,
                "logBytes": actual_bytes,
            }
        )
    except (OSError, ValueError) as error:
        errors.append(str(error))

    entry["passed"] = not errors
    entry["errors"] = errors
    return entry, errors


def audit_crash_command(
    records_root: Path,
    scenario_root: Path,
    scenario: str,
    index: int,
    command: object,
    used_logs: set[Path],
) -> tuple[dict[str, Any], list[str]]:
    prefix = f"crash.{scenario}.commands[{index}]"
    errors: list[str] = []
    result: dict[str, Any] = {"passed": False}
    if not isinstance(command, dict):
        errors.append(f"{prefix} must be an object")
        result["errors"] = errors
        return result, errors

    if command.get("status") != "passed":
        errors.append(f"{prefix}.status must be passed")
    if not is_exact_int(command.get("exitCode"), minimum=0) or command.get("exitCode") != 0:
        errors.append(f"{prefix}.exitCode must be integer zero, not bool")
    if command.get("timedOut") is not False:
        errors.append(f"{prefix}.timedOut must be exactly false")
    if command.get("skippedDetected") is not False:
        errors.append(f"{prefix}.skippedDetected must be exactly false")
    if command.get("missingMarkers") != []:
        errors.append(f"{prefix}.missingMarkers must be empty")
    validate_timestamp_range(command, prefix, errors)

    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        errors.append(f"{prefix}.argv must be a non-empty string array")
    elif command.get("command") != shlex.join(argv):
        errors.append(f"{prefix}.command is not the canonical argv rendering")
    for key in ("package", "testName"):
        if not isinstance(command.get(key), str) or not command[key]:
            errors.append(f"{prefix}.{key} must be non-empty")
    target_args = command.get("targetArgs")
    if not isinstance(target_args, list) or not all(isinstance(item, str) for item in target_args):
        errors.append(f"{prefix}.targetArgs must be a string array")
    required_markers = command.get("requiredMarkers")
    if (
        not isinstance(required_markers, list)
        or not required_markers
        or not all(isinstance(marker, str) and marker for marker in required_markers)
    ):
        errors.append(f"{prefix}.requiredMarkers must be a non-empty string array")

    try:
        log = strict_regular_file(
            records_root,
            command.get("logPath", ""),
            label=f"{prefix} log",
            allowed_root=scenario_root,
        )
        if log in used_logs:
            errors.append(f"{prefix} reuses another command log")
        used_logs.add(log)
        actual = log.read_bytes()
        actual_sha = hashlib.sha256(actual).hexdigest()
        if not actual:
            errors.append(f"{prefix} retained log is empty")
        if command.get("logSha256") != actual_sha:
            errors.append(f"{prefix}.logSha256 does not match retained log bytes")
        if not is_exact_int(command.get("logBytes"), minimum=0):
            errors.append(f"{prefix}.logBytes must be an integer, not bool")
        elif command.get("logBytes") != len(actual):
            errors.append(f"{prefix}.logBytes does not match retained log bytes")
        text = actual.decode("utf-8", errors="replace")
        if isinstance(required_markers, list):
            for marker in required_markers:
                if isinstance(marker, str) and marker and marker not in text:
                    errors.append(f"{prefix} retained log is missing marker {marker!r}")
        if "skipping:" in text.lower():
            errors.append(f"{prefix} retained log contains a skip marker")
        result.update({"logPath": str(log), "logSha256": actual_sha, "logBytes": len(actual)})
    except (OSError, ValueError) as error:
        errors.append(str(error))

    result["passed"] = not errors
    result["errors"] = errors
    return result, errors


def audit_crash_matrix(
    records_root: Path,
    identity: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    all_errors: list[str] = []
    crash_root = records_root / "crash"
    scenarios: dict[str, Any] = {}
    used_logs: set[Path] = set()
    for scenario in REQUIRED_CRASH_SCENARIOS:
        errors: list[str] = []
        prefix = f"crash.{scenario}"
        receipt_path = crash_root / f"{scenario}.json"
        scenario_root = crash_root / scenario
        entry: dict[str, Any] = {"passed": False, "receiptPath": str(receipt_path)}
        try:
            receipt_file = strict_regular_file(
                records_root, receipt_path, label=f"{prefix} receipt"
            )
            receipt = load_json(receipt_file)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(str(error))
            entry["errors"] = errors
            scenarios[scenario] = entry
            all_errors.extend(errors)
            continue

        expected_values = {
            "schemaVersion": 2,
            "module": "kernel.evidence",
            "receiptKind": "crash_consistency_scenario",
            "scenario": scenario,
            "sourceHeadSha": identity["sourceHeadSha"],
            "sourceHeadTree": identity["sourceHeadTree"],
            "baseSha": identity["baseSha"],
            "workflowSha": identity["workflowSha"],
            "workflowRunId": identity["workflowRunId"],
            "workflowRunAttempt": identity["workflowRunAttempt"],
            "runnerImage": identity["runnerImage"],
            "targetTriple": identity["targetTriple"],
            "qualificationClass": "hosted_runner",
            "status": "passed",
        }
        for key, expected in expected_values.items():
            expect(receipt, key, expected, prefix, errors)
        validate_timestamp_range(receipt, prefix, errors)
        validate_authority_false(
            receipt,
            (
                "qualificationGranted",
                "targetHostAcceptanceGranted",
                "productionActivationGranted",
                "releaseGranted",
            ),
            prefix,
            errors,
        )
        commands = receipt.get("commands")
        command_results: list[dict[str, Any]] = []
        if not isinstance(commands, list) or not commands:
            errors.append(f"{prefix}.commands must be non-empty")
        else:
            for index, command in enumerate(commands):
                result, command_errors = audit_crash_command(
                    records_root,
                    scenario_root,
                    scenario,
                    index,
                    command,
                    used_logs,
                )
                command_results.append(result)
                errors.extend(command_errors)
        entry.update(
            {
                "receiptSha256": sha256_file(receipt_file),
                "commands": command_results,
                "passed": not errors,
                "errors": errors,
            }
        )
        scenarios[scenario] = entry
        all_errors.extend(errors)

    summary_errors: list[str] = []
    summary_path = crash_root / "SUMMARY.json"
    summary_entry: dict[str, Any] = {"passed": False, "path": str(summary_path)}
    try:
        summary_file = strict_regular_file(
            records_root, summary_path, label="crash summary"
        )
        summary = load_json(summary_file)
        expected_values = {
            "schemaVersion": 2,
            "module": "kernel.evidence",
            "receiptKind": "crash_consistency_matrix",
            "sourceHeadSha": identity["sourceHeadSha"],
            "sourceHeadTree": identity["sourceHeadTree"],
            "baseSha": identity["baseSha"],
            "workflowSha": identity["workflowSha"],
            "workflowRunId": identity["workflowRunId"],
            "workflowRunAttempt": identity["workflowRunAttempt"],
            "runnerImage": identity["runnerImage"],
            "targetTriple": identity["targetTriple"],
            "passed": True,
        }
        for key, expected in expected_values.items():
            expect(summary, key, expected, "crash.summary", summary_errors)
        if not is_exact_int(summary.get("scenarioCount"), minimum=0):
            summary_errors.append("crash.summary.scenarioCount must be an integer, not bool")
        if not is_exact_int(summary.get("requiredScenarioCount"), minimum=0):
            summary_errors.append("crash.summary.requiredScenarioCount must be an integer, not bool")
        if summary.get("scenarioCount") != len(REQUIRED_CRASH_SCENARIOS):
            summary_errors.append("crash.summary scenario count is incomplete")
        if summary.get("requiredScenarioCount") != len(REQUIRED_CRASH_SCENARIOS):
            summary_errors.append("crash.summary required scenario count is incorrect")
        validate_authority_false(
            summary,
            ("targetHostAcceptanceGranted", "productionActivationGranted", "releaseGranted"),
            "crash.summary",
            summary_errors,
        )
        summary_scenarios = summary.get("scenarios")
        if not isinstance(summary_scenarios, dict) or set(summary_scenarios) != set(REQUIRED_CRASH_SCENARIOS):
            summary_errors.append("crash.summary.scenarios must be the exact closed-world inventory")
        else:
            for scenario in REQUIRED_CRASH_SCENARIOS:
                item = summary_scenarios.get(scenario)
                if not isinstance(item, dict):
                    summary_errors.append(f"crash.summary.scenarios.{scenario} must be an object")
                    continue
                expected_receipt = crash_root / f"{scenario}.json"
                try:
                    referenced = strict_regular_file(
                        records_root,
                        item.get("path", ""),
                        label=f"crash.summary.scenarios.{scenario}.path",
                        expected=expected_receipt,
                    )
                    actual_sha = sha256_file(referenced)
                    if item.get("sha256") != actual_sha:
                        summary_errors.append(
                            f"crash.summary.scenarios.{scenario}.sha256 does not match receipt bytes"
                        )
                    if item.get("passed") is not True:
                        summary_errors.append(
                            f"crash.summary.scenarios.{scenario}.passed must be exactly true"
                        )
                except (OSError, ValueError) as error:
                    summary_errors.append(str(error))
        summary_entry.update(
            {
                "sha256": sha256_file(summary_file),
                "passed": not summary_errors,
                "errors": summary_errors,
            }
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        summary_errors.append(str(error))
        summary_entry["errors"] = summary_errors
    all_errors.extend(summary_errors)

    return {
        "passed": not all_errors and all(entry["passed"] for entry in scenarios.values()),
        "summary": summary_entry,
        "scenarios": scenarios,
    }, all_errors


def build_audit(records_root: Path, identity: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        root = records_root.resolve(strict=True)
        if records_root.is_symlink() or not root.is_dir():
            errors.append("records root must be a real directory, not a symlink")
    except OSError as error:
        root = records_root
        errors.append(f"records root is unavailable: {error}")

    validate_identity(identity, errors)
    qualifications: dict[str, Any] = {}
    if not errors or Path(root).is_dir():
        for kind in QUALIFICATION_LOGS:
            entry, entry_errors = audit_qualification_receipt(Path(root), kind, identity)
            qualifications[kind] = entry
            errors.extend(entry_errors)
        crash, crash_errors = audit_crash_matrix(Path(root), identity)
        errors.extend(crash_errors)
    else:
        qualifications = {
            kind: {"passed": False, "errors": ["records root is unavailable"]}
            for kind in QUALIFICATION_LOGS
        }
        crash = {"passed": False, "errors": ["records root is unavailable"]}

    unique_errors = list(dict.fromkeys(errors))
    passed = (
        not unique_errors
        and all(entry.get("passed") is True for entry in qualifications.values())
        and crash.get("passed") is True
    )
    return {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "receiptKind": "readiness_receipt_audit",
        "identity": identity,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "qualificationReceipts": qualifications,
        "crashConsistency": crash,
        "errors": unique_errors,
        "authority": {
            "qualificationGranted": False,
            "independentAcceptanceGranted": False,
            "targetHostAcceptanceGranted": False,
            "productionActivationGranted": False,
            "promotionGranted": False,
            "releaseGranted": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-root", type=Path, required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--source-head-tree", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--deterministic-merge-sha", default="")
    parser.add_argument("--github-synthetic-merge-sha", default="")
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--final-merge-sha", default="")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identity = identity_from_args(args)
    try:
        audit = build_audit(args.records_root, identity)
    except Exception as error:
        audit = {
            "schemaVersion": 1,
            "module": "kernel.evidence",
            "receiptKind": "readiness_receipt_audit",
            "identity": identity,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "passed": False,
            "qualificationReceipts": {},
            "crashConsistency": {"passed": False},
            "errors": [f"receipt audit failed closed: {error}"],
            "authority": {
                "qualificationGranted": False,
                "independentAcceptanceGranted": False,
                "targetHostAcceptanceGranted": False,
                "productionActivationGranted": False,
                "promotionGranted": False,
                "releaseGranted": False,
            },
        }
    atomic_json(args.output, audit)
    print(json.dumps(audit, sort_keys=True))
    return 0 if audit["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
