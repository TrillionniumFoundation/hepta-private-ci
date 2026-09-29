#!/usr/bin/env python3
"""Build tamper-evident inference.worker command and aggregate receipts.

The receipts bind repository-local qualification evidence only. They never
upgrade real-hardware, deployed-provider, activation, acceptance, promotion, or
release gates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
from collections.abc import Iterable, Sequence
from typing import Any

COMMAND_SCHEMA = "hepta.inference-worker-command-receipt.v1"
AGGREGATE_SCHEMA = "hepta.inference-worker-qualification-aggregate.v1"
_ALLOWED_LANES = {"source-head", "base-merge"}
_ALLOWED_PACKAGES = {
    "codex-hepta-infer-core",
    "codex-hepta-infer-worker-host",
    "codex-hepta-agentd",
}
_OID = re.compile(r"^[0-9a-f]{40}$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def _oid(value: str, field: str) -> str:
    value = value.strip().lower()
    if not _OID.fullmatch(value):
        raise ValueError(f"{field} must be a 40-character lowercase Git object id")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_digest(value: dict[str, Any]) -> str:
    body = dict(value)
    body.pop("receipt_sha256", None)
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _sha256(encoded)


def _safe_text(value: str, field: str, maximum: int = 512) -> str:
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {field}")
    return value


def observed_skipped_tests(text: str) -> int:
    """Parse skip/ignore counts without treating filter exclusions as skips."""
    text = _ANSI.sub("", text)
    nextest = re.findall(r"Summary[^\n]*?\d+ tests? run: ([^\n]+)", text)
    if nextest:
        return sum(int(value) for value in re.findall(r"(\d+) skipped", nextest[-1]))
    skipped = 0
    for match in re.finditer(
        r"test result: (?:ok|FAILED)\. \d+ passed; \d+ failed; (\d+) ignored;",
        text,
    ):
        skipped += int(match[1])
    for match in re.finditer(
        r"Ran \d+ tests? in [^\n]+\n\s*\n?(?:OK|FAILED)(?: \(([^\n]*)\))?",
        text,
    ):
        fields = dict(
            (key.strip(), int(value))
            for key, value in re.findall(r"([a-z ]+)=(\d+)", match[1] or "")
        )
        skipped += fields.get("skipped", 0)
    return skipped


def _load_record(
    *,
    record_path: pathlib.Path,
    label: str,
    source_sha: str,
    base_sha: str,
    tested_sha: str,
    lane: str,
) -> dict[str, Any]:
    raw = record_path.read_bytes()
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise ValueError(f"{label}: command record must be an object")
    expected = {
        "source_sha": source_sha,
        "base_sha": base_sha,
        "tested_sha": tested_sha,
        "lane": lane,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise ValueError(f"{label}: {field} mismatch")
    before = record.get("before")
    after = record.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError(f"{label}: missing before/after identity")
    if before != after:
        raise ValueError(f"{label}: source identity changed during command")
    if before.get("commit") != tested_sha or not _OID.fullmatch(
        str(before.get("tree", ""))
    ):
        raise ValueError(f"{label}: tested identity mismatch")
    command = record.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item for item in command
    ):
        raise ValueError(f"{label}: missing exact command argv")
    log_name = record.get("log_file")
    skipped = 0
    log_sha256 = None
    if log_name is not None:
        if not isinstance(log_name, str) or pathlib.Path(log_name).name != log_name:
            raise ValueError(f"{label}: invalid log file")
        log_path = record_path.with_name(log_name)
        if not log_path.is_file():
            raise ValueError(f"{label}: command log is missing")
        log = log_path.read_bytes()
        log_sha256 = _sha256(log)
        if record.get("log_sha256") != log_sha256:
            raise ValueError(f"{label}: command log digest mismatch")
        skipped = observed_skipped_tests(log.decode("utf-8", errors="replace"))
    return {
        "label": label,
        "record_file": record_path.name,
        "record_sha256": _sha256(raw),
        "command": command,
        "working_directory": record.get("working_directory"),
        "status": record.get("status"),
        "exit_code": record.get("exit_code"),
        "command_exit_code": record.get("command_exit_code"),
        "minimum_tests": record.get("minimum_tests", 0),
        "observed_passed_tests": record.get("observed_passed_tests", 0),
        "observed_failed_tests": record.get("observed_failed_tests", 0),
        "observed_skipped_tests": skipped,
        "log_sha256": log_sha256,
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
    }


def emit_receipt(
    *,
    repo: pathlib.Path,
    source_sha: str,
    base_sha: str,
    tested_sha: str,
    lane: str,
    package: str,
    runner_os: str,
    runner_arch: str,
    runner_name: str,
    runner_environment: str,
    records: Sequence[tuple[str, pathlib.Path]],
    expected_labels: Sequence[str],
    generated_at: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    source_sha = _oid(source_sha, "source_sha")
    base_sha = _oid(base_sha, "base_sha")
    tested_sha = _oid(tested_sha, "tested_sha")
    if lane not in _ALLOWED_LANES:
        raise ValueError("unsupported lane")
    if package not in _ALLOWED_PACKAGES:
        raise ValueError("unsupported package")
    observed_head = _oid(_git(repo, "rev-parse", "HEAD"), "checked out HEAD")
    if observed_head != tested_sha:
        raise ValueError("checked out HEAD does not match tested_sha")
    source_tree = _oid(_git(repo, "rev-parse", f"{source_sha}^{{tree}}"), "source tree")
    base_tree = _oid(_git(repo, "rev-parse", f"{base_sha}^{{tree}}"), "base tree")
    tested_tree = _oid(_git(repo, "rev-parse", f"{tested_sha}^{{tree}}"), "tested tree")
    if lane == "source-head":
        if tested_sha != source_sha:
            raise ValueError("source-head lane must test source_sha")
    else:
        parents = _git(repo, "show", "-s", "--format=%P", tested_sha).split()
        if parents != [base_sha, source_sha]:
            raise ValueError("base-merge lane must have exact ordered base/source parents")
        expected_tree = _oid(
            _git(repo, "merge-tree", "--write-tree", base_sha, source_sha),
            "recomputed merge tree",
        )
        if tested_tree != expected_tree:
            raise ValueError("base-merge tree differs from recomputed merge")
    cargo_lock_blob = _oid(
        _git(repo, "rev-parse", f"{tested_sha}:codex-rs/Cargo.lock"),
        "Cargo.lock blob",
    )
    labels = [label for label, _ in records]
    if len(labels) != len(set(labels)):
        raise ValueError("duplicate command record label")
    missing = sorted(set(expected_labels) - set(labels))
    unexpected = sorted(set(labels) - set(expected_labels))
    command_records: list[dict[str, Any]] = []
    failures: list[str] = []
    if missing:
        failures.append(f"missing command records: {missing}")
    if unexpected:
        failures.append(f"unexpected command records: {unexpected}")
    for label, path in records:
        try:
            command_records.append(
                _load_record(
                    record_path=path.resolve(),
                    label=label,
                    source_sha=source_sha,
                    base_sha=base_sha,
                    tested_sha=tested_sha,
                    lane=lane,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"{label}: {error}")
    total_passed = sum(
        int(record["observed_passed_tests"]) for record in command_records
    )
    total_failed = sum(
        int(record["observed_failed_tests"]) for record in command_records
    )
    total_skipped = sum(
        int(record["observed_skipped_tests"]) for record in command_records
    )
    for record in command_records:
        if (
            record["status"] != "passed"
            or record["exit_code"] != 0
            or record["command_exit_code"] != 0
            or int(record["observed_failed_tests"]) != 0
        ):
            failures.append(f"{record['label']}: command did not pass")
        if (
            int(record["minimum_tests"]) > 0
            and int(record["observed_passed_tests"])
            < int(record["minimum_tests"])
        ):
            failures.append(f"{record['label']}: minimum test count not met")
    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat()
    receipt: dict[str, Any] = {
        "schema": COMMAND_SCHEMA,
        "schemaVersion": 1,
        "generated_at": timestamp,
        "source_sha": source_sha,
        "source_tree": source_tree,
        "base_sha": base_sha,
        "base_tree": base_tree,
        "tested_sha": tested_sha,
        "tested_tree": tested_tree,
        "cargo_lock_blob": cargo_lock_blob,
        "lane": lane,
        "package": package,
        "runner": {
            "os": _safe_text(runner_os, "runner os", 64),
            "arch": _safe_text(runner_arch, "runner arch", 64),
            "name": _safe_text(runner_name, "runner name", 256),
            "environment": _safe_text(
                runner_environment, "runner environment", 64
            ),
        },
        "command_records": sorted(command_records, key=lambda item: item["label"]),
        "test_counts": {
            "passed": total_passed,
            "failed": total_failed,
            "skipped": total_skipped,
        },
        "result": "success" if not failures else "failed_or_incomplete",
        "failures": failures,
        "claim_boundary": {
            "repository_local_command_evidence": not failures,
            "real_hardware_qualification": False,
            "deployed_provider_qualification": False,
            "independent_acceptance": False,
            "activation": False,
            "release": False,
        },
    }
    receipt["receipt_sha256"] = _canonical_digest(receipt)
    return receipt


def aggregate_receipts(
    *,
    receipts: Iterable[dict[str, Any]],
    source_sha: str,
    base_sha: str,
    expected_lanes: Sequence[str],
    expected_packages: Sequence[str],
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_sha = _oid(source_sha, "source_sha")
    base_sha = _oid(base_sha, "base_sha")
    expected = {
        (lane, package)
        for lane in expected_lanes
        for package in expected_packages
    }
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    failures: list[str] = []
    for receipt in receipts:
        if receipt.get("schema") != COMMAND_SCHEMA:
            failures.append("unexpected receipt schema")
            continue
        if receipt.get("receipt_sha256") != _canonical_digest(receipt):
            failures.append("receipt digest mismatch")
            continue
        if receipt.get("source_sha") != source_sha or receipt.get("base_sha") != base_sha:
            failures.append("receipt source/base mismatch")
            continue
        key = (str(receipt.get("lane")), str(receipt.get("package")))
        if key in seen:
            failures.append(f"duplicate receipt: {key}")
            continue
        seen[key] = receipt
        if receipt.get("result") != "success":
            failures.append(f"receipt did not pass: {key}")
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    if missing:
        failures.append(f"missing receipts: {missing}")
    if extra:
        failures.append(f"unexpected receipts: {extra}")
    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat()
    ordered = [seen[key] for key in sorted(seen)]
    aggregate: dict[str, Any] = {
        "schema": AGGREGATE_SCHEMA,
        "schemaVersion": 1,
        "generated_at": timestamp,
        "source_sha": source_sha,
        "base_sha": base_sha,
        "expected_lanes": list(expected_lanes),
        "expected_packages": list(expected_packages),
        "receipt_digests": {
            f"{receipt['lane']}:{receipt['package']}": receipt["receipt_sha256"]
            for receipt in ordered
        },
        "test_counts": {
            "passed": sum(receipt["test_counts"]["passed"] for receipt in ordered),
            "failed": sum(receipt["test_counts"]["failed"] for receipt in ordered),
            "skipped": sum(receipt["test_counts"]["skipped"] for receipt in ordered),
        },
        "result": "success" if not failures else "failed_or_incomplete",
        "failures": failures,
        "claim_boundary": {
            "repository_local_qualification_complete": not failures,
            "production_implementation": False,
            "product_execution_complete": False,
            "deployment_qualification_complete": False,
            "independent_acceptance_complete": False,
            "activation": False,
            "release": False,
        },
    }
    aggregate["receipt_sha256"] = _canonical_digest(aggregate)
    return aggregate


def _write(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _record_arg(value: str) -> tuple[str, pathlib.Path]:
    label, separator, path = value.partition("=")
    if not separator or not label or not path:
        raise argparse.ArgumentTypeError("--record requires LABEL=PATH")
    return label, pathlib.Path(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    emit = subparsers.add_parser("emit")
    emit.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path("."))
    emit.add_argument("--source-sha", required=True)
    emit.add_argument("--base-sha", required=True)
    emit.add_argument("--tested-sha", required=True)
    emit.add_argument("--lane", required=True)
    emit.add_argument("--package", required=True)
    emit.add_argument("--runner-os", required=True)
    emit.add_argument("--runner-arch", required=True)
    emit.add_argument("--runner-name", required=True)
    emit.add_argument("--runner-environment", required=True)
    emit.add_argument("--record", action="append", type=_record_arg, default=[])
    emit.add_argument("--expected-label", action="append", default=[])
    emit.add_argument("--generated-at")
    emit.add_argument("--output", type=pathlib.Path, required=True)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--receipt-dir", type=pathlib.Path, required=True)
    aggregate.add_argument("--source-sha", required=True)
    aggregate.add_argument("--base-sha", required=True)
    aggregate.add_argument("--expected-lane", action="append", required=True)
    aggregate.add_argument("--expected-package", action="append", required=True)
    aggregate.add_argument("--generated-at")
    aggregate.add_argument("--output", type=pathlib.Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "emit":
        receipt = emit_receipt(
            repo=args.repo_root,
            source_sha=args.source_sha,
            base_sha=args.base_sha,
            tested_sha=args.tested_sha,
            lane=args.lane,
            package=args.package,
            runner_os=args.runner_os,
            runner_arch=args.runner_arch,
            runner_name=args.runner_name,
            runner_environment=args.runner_environment,
            records=args.record,
            expected_labels=args.expected_label,
            generated_at=args.generated_at,
        )
        _write(args.output, receipt)
        return 0 if receipt["result"] == "success" else 1
    values = []
    for path in sorted(args.receipt_dir.rglob("*.json")):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if candidate.get("schema") == COMMAND_SCHEMA:
            values.append(candidate)
    aggregate = aggregate_receipts(
        receipts=values,
        source_sha=args.source_sha,
        base_sha=args.base_sha,
        expected_lanes=args.expected_lane,
        expected_packages=args.expected_package,
        generated_at=args.generated_at,
    )
    _write(args.output, aggregate)
    return 0 if aggregate["result"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
