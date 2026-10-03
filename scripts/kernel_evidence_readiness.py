#!/usr/bin/env python3
"""Build one fail-closed runtime readiness manifest for kernel.evidence.

The manifest binds source, deterministic merge, hosted workflow, runtime status,
qualification receipts, crash receipts, and source-controlled inputs. It never
grants independent acceptance, external activation, operator activation,
promotion, or release authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

REQUIRED_QUALIFICATION_RECEIPTS = (
    "exact_source",
    "deterministic_merge",
    "metadata",
    "publication_diagnostics",
)
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


def inventory_hash(root: Path, paths: Iterable[Path]) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    selected = sorted({path.resolve() for path in paths if path.is_file()})
    for path in selected:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def tree_files(path: Path) -> list[Path]:
    return [entry for entry in path.rglob("*") if entry.is_file()] if path.exists() else []


def parse_named_paths(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or not raw_path or name in parsed:
            raise ValueError(f"expected one unique NAME=PATH value, got {value!r}")
        parsed[name] = Path(raw_path)
    return parsed


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def require_oid(value: str | None, label: str, *, optional: bool = False) -> None:
    if optional and not value:
        return
    if not isinstance(value, str) or OID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a full lowercase Git object id")


def valid_timestamp_range(value: dict[str, Any]) -> bool:
    started = value.get("startedAtUnixMs")
    finished = value.get("finishedAtUnixMs")
    return (
        type(started) is int
        and type(finished) is int
        and started > 0
        and finished >= started
    )


def qualification_receipt_status(
    *,
    path: Path | None,
    kind: str,
    source_head_sha: str,
    source_head_tree: str,
    base_sha: str,
    deterministic_merge_sha: str | None,
    workflow_sha: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    runner_image: str,
    target_triple: str,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "present": bool(path and path.is_file()),
        "passed": False,
    }
    if path is None or not path.is_file():
        entry["error"] = "receipt is absent"
        return entry

    try:
        value = load_json(path)
        expected_merge = deterministic_merge_sha if kind == "deterministic_merge" else None
        expected_tested_object = (
            deterministic_merge_sha if kind == "deterministic_merge" else source_head_sha
        )
        passed = (
            value.get("schemaVersion") == 2
            and value.get("module") == "kernel.evidence"
            and value.get("receiptKind") == "candidate_qualification"
            and value.get("kind") == kind
            and value.get("sourceHeadSha") == source_head_sha
            and value.get("sourceHeadTree") == source_head_tree
            and value.get("baseSha") == base_sha
            and value.get("deterministicMergeSha") == expected_merge
            and value.get("testedObjectSha") == expected_tested_object
            and value.get("workflowSha") == workflow_sha
            and value.get("workflowRunId") == workflow_run_id
            and value.get("workflowRunAttempt") == workflow_run_attempt
            and value.get("runnerImage") == runner_image
            and value.get("targetTriple") == target_triple
            and value.get("status") == "passed"
            and value.get("passed") is True
            and value.get("exitCode") == 0
            and valid_timestamp_range(value)
            and isinstance(value.get("command"), str)
            and bool(value.get("command"))
            and isinstance(value.get("logSha256"), str)
            and SHA256.fullmatch(value["logSha256"]) is not None
            and value.get("qualificationGranted") is False
            and value.get("independentAcceptanceGranted") is False
            and value.get("productionActivationGranted") is False
            and value.get("releaseGranted") is False
        )
        entry.update(
            {
                "passed": passed,
                "sha256": sha256_file(path),
                "testedObjectSha": value.get("testedObjectSha"),
                "logSha256": value.get("logSha256"),
            }
        )
        if not passed:
            entry["error"] = "receipt identity, execution, or authority boundary is invalid"
    except (OSError, ValueError, json.JSONDecodeError) as error:
        entry["error"] = str(error)
    return entry


def crash_receipt_status(
    *,
    directory: Path | None,
    source_head_sha: str,
    source_head_tree: str,
    base_sha: str,
    workflow_sha: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    runner_image: str,
    target_triple: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for scenario in REQUIRED_CRASH_SCENARIOS:
        path = None if directory is None else directory / f"{scenario}.json"
        entry: dict[str, Any] = {
            "present": bool(path and path.is_file()),
            "passed": False,
        }
        if path is None or not path.is_file():
            entry["error"] = "required scenario receipt is absent"
            result[scenario] = entry
            continue
        try:
            value = load_json(path)
            commands = value.get("commands")
            commands_valid = (
                isinstance(commands, list)
                and bool(commands)
                and all(
                    isinstance(command, dict)
                    and command.get("status") == "passed"
                    and command.get("exitCode") == 0
                    and command.get("timedOut") is False
                    and command.get("skippedDetected") is False
                    and not command.get("missingMarkers")
                    and isinstance(command.get("logSha256"), str)
                    and SHA256.fullmatch(command["logSha256"]) is not None
                    and valid_timestamp_range(command)
                    for command in commands
                )
            )
            passed = (
                value.get("schemaVersion") == 2
                and value.get("module") == "kernel.evidence"
                and value.get("receiptKind") == "crash_consistency_scenario"
                and value.get("scenario") == scenario
                and value.get("sourceHeadSha") == source_head_sha
                and value.get("sourceHeadTree") == source_head_tree
                and value.get("baseSha") == base_sha
                and value.get("workflowSha") == workflow_sha
                and value.get("workflowRunId") == workflow_run_id
                and value.get("workflowRunAttempt") == workflow_run_attempt
                and value.get("runnerImage") == runner_image
                and value.get("targetTriple") == target_triple
                and value.get("qualificationClass") == "hosted_runner"
                and value.get("status") == "passed"
                and valid_timestamp_range(value)
                and commands_valid
                and value.get("qualificationGranted") is False
                and value.get("targetHostAcceptanceGranted") is False
                and value.get("productionActivationGranted") is False
                and value.get("releaseGranted") is False
            )
            entry.update({"passed": passed, "sha256": sha256_file(path)})
            if not passed:
                entry["error"] = (
                    "scenario receipt, exact candidate, command result, or authority "
                    "boundary is invalid"
                )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            entry["error"] = str(error)
        result[scenario] = entry
    return result


def validate_runtime_status(
    *,
    path: Path,
    source_head_sha: str,
    source_head_tree: str,
    base_sha: str,
    deterministic_merge_sha: str | None,
    github_synthetic_merge_sha: str | None,
    workflow_sha: str,
    final_merge_sha: str | None,
    workflow_run_id: str,
    workflow_run_attempt: str,
    runner_image: str,
    target_triple: str,
) -> dict[str, Any]:
    status = load_json(path)
    exact = (
        status.get("schema") == "hepta.kernel-evidence-runtime-status-source.v1"
        and status.get("schemaVersion") == 1
        and status.get("module") == "kernel.evidence"
        and status.get("statusClass") == "exact_runtime_qualification"
        and status.get("asOfCommit") == source_head_sha
        and status.get("asOfTree") == source_head_tree
        and status.get("baseSha") == base_sha
        and status.get("deterministicMergeSha") == deterministic_merge_sha
        and status.get("githubSyntheticMergeSha") == github_synthetic_merge_sha
        and status.get("workflowSha") == workflow_sha
        and status.get("finalMergeSha") == final_merge_sha
        and status.get("workflowRunId") == workflow_run_id
        and status.get("workflowRunAttempt") == workflow_run_attempt
        and status.get("runnerImage") == runner_image
        and status.get("targetTriple") == target_triple
        and status.get("authenticatedFrontierAuthorityAccepted") is False
        and status.get("externalFrontierActive") is False
        and status.get("independentRollbackAnchorAccepted") is False
        and status.get("independentAcceptance") is False
        and status.get("operatorActivation") is False
        and status.get("canaryAccepted") is False
        and status.get("promotionApproved") is False
        and status.get("releaseApproved") is False
    )
    return {
        "present": True,
        "exact": exact,
        "sha256": sha256_file(path),
        "asOfCommit": status.get("asOfCommit"),
        "asOfTree": status.get("asOfTree"),
        "error": None if exact else "runtime STATUS_SOURCE is not bound to the exact tested object",
        "value": status,
    }


def artifact_inventory(artifacts: dict[str, Path]) -> tuple[dict[str, Any], bool]:
    inventory: dict[str, Any] = {}
    ready = True
    for name, path in sorted(artifacts.items()):
        present = path.is_file()
        entry: dict[str, Any] = {
            "path": str(path),
            "present": present,
        }
        if present:
            entry.update({"sha256": sha256_file(path), "bytes": path.stat().st_size})
        else:
            entry["error"] = "artifact is absent"
            ready = False
        inventory[name] = entry
    return inventory, ready


def build_manifest(
    *,
    root: Path,
    source_head_sha: str,
    source_head_tree: str,
    base_sha: str,
    deterministic_merge_sha: str | None,
    github_synthetic_merge_sha: str | None,
    workflow_sha: str,
    final_merge_sha: str | None,
    workflow_run_id: str,
    workflow_run_attempt: str,
    runner_image: str,
    target_triple: str,
    runtime_status_source: Path,
    checked_in_status_source: Path,
    qualification_receipts: dict[str, Path],
    artifacts: dict[str, Path],
    crash_receipts: Path | None,
) -> dict[str, Any]:
    for label, oid in (
        ("source head", source_head_sha),
        ("source tree", source_head_tree),
        ("base", base_sha),
        ("workflow", workflow_sha),
    ):
        require_oid(oid, label)
    for label, oid in (
        ("deterministic merge", deterministic_merge_sha),
        ("GitHub synthetic merge", github_synthetic_merge_sha),
        ("final merge", final_merge_sha),
    ):
        require_oid(oid, label, optional=True)
    if not workflow_run_id or not workflow_run_attempt or not runner_image or not target_triple:
        raise ValueError("workflow, runner, and target identity must be non-empty")

    root = root.resolve()
    checked_status = load_json(checked_in_status_source)
    require_oid(checked_status.get("asOfCommit"), "checked-in status anchor")
    require_oid(checked_status.get("asOfTree"), "checked-in status tree")

    runtime_status = validate_runtime_status(
        path=runtime_status_source,
        source_head_sha=source_head_sha,
        source_head_tree=source_head_tree,
        base_sha=base_sha,
        deterministic_merge_sha=deterministic_merge_sha,
        github_synthetic_merge_sha=github_synthetic_merge_sha,
        workflow_sha=workflow_sha,
        final_merge_sha=final_merge_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        runner_image=runner_image,
        target_triple=target_triple,
    )
    qualification = {
        kind: qualification_receipt_status(
            path=qualification_receipts.get(kind),
            kind=kind,
            source_head_sha=source_head_sha,
            source_head_tree=source_head_tree,
            base_sha=base_sha,
            deterministic_merge_sha=deterministic_merge_sha,
            workflow_sha=workflow_sha,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            runner_image=runner_image,
            target_triple=target_triple,
        )
        for kind in REQUIRED_QUALIFICATION_RECEIPTS
    }
    crash = crash_receipt_status(
        directory=crash_receipts,
        source_head_sha=source_head_sha,
        source_head_tree=source_head_tree,
        base_sha=base_sha,
        workflow_sha=workflow_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        runner_image=runner_image,
        target_triple=target_triple,
    )
    artifact_hashes, artifacts_ready = artifact_inventory(artifacts)

    test_paths = [
        path
        for base in (
            root / "codex-rs/hepta-evidence/src",
            root / "codex-rs/hepta-evidence/tests",
            root / "codex-rs/hepta-agentd/tests",
            root / "scripts/tests",
        )
        for path in tree_files(base)
        if "test" in path.name or path.suffix in {".rs", ".py"}
    ]
    docs_paths = tree_files(root / "docs/modules/kernel.evidence") + tree_files(
        root / "docs/lane-a-foundation/kernel.evidence"
    )
    migrations = tree_files(root / "codex-rs/hepta-evidence/migrations")
    implementation_map = root / "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json"
    cargo_lock = root / "codex-rs/Cargo.lock"

    exact_source = bool(qualification["exact_source"]["passed"])
    deterministic_merge = bool(qualification["deterministic_merge"]["passed"])
    metadata = bool(qualification["metadata"]["passed"])
    publication = bool(qualification["publication_diagnostics"]["passed"])
    crash_ready = all(bool(entry["passed"]) for entry in crash.values())
    runtime_status_exact = bool(runtime_status["exact"])
    repository_controlled_ready = bool(
        exact_source
        and deterministic_merge
        and metadata
        and publication
        and crash_ready
        and runtime_status_exact
        and artifacts_ready
    )
    final_merge_requalified = bool(
        final_merge_sha
        and final_merge_sha == source_head_sha
        and repository_controlled_ready
    )

    blockers: list[str] = []
    for name, entry in qualification.items():
        if not entry["passed"]:
            blockers.append(f"qualification:{name}")
    if not runtime_status_exact:
        blockers.append("runtime_status_source_identity")
    if not crash_ready:
        blockers.append("crash_matrix")
    if not artifacts_ready:
        blockers.append("artifact_inventory")
    if not final_merge_requalified:
        blockers.append("real_merge_sha_not_requalified")
    blockers.extend(
        [
            "independent_acceptance_absent",
            "authenticated_frontier_authority_acceptance_absent",
            "external_monotonic_anchor_acceptance_absent",
            "operator_activation_absent",
            "release_authority_absent",
        ]
    )

    return {
        "schema_version": 2,
        "module": "kernel.evidence",
        "source_head_sha": source_head_sha,
        "source_head_tree": source_head_tree,
        "base_sha": base_sha,
        "deterministic_merge_sha": deterministic_merge_sha,
        "github_synthetic_merge_sha": github_synthetic_merge_sha,
        "workflow_sha": workflow_sha,
        "final_merge_sha": final_merge_sha,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "runner_image": runner_image,
        "target_triple": target_triple,
        "Cargo.lock_hash": sha256_file(cargo_lock),
        "test_set_hash": inventory_hash(root, test_paths),
        "migration_hash": inventory_hash(root, migrations),
        "implementation_map_hash": sha256_file(implementation_map),
        "documentation_hash": inventory_hash(root, docs_paths),
        "artifact_hashes": artifact_hashes,
        "status_identity": {
            "runtime": {
                key: value
                for key, value in runtime_status.items()
                if key != "value"
            },
            "checked_in_implementation_source": {
                "path": str(checked_in_status_source),
                "sha256": sha256_file(checked_in_status_source),
                "asOfCommit": checked_status.get("asOfCommit"),
                "asOfTree": checked_status.get("asOfTree"),
                "role": "ancestor implementation provenance only",
            },
        },
        "qualification_receipts": qualification,
        "crash_consistency_receipts": crash,
        "readiness": {
            "repository_controlled_ready": repository_controlled_ready,
            "local_integrity_ready": repository_controlled_ready,
            "authenticated_frontier_protocol_ready": repository_controlled_ready,
            "authenticated_frontier_authority_ready": False,
            "external_rollback_anchor_ready": False,
            "crash_matrix_ready": crash_ready,
            "runtime_status_exact": runtime_status_exact,
            "artifact_inventory_ready": artifacts_ready,
            "exact_source_qualified": exact_source,
            "deterministic_merge_qualified": deterministic_merge,
            "metadata_qualified": metadata,
            "publication_diagnostics_qualified": publication,
            "final_merge_requalified": final_merge_requalified,
            "independent_acceptance": False,
            "operator_activation": False,
            "production_activation": False,
            "promotion_approved": False,
            "release_approved": False,
        },
        "blockers": blockers,
        "authority": {
            "self_issued_independent_acceptance": False,
            "self_issued_external_activation": False,
            "self_issued_operator_activation": False,
            "self_issued_promotion": False,
            "self_issued_release_approval": False,
        },
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".readiness-"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
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
    parser.add_argument("--runtime-status-source", type=Path, required=True)
    parser.add_argument(
        "--checked-in-status-source",
        type=Path,
        default=Path("qualification/kernel-evidence/STATUS_SOURCE.json"),
    )
    parser.add_argument("--qualification-receipt", action="append", default=[])
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--crash-receipts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        root = args.root.resolve()
        checked_in_status = (
            (root / args.checked_in_status_source).resolve()
            if not args.checked_in_status_source.is_absolute()
            else args.checked_in_status_source
        )
        manifest = build_manifest(
            root=root,
            source_head_sha=args.source_head_sha,
            source_head_tree=args.source_head_tree,
            base_sha=args.base_sha,
            deterministic_merge_sha=args.deterministic_merge_sha or None,
            github_synthetic_merge_sha=args.github_synthetic_merge_sha or None,
            workflow_sha=args.workflow_sha,
            final_merge_sha=args.final_merge_sha or None,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            runner_image=args.runner_image,
            target_triple=args.target_triple,
            runtime_status_source=args.runtime_status_source,
            checked_in_status_source=checked_in_status,
            qualification_receipts=parse_named_paths(args.qualification_receipt),
            artifacts=parse_named_paths(args.artifact),
            crash_receipts=args.crash_receipts,
        )
        atomic_json(args.output, manifest)
        print(json.dumps(manifest, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ready": False, "error": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
