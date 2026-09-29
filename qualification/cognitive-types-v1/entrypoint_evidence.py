#!/usr/bin/env python3
"""Seal and verify fixed-candidate evidence for five canonical product entrypoints.

The evidence proves only that the reviewed, non-empty Rust test module for each
existing consumer was discovered and passed on one immutable candidate. It is
not product acceptance, compatibility retirement, activation, or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
TEST_LINE = re.compile(r"^(.+): test$")
KINDS = ("exact-head", "synthetic-merge")
CONSUMERS: dict[str, tuple[str, str]] = {
    "cognitive.read": ("codex-hepta-cognitive-read", "authoritative::tests"),
    "cognitive.store": ("codex-hepta-cognitive-store", "v2::product_tests"),
    "memory.retrieval": ("codex-hepta-memory-retrieval", "generation_bound::tests"),
    "compact.engine": ("codex-hepta-compact-engine", "qualified::tests"),
    "intelligence.control": ("codex-hepta-intelligence", "canonical::tests"),
}
CANDIDATE_SCHEMA = "hepta.cognitive-types.depth-candidate.v1"
RESULT_SCHEMA = "hepta.cognitive-types.entrypoint-execution.v1"
RECEIPT_SCHEMA = "hepta.cognitive-types.entrypoint-artifact.v1"
AGGREGATE_SCHEMA = "hepta.cognitive-types.entrypoint-matrix.v1"
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_FILES = 16
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_TESTS = 4096
MAX_TEST_NAME_BYTES = 512


class EvidenceError(ValueError):
    """Entrypoint evidence is missing, malformed, stale, or inconsistent."""


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
    try:
        raw = read_regular(path).decode("utf-8")
        value = json.loads(
            raw,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid JSON in {path.name}: {error}") from error
    require(isinstance(value, dict), f"JSON root must be an object: {path.name}")
    return value


def read_regular(path: Path, maximum: int = MAX_LOG_BYTES) -> bytes:
    require(type(maximum) is int and 0 < maximum <= MAX_TOTAL_BYTES, "invalid byte limit")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), f"unsafe file: {path.name}")
    require(0 <= info.st_size <= maximum, f"oversized file: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        identity = (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        require(
            stat.S_ISREG(before.st_mode)
            and (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            == identity,
            f"file changed before reading: {path.name}",
        )
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    final = path.lstat()
    require(
        len(data) == info.st_size
        and all(
            (
                row.st_dev,
                row.st_ino,
                row.st_size,
                row.st_mtime_ns,
                row.st_ctime_ns,
            )
            == identity
            for row in (after, final)
        ),
        f"file changed while reading: {path.name}",
    )
    return data


def require_sha(value: object, label: str) -> str:
    require(isinstance(value, str) and SHA40.fullmatch(value) is not None, f"invalid {label}")
    return value


def verify_candidate(value: dict[str, Any], source: str, base: str, kind: str) -> None:
    expected = {
        "schema",
        "source_commit",
        "source_tree",
        "base_commit",
        "base_tree",
        "candidate_kind",
        "candidate_commit",
        "candidate_tree",
        "parents",
        "identity_valid",
        "product_acceptance",
        "activation",
        "release",
    }
    require(set(value) == expected, "candidate fields changed")
    require(value["schema"] == CANDIDATE_SCHEMA, "candidate schema mismatch")
    require(value["source_commit"] == source and value["base_commit"] == base, "source/base mismatch")
    require(value["candidate_kind"] == kind, "candidate kind mismatch")
    for field in (
        "source_commit",
        "source_tree",
        "base_commit",
        "base_tree",
        "candidate_commit",
        "candidate_tree",
    ):
        require_sha(value[field], field)
    require(value["identity_valid"] is True, "candidate identity invalid")
    require(
        isinstance(value["parents"], list)
        and all(isinstance(item, str) and SHA40.fullmatch(item) for item in value["parents"]),
        "invalid candidate parents",
    )
    if kind == "exact-head":
        require(value["candidate_commit"] == source, "exact-head candidate drift")
    else:
        require(value["parents"] == [base, source], "synthetic merge parent drift")
    for field in ("product_acceptance", "activation", "release"):
        require(value[field] is False, f"candidate {field} must remain false")


def parse_test_listing(raw: bytes, consumer: str) -> list[str]:
    require(consumer in CONSUMERS, "unknown consumer")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError("test listing is not UTF-8") from error
    test_filter = CONSUMERS[consumer][1]
    names: list[str] = []
    for line in text.splitlines():
        match = TEST_LINE.fullmatch(line.strip())
        if match is None:
            continue
        name = match.group(1)
        require(0 < len(name.encode("utf-8")) <= MAX_TEST_NAME_BYTES, "invalid test name length")
        require(
            name == test_filter or name.startswith(test_filter + "::"),
            "listed test escaped the reviewed entrypoint module",
        )
        names.append(name)
    require(0 < len(names) <= MAX_TESTS, "entrypoint listing found no bounded tests")
    require(len(names) == len(set(names)), "duplicate test name in listing")
    return sorted(names)


def result_value(
    candidate: dict[str, Any],
    consumer: str,
    list_log: Path,
    tests_log: Path,
    list_exit: int,
    test_exit: int,
) -> dict[str, Any]:
    require(consumer in CONSUMERS, "unknown consumer")
    require(type(list_exit) is int and type(test_exit) is int, "exit codes must be integers")
    listing = read_regular(list_log)
    tests = read_regular(tests_log)
    require(tests, "empty test execution log")
    names: list[str] = []
    error = None
    try:
        names = parse_test_listing(listing, consumer)
    except EvidenceError as exc:
        error = str(exc)
    package, test_filter = CONSUMERS[consumer]
    passed = list_exit == 0 and test_exit == 0 and error is None
    return {
        "schema": RESULT_SCHEMA,
        "consumer": consumer,
        "package": package,
        "test_filter": test_filter,
        "candidate_kind": candidate["candidate_kind"],
        "candidate_commit": candidate["candidate_commit"],
        "candidate_tree": candidate["candidate_tree"],
        "list_exit_code": list_exit,
        "test_exit_code": test_exit,
        "test_count": len(names),
        "test_names": names,
        "listing_bytes": len(listing),
        "listing_sha256": hashlib.sha256(listing).hexdigest(),
        "tests_bytes": len(tests),
        "tests_sha256": hashlib.sha256(tests).hexdigest(),
        "execution_passed": passed,
        "execution_error": error,
        "product_acceptance": False,
        "compatibility_retired": False,
        "activation": False,
        "release": False,
    }


def verify_result(
    value: dict[str, Any],
    candidate: dict[str, Any],
    consumer: str,
    list_log: Path,
    tests_log: Path,
) -> None:
    expected = {
        "schema",
        "consumer",
        "package",
        "test_filter",
        "candidate_kind",
        "candidate_commit",
        "candidate_tree",
        "list_exit_code",
        "test_exit_code",
        "test_count",
        "test_names",
        "listing_bytes",
        "listing_sha256",
        "tests_bytes",
        "tests_sha256",
        "execution_passed",
        "execution_error",
        "product_acceptance",
        "compatibility_retired",
        "activation",
        "release",
    }
    require(set(value) == expected and value["schema"] == RESULT_SCHEMA, "result fields changed")
    require(consumer in CONSUMERS and value["consumer"] == consumer, "consumer mismatch")
    package, test_filter = CONSUMERS[consumer]
    require(value["package"] == package and value["test_filter"] == test_filter, "entrypoint selection drift")
    require(
        value["candidate_kind"] == candidate["candidate_kind"]
        and value["candidate_commit"] == candidate["candidate_commit"]
        and value["candidate_tree"] == candidate["candidate_tree"],
        "result candidate drift",
    )
    require(type(value["list_exit_code"]) is int and value["list_exit_code"] == 0, "listing failed")
    require(type(value["test_exit_code"]) is int and value["test_exit_code"] == 0, "entrypoint tests failed")
    listing = read_regular(list_log)
    tests = read_regular(tests_log)
    require(tests, "empty test execution log")
    names = parse_test_listing(listing, consumer)
    require(value["test_names"] == names and value["test_count"] == len(names), "test inventory drift")
    require(
        type(value["listing_bytes"]) is int
        and value["listing_bytes"] == len(listing)
        and value["listing_sha256"] == hashlib.sha256(listing).hexdigest(),
        "listing bytes or digest mismatch",
    )
    require(
        type(value["tests_bytes"]) is int
        and value["tests_bytes"] == len(tests)
        and value["tests_sha256"] == hashlib.sha256(tests).hexdigest(),
        "test log bytes or digest mismatch",
    )
    require(value["execution_passed"] is True and value["execution_error"] is None, "execution did not pass")
    for field in ("product_acceptance", "compatibility_retired", "activation", "release"):
        require(value[field] is False, f"{field} must remain false")


def collect_inventory(directory: Path) -> dict[str, Any]:
    require(not directory.is_symlink() and directory.is_dir(), "missing evidence directory")
    rows: list[dict[str, Any]] = []
    total = 0
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(directory).as_posix()
        require(len(Path(relative).parts) <= 4 and len(relative.encode("utf-8")) <= 512, "unsafe evidence path")
        if relative in ("receipt.json", "receipt.sha256"):
            continue
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), f"unsafe evidence entry: {relative}")
        data = read_regular(path, MAX_LOG_BYTES)
        total += len(data)
        require(len(rows) < MAX_FILES and total <= MAX_TOTAL_BYTES, "evidence inventory limit exceeded")
        rows.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {"files": rows, "file_count": len(rows), "total_bytes": total}


def verify_inventory(directory: Path, expected: dict[str, Any]) -> None:
    require(isinstance(expected, dict), "missing inventory")
    observed = collect_inventory(directory)
    require(observed == expected, "evidence inventory mismatch")


def write_json(path: Path, value: dict[str, Any]) -> str:
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def write_result(
    candidate_path: Path,
    consumer: str,
    list_log: Path,
    tests_log: Path,
    list_exit: int,
    test_exit: int,
    output: Path,
) -> bool:
    candidate = load_json(candidate_path)
    source = require_sha(candidate.get("source_commit"), "candidate source")
    base = require_sha(candidate.get("base_commit"), "candidate base")
    kind = candidate.get("candidate_kind")
    require(kind in KINDS, "unknown candidate kind")
    verify_candidate(candidate, source, base, kind)
    value = result_value(candidate, consumer, list_log, tests_log, list_exit, test_exit)
    write_json(output, value)
    return value["execution_passed"] is True


def seal_artifact(
    directory: Path,
    source: str,
    base: str,
    kind: str,
    consumer: str,
    run_id: str,
    run_attempt: str,
) -> bool:
    require_sha(source, "source")
    require_sha(base, "base")
    require(kind in KINDS and consumer in CONSUMERS, "invalid artifact identity")
    require(run_id.isdecimal() and run_id != "0", "invalid run id")
    require(run_attempt.isdecimal() and int(run_attempt) > 0, "invalid run attempt")
    candidate = load_json(directory / "candidate.json")
    results = load_json(directory / "results.json")
    passed = True
    error = None
    try:
        verify_candidate(candidate, source, base, kind)
        verify_result(results, candidate, consumer, directory / "list.log", directory / "tests.log")
    except (EvidenceError, OSError) as exc:
        passed = False
        error = f"{type(exc).__name__}: {exc}"
    inventory = collect_inventory(directory)
    required = {
        "candidate.json",
        "results.json",
        "list.log",
        "tests.log",
        "toolchain.log",
        "source-status.txt",
    }
    observed = {row["path"] for row in inventory["files"]}
    if observed != required:
        passed = False
        error = error or "EvidenceError: artifact file set changed"
    else:
        rows = {row["path"]: row for row in inventory["files"]}
        if rows["toolchain.log"]["bytes"] == 0:
            passed = False
            error = error or "EvidenceError: empty toolchain identity"
        if (directory / "source-status.txt").read_bytes() != b"":
            passed = False
            error = error or "EvidenceError: source worktree changed"
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "consumer": consumer,
        "source_commit": source,
        "base_commit": base,
        "candidate_kind": kind,
        "candidate_commit": candidate.get("candidate_commit"),
        "candidate_tree": candidate.get("candidate_tree"),
        "parents": candidate.get("parents"),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "evidence_files": inventory,
        "evidence_passed": passed,
        "evidence_error": error,
        "product_acceptance": False,
        "compatibility_retired": False,
        "activation": False,
        "release": False,
    }
    digest = write_json(directory / "receipt.json", receipt)
    (directory / "receipt.sha256").write_text(digest + "\n", encoding="ascii")
    return passed


def expected_artifacts(source: str, attempt: str, event: str) -> dict[str, tuple[str, str]]:
    require(event in ("pull_request", "push", "workflow_dispatch", "schedule"), "unsupported event")
    kinds = KINDS if event == "pull_request" else ("exact-head",)
    return {
        f"cognitive-types-entrypoint-{consumer}-{kind}-{source}-{attempt}": (consumer, kind)
        for kind in kinds
        for consumer in CONSUMERS
    }


def load_receipt(directory: Path) -> dict[str, Any]:
    checksum = directory / "receipt.sha256"
    try:
        expected = read_regular(checksum, 1024).decode("ascii").strip()
    except UnicodeError as error:
        raise EvidenceError("receipt checksum is not ASCII") from error
    require(SHA64.fullmatch(expected) is not None, "invalid receipt checksum")
    receipt_path = directory / "receipt.json"
    receipt_bytes = read_regular(receipt_path)
    require(hashlib.sha256(receipt_bytes).hexdigest() == expected, "receipt checksum mismatch")
    return load_json(receipt_path)


def verify_artifact(
    directory: Path,
    source: str,
    base: str,
    kind: str,
    consumer: str,
    run_id: str,
    attempt: str,
) -> dict[str, Any]:
    receipt = load_receipt(directory)
    expected_fields = {
        "schema",
        "consumer",
        "source_commit",
        "base_commit",
        "candidate_kind",
        "candidate_commit",
        "candidate_tree",
        "parents",
        "run_id",
        "run_attempt",
        "evidence_files",
        "evidence_passed",
        "evidence_error",
        "product_acceptance",
        "compatibility_retired",
        "activation",
        "release",
    }
    require(set(receipt) == expected_fields and receipt["schema"] == RECEIPT_SCHEMA, "receipt fields changed")
    require(
        receipt["consumer"] == consumer
        and receipt["source_commit"] == source
        and receipt["base_commit"] == base
        and receipt["candidate_kind"] == kind
        and receipt["run_id"] == run_id
        and receipt["run_attempt"] == attempt,
        "receipt identity mismatch",
    )
    require(receipt["evidence_passed"] is True and receipt["evidence_error"] is None, "artifact did not pass")
    for field in ("product_acceptance", "compatibility_retired", "activation", "release"):
        require(receipt[field] is False, f"receipt {field} must remain false")
    verify_inventory(directory, receipt["evidence_files"])
    candidate = load_json(directory / "candidate.json")
    results = load_json(directory / "results.json")
    verify_candidate(candidate, source, base, kind)
    verify_result(results, candidate, consumer, directory / "list.log", directory / "tests.log")
    require(
        receipt["candidate_commit"] == candidate["candidate_commit"]
        and receipt["candidate_tree"] == candidate["candidate_tree"]
        and receipt["parents"] == candidate["parents"],
        "receipt candidate mismatch",
    )
    return receipt


def verify_matrix(
    evidence: Path,
    source: str,
    base: str,
    event: str,
    run_id: str,
    attempt: str,
) -> dict[str, Any]:
    require_sha(source, "source")
    require_sha(base, "base")
    require(not evidence.is_symlink() and evidence.is_dir(), "missing evidence root")
    expected = expected_artifacts(source, attempt, event)
    observed = {entry.name: entry for entry in evidence.iterdir()}
    require(set(observed) == set(expected), "entrypoint artifact set changed")
    artifacts = []
    for name, (consumer, kind) in sorted(expected.items()):
        receipt = verify_artifact(observed[name], source, base, kind, consumer, run_id, attempt)
        artifacts.append(
            {
                "artifact": name,
                "consumer": consumer,
                "candidate_kind": kind,
                "candidate_commit": receipt["candidate_commit"],
                "candidate_tree": receipt["candidate_tree"],
            }
        )
    return {
        "schema": AGGREGATE_SCHEMA,
        "source_commit": source,
        "base_commit": base,
        "event": event,
        "run_id": run_id,
        "run_attempt": attempt,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "entrypoint_evidence_passed": True,
        "product_acceptance": False,
        "compatibility_retired": False,
        "activation": False,
        "release": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record")
    record.add_argument("--candidate", type=Path, required=True)
    record.add_argument("--consumer", choices=sorted(CONSUMERS), required=True)
    record.add_argument("--list-log", type=Path, required=True)
    record.add_argument("--tests-log", type=Path, required=True)
    record.add_argument("--list-exit", type=int, required=True)
    record.add_argument("--test-exit", type=int, required=True)
    record.add_argument("--output", type=Path, required=True)

    seal = sub.add_parser("seal")
    seal.add_argument("--directory", type=Path, required=True)
    seal.add_argument("--source", required=True)
    seal.add_argument("--base", required=True)
    seal.add_argument("--kind", choices=KINDS, required=True)
    seal.add_argument("--consumer", choices=sorted(CONSUMERS), required=True)
    seal.add_argument("--run-id", required=True)
    seal.add_argument("--run-attempt", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--evidence", type=Path, required=True)
    verify.add_argument("--source", required=True)
    verify.add_argument("--base", required=True)
    verify.add_argument("--event", choices=("pull_request", "push", "workflow_dispatch", "schedule"), required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--run-attempt", required=True)
    verify.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "record":
            passed = write_result(
                args.candidate,
                args.consumer,
                args.list_log,
                args.tests_log,
                args.list_exit,
                args.test_exit,
                args.output,
            )
        elif args.command == "seal":
            passed = seal_artifact(
                args.directory,
                args.source,
                args.base,
                args.kind,
                args.consumer,
                args.run_id,
                args.run_attempt,
            )
        else:
            report = verify_matrix(
                args.evidence,
                args.source,
                args.base,
                args.event,
                args.run_id,
                args.run_attempt,
            )
            write_json(args.output, report)
            passed = True
        return 0 if passed else 1
    except (EvidenceError, OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.exit(1, f"entrypoint evidence unavailable: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
