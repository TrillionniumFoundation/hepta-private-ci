#!/usr/bin/env python3
"""Build one fail-closed runtime readiness manifest for kernel.evidence.

The manifest binds execution evidence to immutable Git objects and hashes the
source-controlled inputs that define the qualification surface. It never grants
independent acceptance, production activation, promotion, or release authority.
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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_hash(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    selected = sorted({path.resolve() for path in paths if path.is_file()})
    for path in selected:
        relative = path.relative_to(root.resolve()).as_posix().encode("utf-8")
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
        if not separator or not name or name in parsed:
            raise ValueError(f"expected one unique NAME=PATH value, got {value!r}")
        parsed[name] = Path(raw_path)
    return parsed


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def receipt_passed(path: Path, source_sha: str) -> tuple[bool, str | None]:
    try:
        value = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return False, str(error)
    candidate = value.get("candidate")
    bound_sha = value.get("testedSha") or value.get("tested_sha")
    if bound_sha is None and isinstance(candidate, dict):
        bound_sha = candidate.get("sourceCommit") or candidate.get("testedCommit")
    if bound_sha not in (None, source_sha):
        return False, "receipt is bound to a different source candidate"
    passed = value.get("qualified") is True or value.get("passed") is True
    if not passed:
        return False, "receipt is not terminal success"
    return True, None


def crash_receipt_status(directory: Path | None, source_sha: str, target: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for scenario in REQUIRED_CRASH_SCENARIOS:
        path = None if directory is None else directory / f"{scenario}.json"
        entry: dict[str, Any] = {"present": bool(path and path.is_file()), "passed": False}
        if path and path.is_file():
            try:
                value = load_json(path)
                entry["sha256"] = sha256_file(path)
                entry["passed"] = (
                    value.get("schemaVersion") == 1
                    and value.get("module") == "kernel.evidence"
                    and value.get("scenario") == scenario
                    and value.get("testedSha") == source_sha
                    and value.get("targetTriple") == target
                    and value.get("status") == "passed"
                    and value.get("exitCode") == 0
                    and isinstance(value.get("command"), str)
                    and bool(value.get("command"))
                    and isinstance(value.get("startedAtUnixMs"), int)
                    and isinstance(value.get("finishedAtUnixMs"), int)
                    and value["finishedAtUnixMs"] >= value["startedAtUnixMs"]
                    and isinstance(value.get("logSha256"), str)
                    and SHA256.fullmatch(value["logSha256"]) is not None
                )
                if not entry["passed"]:
                    entry["error"] = "receipt schema, candidate, target, or terminal result is invalid"
            except (OSError, ValueError, json.JSONDecodeError) as error:
                entry["error"] = str(error)
        else:
            entry["error"] = "required scenario receipt is absent"
        result[scenario] = entry
    return result


def build_manifest(
    *,
    root: Path,
    source_head_sha: str,
    base_sha: str,
    deterministic_merge_sha: str | None,
    github_synthetic_merge_sha: str | None,
    workflow_sha: str,
    final_merge_sha: str | None,
    workflow_run_id: str,
    runner_image: str,
    target_triple: str,
    status_source: Path,
    qualification_receipts: dict[str, Path],
    artifacts: dict[str, Path],
    crash_receipts: Path | None,
) -> dict[str, Any]:
    for label, oid in (
        ("source head", source_head_sha),
        ("base", base_sha),
        ("workflow", workflow_sha),
    ):
        if OID.fullmatch(oid) is None:
            raise ValueError(f"{label} must be a full lowercase Git object id")
    for label, oid in (
        ("deterministic merge", deterministic_merge_sha),
        ("GitHub synthetic merge", github_synthetic_merge_sha),
        ("final merge", final_merge_sha),
    ):
        if oid and OID.fullmatch(oid) is None:
            raise ValueError(f"{label} must be empty or a full lowercase Git object id")
    if not workflow_run_id or not runner_image or not target_triple:
        raise ValueError("workflow, runner, and target identity must be non-empty")

    root = root.resolve()
    status = load_json(status_source)
    checked_in_as_of = status.get("asOfCommit")
    qualification: dict[str, Any] = {}
    for name in REQUIRED_QUALIFICATION_RECEIPTS:
        path = qualification_receipts.get(name)
        if path is None or not path.is_file():
            qualification[name] = {"present": False, "passed": False, "error": "receipt is absent"}
            continue
        passed, error = receipt_passed(path, source_head_sha)
        qualification[name] = {
            "present": True,
            "passed": passed,
            "sha256": sha256_file(path),
            "error": error,
        }

    crash = crash_receipt_status(crash_receipts, source_head_sha, target_triple)
    artifact_hashes = {
        name: {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for name, path in sorted(artifacts.items())
        if path.is_file()
    }

    test_paths = [
        path
        for base in (
            root / "codex-rs/hepta-evidence/src",
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

    exact_source = qualification["exact_source"]["passed"]
    deterministic_merge = qualification["deterministic_merge"]["passed"]
    metadata = qualification["metadata"]["passed"]
    publication = qualification["publication_diagnostics"]["passed"]
    crash_ready = all(entry["passed"] for entry in crash.values())
    local_integrity_ready = exact_source and deterministic_merge and metadata and publication

    blockers: list[str] = []
    for name, entry in qualification.items():
        if not entry["passed"]:
            blockers.append(f"qualification:{name}")
    if not crash_ready:
        blockers.append("crash_matrix")
    if not final_merge_sha:
        blockers.append("real_merge_sha_not_requalified")
    blockers.extend(
        [
            "independent_acceptance_absent",
            "external_monotonic_anchor_acceptance_absent",
            "operator_activation_absent",
            "release_authority_absent",
        ]
    )

    return {
        "schema_version": 1,
        "module": "kernel.evidence",
        "source_head_sha": source_head_sha,
        "base_sha": base_sha,
        "deterministic_merge_sha": deterministic_merge_sha,
        "github_synthetic_merge_sha": github_synthetic_merge_sha,
        "workflow_sha": workflow_sha,
        "final_merge_sha": final_merge_sha,
        "workflow_run_id": workflow_run_id,
        "runner_image": runner_image,
        "target_triple": target_triple,
        "Cargo.lock_hash": sha256_file(cargo_lock),
        "test_set_hash": inventory_hash(root, test_paths),
        "migration_hash": inventory_hash(root, migrations),
        "implementation_map_hash": sha256_file(implementation_map),
        "documentation_hash": inventory_hash(root, docs_paths),
        "artifact_hashes": artifact_hashes,
        "status_identity": {
            "checked_in_as_of_commit": checked_in_as_of,
            "runtime_as_of_commit": source_head_sha,
            "runtime_matches_tested_sha": True,
            "checked_in_is_source_anchor": OID.fullmatch(str(checked_in_as_of or "")) is not None,
            "note": (
                "A Git commit cannot contain its own hash. The checked-in value is a provenance "
                "anchor; this runtime manifest is the exact tested-SHA status authority."
            ),
        },
        "qualification_receipts": qualification,
        "crash_consistency_receipts": crash,
        "readiness": {
            "local_integrity_ready": local_integrity_ready,
            "authenticated_frontier_ready": False,
            "external_rollback_anchor_ready": False,
            "crash_matrix_ready": crash_ready,
            "exact_source_qualified": exact_source,
            "deterministic_merge_qualified": deterministic_merge,
            "metadata_qualified": metadata,
            "publication_diagnostics_qualified": publication,
            "independent_acceptance": False,
            "production_activation": False,
            "release_approved": False,
        },
        "blockers": blockers,
        "authority": {
            "self_issued_independent_acceptance": False,
            "self_issued_production_activation": False,
            "self_issued_release_approval": False,
        },
    }


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".readiness-")
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
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--deterministic-merge-sha", default="")
    parser.add_argument("--github-synthetic-merge-sha", default="")
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--final-merge-sha", default="")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--target-triple", required=True)
    parser.add_argument(
        "--status-source",
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
        manifest = build_manifest(
            root=root,
            source_head_sha=args.source_head_sha,
            base_sha=args.base_sha,
            deterministic_merge_sha=args.deterministic_merge_sha or None,
            github_synthetic_merge_sha=args.github_synthetic_merge_sha or None,
            workflow_sha=args.workflow_sha,
            final_merge_sha=args.final_merge_sha or None,
            workflow_run_id=args.workflow_run_id,
            runner_image=args.runner_image,
            target_triple=args.target_triple,
            status_source=(root / args.status_source).resolve()
            if not args.status_source.is_absolute()
            else args.status_source,
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
