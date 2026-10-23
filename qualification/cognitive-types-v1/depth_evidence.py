#!/usr/bin/env python3
"""Prepare, seal, and independently verify cognitive.types depth evidence.

This helper binds one immutable source/base pair to exact-head and deterministic
synthetic-merge candidates. It inventories complete uploaded evidence, verifies
all expected consumer, owner, and fuzz artifacts, and preserves explicit
non-claims for product acceptance, activation, and release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import evidence_inventory as inventory
import run_qualification as qualification

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
KINDS = ("exact-head", "synthetic-merge")
CONSUMERS = {
    "cognitive.read": "codex-hepta-cognitive-read",
    "cognitive.store": "codex-hepta-cognitive-store",
    "memory.retrieval": "codex-hepta-memory-retrieval",
    "compact.engine": "codex-hepta-compact-engine",
    "intelligence.control": "codex-hepta-intelligence",
}
OUTCOMES = {
    "consumer": ("identity", "select", "toolchain", "format", "check", "clippy", "test"),
    "owner": ("identity", "prepare", "clippy", "store", "recall", "shared"),
    "fuzz": ("identity", "setup", "seed", "campaign", "clean"),
}
RESULT_SCHEMAS = {
    "consumer": "hepta.cognitive-types.consumer-depth-evidence.v1",
    "owner": "hepta.cognitive-types.owner-depth-evidence.v1",
    "fuzz": "hepta.cognitive-types.decoder-fuzz-evidence.v1",
}
CANDIDATE_SCHEMA = "hepta.cognitive-types.depth-candidate.v1"
ARTIFACT_SCHEMA = "hepta.cognitive-types.depth-artifact.v1"
AGGREGATE_SCHEMA = "hepta.cognitive-types.depth-evidence-matrix.v1"


class EvidenceError(ValueError):
    """Depth evidence is missing, malformed, stale, or identity-inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def reject_constant(value: str) -> None:
    raise EvidenceError(f"non-finite JSON value is forbidden: {value}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    require(not path.is_symlink() and path.is_file(), f"missing or unsafe JSON file: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid JSON in {path.name}: {error}") from error
    require(isinstance(value, dict), f"JSON root must be an object: {path.name}")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sealed_json(path: Path, value: dict[str, Any]) -> str:
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    path.with_suffix(".sha256").write_text(digest + "\n", encoding="ascii")
    return digest


def require_sha(value: object, label: str) -> str:
    require(isinstance(value, str) and SHA40.fullmatch(value) is not None,
            f"invalid {label}")
    return value


def require_false(value: object, label: str) -> None:
    require(value is False, f"{label} must remain false")


def candidate_receipt(root: Path, source: str, base: str, kind: str) -> dict[str, Any]:
    require_sha(source, "source commit")
    require_sha(base, "base commit")
    require(kind in KINDS, "unknown candidate kind")
    identity = qualification.prepare_candidate(root, source, base, kind)
    return {
        "schema": CANDIDATE_SCHEMA,
        **identity,
        "product_acceptance": False,
        "activation": False,
        "release": False,
    }


def verify_candidate(value: dict[str, Any], source: str, base: str, kind: str) -> None:
    required = {
        "schema", "source_commit", "source_tree", "base_commit", "base_tree",
        "candidate_kind", "candidate_commit", "candidate_tree", "parents",
        "identity_valid", "product_acceptance", "activation", "release",
    }
    require(set(value) == required, "candidate receipt fields changed")
    require(value["schema"] == CANDIDATE_SCHEMA, "candidate receipt schema mismatch")
    require(value["source_commit"] == source and value["base_commit"] == base,
            "candidate source/base mismatch")
    require(value["candidate_kind"] == kind, "candidate kind mismatch")
    for field in ("source_commit", "source_tree", "base_commit", "base_tree",
                  "candidate_commit", "candidate_tree"):
        require_sha(value[field], field)
    require(value["identity_valid"] is True, "candidate identity is not valid")
    require(isinstance(value["parents"], list)
            and all(isinstance(item, str) and SHA40.fullmatch(item) for item in value["parents"]),
            "invalid candidate parents")
    if kind == "exact-head":
        require(value["candidate_commit"] == source, "exact-head candidate drift")
    else:
        require(value["parents"] == [base, source], "synthetic merge parent drift")
    for field in ("product_acceptance", "activation", "release"):
        require_false(value[field], f"candidate.{field}")


def verify_results(value: dict[str, Any], role: str, kind: str,
                   consumer: str | None) -> None:
    require(role in OUTCOMES, "unknown depth evidence role")
    require(value.get("schema") == RESULT_SCHEMAS[role], "result schema mismatch")
    require(value.get("candidate") == kind, "result candidate mismatch")
    outcomes = value.get("outcomes")
    require(isinstance(outcomes, dict) and set(outcomes) == set(OUTCOMES[role])
            and len(outcomes) == len(OUTCOMES[role]), "result outcome plan changed")
    require(all(outcomes[name] == "success" for name in OUTCOMES[role]),
            "depth execution contains a non-success outcome")
    if role == "consumer":
        require(consumer in CONSUMERS, "unknown consumer")
        require(value.get("consumer") == consumer, "consumer result mismatch")
        require(value.get("package") == CONSUMERS[consumer], "consumer package mismatch")
        require_false(value.get("compatibility_retired"), "compatibility_retired")
    elif role == "owner":
        require_false(value.get("owner_currentness_cached"), "owner_currentness_cached")
    else:
        require_false(value.get("campaign_is_product_acceptance"),
                      "campaign_is_product_acceptance")
    for field in ("product_acceptance", "activation", "release"):
        if field in value:
            require_false(value[field], field)
    expected = {
        "consumer": {"schema", "consumer", "package", "candidate", "outcomes",
                     "product_acceptance", "compatibility_retired", "activation", "release"},
        "owner": {"schema", "candidate", "outcomes", "owner_currentness_cached",
                  "product_acceptance", "activation", "release"},
        "fuzz": {"schema", "candidate", "outcomes", "campaign_is_product_acceptance",
                 "activation", "release"},
    }[role]
    require(set(value) == expected, "result fields changed")


def seal_artifact(directory: Path, role: str, source: str, base: str, kind: str,
                  run_id: str, run_attempt: str, consumer: str | None = None) -> dict[str, Any]:
    require(not directory.is_symlink() and directory.is_dir(), "missing depth evidence directory")
    require(role in OUTCOMES, "unknown role")
    require(kind in KINDS, "unknown candidate kind")
    require(isinstance(run_id, str) and run_id.isdecimal() and run_id != "0", "invalid run id")
    require(isinstance(run_attempt, str) and run_attempt.isdecimal()
            and int(run_attempt) > 0, "invalid run attempt")
    if role == "consumer":
        require(consumer in CONSUMERS, "unknown consumer")
    else:
        require(consumer is None, "unexpected consumer for non-consumer evidence")
    candidate = load_json(directory / "candidate.json")
    results = load_json(directory / "results.json")
    verify_candidate(candidate, source, base, kind)
    passed = True
    error = None
    try:
        verify_results(results, role, kind, consumer)
    except EvidenceError as exc:
        passed = False
        error = str(exc)
    evidence_files = inventory.collect_inventory(directory)
    required_files = {
        "consumer": ["candidate.json", "results.json", "toolchain.log", "format.log",
                     "check.log", "clippy.log", "tests.log"],
        "owner": ["candidate.json", "results.json", "clippy.log", "store-writer.log",
                  "canonical-recall.log", "shared-experience.log"],
        "fuzz": ["candidate.json", "results.json", "toolchain.log",
                 "campaign-seconds.txt", "corpus/modality-span-envelope-v1",
                 "fuzz.log", "source-status.txt"],
    }[role]
    inventory.require_files(evidence_files, required_files)
    file_rows = {row["path"]: row for row in evidence_files["files"]}
    for name in required_files:
        if name != "source-status.txt":
            require(file_rows[name]["bytes"] > 0, f"empty required evidence file: {name}")
    if role == "fuzz":
        require((directory / "source-status.txt").read_bytes() == b"",
                "fuzz campaign changed the source worktree")
        seconds = (directory / "campaign-seconds.txt").read_text(encoding="ascii").strip()
        require(seconds in ("180", "900"), "unexpected fuzz campaign duration")
    receipt = {
        "schema": ARTIFACT_SCHEMA,
        "role": role,
        "consumer": consumer,
        "source_commit": source,
        "base_commit": base,
        "candidate_kind": kind,
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "parents": candidate["parents"],
        "run_id": run_id,
        "run_attempt": run_attempt,
        "evidence_files": evidence_files,
        "evidence_passed": passed,
        "evidence_error": error,
        "product_acceptance": False,
        "activation": False,
        "release": False,
    }
    write_sealed_json(directory / "receipt.json", receipt)
    return receipt


def load_receipt(directory: Path) -> dict[str, Any]:
    checksum = directory / "receipt.sha256"
    require(not checksum.is_symlink() and checksum.is_file(), "missing artifact checksum")
    expected = checksum.read_text(encoding="ascii").strip()
    require(SHA64.fullmatch(expected) is not None, "invalid artifact checksum")
    receipt_path = directory / "receipt.json"
    require(file_sha256(receipt_path) == expected, "artifact receipt checksum mismatch")
    return load_json(receipt_path)


def expected_artifacts(source: str, attempt: str, event: str) -> dict[str, tuple[str, str, str | None]]:
    require(event in ("pull_request", "schedule", "workflow_dispatch"), "unsupported event")
    kinds = KINDS if event == "pull_request" else ("exact-head",)
    expected: dict[str, tuple[str, str, str | None]] = {}
    for kind in kinds:
        for consumer in CONSUMERS:
            name = f"cognitive-types-consumer-{consumer}-{kind}-{source}-{attempt}"
            expected[name] = ("consumer", kind, consumer)
        expected[f"cognitive-types-owner-{kind}-{source}-{attempt}"] = ("owner", kind, None)
        expected[f"cognitive-types-fuzz-{kind}-{source}-{attempt}"] = ("fuzz", kind, None)
    return expected


def verify_artifact(directory: Path, role: str, source: str, base: str, kind: str,
                    run_id: str, attempt: str, consumer: str | None, event: str) -> dict[str, Any]:
    require(not directory.is_symlink() and directory.is_dir(), "missing or symlinked artifact")
    receipt = load_receipt(directory)
    required = {
        "schema", "role", "consumer", "source_commit", "base_commit", "candidate_kind",
        "candidate_commit", "candidate_tree", "parents", "run_id", "run_attempt",
        "evidence_files", "evidence_passed", "evidence_error", "product_acceptance",
        "activation", "release",
    }
    require(set(receipt) == required and receipt["schema"] == ARTIFACT_SCHEMA,
            "artifact receipt fields or schema changed")
    require(receipt["role"] == role and receipt["consumer"] == consumer,
            "artifact role mismatch")
    require(receipt["source_commit"] == source and receipt["base_commit"] == base,
            "artifact source/base mismatch")
    require(receipt["candidate_kind"] == kind, "artifact candidate kind mismatch")
    require(receipt["run_id"] == run_id and receipt["run_attempt"] == attempt,
            "artifact workflow identity mismatch")
    require(receipt["evidence_passed"] is True and receipt["evidence_error"] is None,
            "artifact does not contain passing evidence")
    for field in ("candidate_commit", "candidate_tree"):
        require_sha(receipt[field], field)
    if kind == "exact-head":
        require(receipt["candidate_commit"] == source, "artifact exact-head drift")
    else:
        require(receipt["parents"] == [base, source], "artifact merge parents drift")
    for field in ("product_acceptance", "activation", "release"):
        require_false(receipt[field], field)
    inventory.verify_inventory(directory, receipt["evidence_files"])
    candidate = load_json(directory / "candidate.json")
    results = load_json(directory / "results.json")
    verify_candidate(candidate, source, base, kind)
    verify_results(results, role, kind, consumer)
    if role == "fuzz":
        expected_seconds = "180" if event == "pull_request" else "900"
        observed_seconds = (directory / "campaign-seconds.txt").read_text(encoding="ascii").strip()
        require(observed_seconds == expected_seconds, "fuzz duration does not match the event policy")
        require((directory / "source-status.txt").read_bytes() == b"",
                "fuzz evidence reports a dirty source worktree")
    require(candidate["candidate_commit"] == receipt["candidate_commit"]
            and candidate["candidate_tree"] == receipt["candidate_tree"],
            "candidate and artifact receipt disagree")
    return receipt


def verify_matrix(evidence: Path, source: str, base: str, event: str,
                  run_id: str, attempt: str) -> dict[str, Any]:
    require_sha(source, "source commit")
    require_sha(base, "base commit")
    require(isinstance(run_id, str) and run_id.isdecimal() and run_id != "0", "invalid run id")
    require(isinstance(attempt, str) and attempt.isdecimal() and int(attempt) > 0,
            "invalid run attempt")
    require(not evidence.is_symlink() and evidence.is_dir(), "missing evidence root")
    expected = expected_artifacts(source, attempt, event)
    observed = {entry.name: entry for entry in evidence.iterdir()}
    require(set(observed) == set(expected), "missing, extra, or misnamed depth artifacts")
    artifacts = []
    for name in sorted(expected):
        role, kind, consumer = expected[name]
        receipt = verify_artifact(observed[name], role, source, base, kind,
                                  run_id, attempt, consumer, event)
        artifacts.append({
            "artifact": name,
            "role": role,
            "consumer": consumer,
            "candidate_kind": kind,
            "candidate_commit": receipt["candidate_commit"],
            "candidate_tree": receipt["candidate_tree"],
            "receipt_sha256": file_sha256(observed[name] / "receipt.json"),
            "evidence_total_bytes": receipt["evidence_files"]["total_bytes"],
            "evidence_file_count": len(receipt["evidence_files"]["files"]),
        })
    return {
        "schema": AGGREGATE_SCHEMA,
        "source_commit": source,
        "base_commit": base,
        "event": event,
        "run_id": run_id,
        "run_attempt": attempt,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "depth_evidence_passed": True,
        "product_acceptance": False,
        "compatibility_retired": False,
        "activation": False,
        "release": False,
    }


def write_refusal(output: Path, args: argparse.Namespace, error: Exception) -> None:
    value = {
        "schema": AGGREGATE_SCHEMA,
        "source_commit": getattr(args, "source", ""),
        "base_commit": getattr(args, "base", ""),
        "event": getattr(args, "event", ""),
        "run_id": getattr(args, "run_id", ""),
        "run_attempt": getattr(args, "run_attempt", ""),
        "artifact_count": 0,
        "artifacts": [],
        "depth_evidence_passed": False,
        "evidence_error": f"{type(error).__name__}: {error}",
        "product_acceptance": False,
        "compatibility_retired": False,
        "activation": False,
        "release": False,
    }
    write_sealed_json(output, value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--base", required=True)
    prepare.add_argument("--kind", choices=KINDS, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    seal = commands.add_parser("seal")
    seal.add_argument("--directory", type=Path, required=True)
    seal.add_argument("--role", choices=tuple(OUTCOMES), required=True)
    seal.add_argument("--consumer", choices=tuple(CONSUMERS))
    seal.add_argument("--source", required=True)
    seal.add_argument("--base", required=True)
    seal.add_argument("--kind", choices=KINDS, required=True)
    seal.add_argument("--run-id", required=True)
    seal.add_argument("--run-attempt", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--evidence", type=Path, required=True)
    verify.add_argument("--source", required=True)
    verify.add_argument("--base", required=True)
    verify.add_argument("--event", choices=("pull_request", "schedule", "workflow_dispatch"), required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--run-attempt", required=True)
    verify.add_argument("--output", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "prepare":
        receipt = candidate_receipt(Path.cwd(), args.source, args.base, args.kind)
        write_sealed_json(args.output, receipt)
        args.output.with_suffix(".sha256").unlink(missing_ok=True)
        return 0
    if args.command == "seal":
        receipt = seal_artifact(args.directory, args.role, args.source, args.base,
                                args.kind, args.run_id, args.run_attempt, args.consumer)
        return 0 if receipt["evidence_passed"] else 1
    try:
        report = verify_matrix(args.evidence, args.source, args.base, args.event,
                               args.run_id, args.run_attempt)
        write_sealed_json(args.output, report)
        return 0
    except (EvidenceError, ValueError, OSError) as error:
        write_refusal(args.output, args, error)
        print(f"depth evidence rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
