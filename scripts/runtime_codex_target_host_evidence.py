#!/usr/bin/env python3
"""Build and verify fail-closed runtime.codex target-host evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FAULT_SCENARIOS = (
    "provider-ack-loss",
    "event-lag",
    "process-death",
    "agentd-restart",
)
FAULT_OUTCOMES = {
    "provider-ack-loss": {"reconciled_terminal", "indeterminate", "quarantined"},
    "event-lag": {"quarantined"},
    "process-death": {"reconciled_terminal", "indeterminate", "quarantined"},
    "agentd-restart": {"reconciled_terminal", "indeterminate", "quarantined"},
}
EVIDENCE_SCHEMAS = {
    "host-identity.json": "hepta.runtime-codex-host-identity.v1",
    "issuer-custody.json": "hepta.runtime-codex-issuer-custody.v1",
    "anti-rollback.json": "hepta.runtime-codex-anti-rollback.v1",
}


class EvidenceError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid JSON evidence {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON evidence must be an object: {path}")
    return value


def parse_elapsed(value: str) -> float:
    """Parse GNU time's s, m:ss, or h:mm:ss wall-clock value."""
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise EvidenceError(f"unsupported elapsed-time value: {value!r}")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as error:
        raise EvidenceError(f"invalid elapsed-time value: {value!r}") from error
    if any(number < 0 for number in numbers):
        raise EvidenceError(f"negative elapsed-time value: {value!r}")
    if len(numbers) >= 2 and numbers[-1] >= 60:
        raise EvidenceError(f"elapsed seconds must be below 60: {value!r}")
    if len(numbers) == 3 and numbers[-2] >= 60:
        raise EvidenceError(f"elapsed minutes must be below 60: {value!r}")
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise EvidenceError("cannot compute percentile of an empty sample")
    if not 0 <= quantile <= 1:
        raise EvidenceError("quantile must be between zero and one")
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return float(
        ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    )


def require_sha(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise EvidenceError(f"{field} must be an exact lowercase hexadecimal digest")
    return value


def require_external_evidence(
    path: Path, schema: str, source_sha: str
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != schema or value.get("schemaVersion") != 1:
        raise EvidenceError(f"unsupported external evidence schema: {path}")
    if value.get("sourceSha") != source_sha:
        raise EvidenceError(f"external evidence is bound to another source: {path}")
    if value.get("verified") is not True:
        raise EvidenceError(f"external evidence is not independently verified: {path}")
    require_sha(value.get("subjectSha256"), f"{path.name}.subjectSha256", HEX64)
    if not isinstance(value.get("issuedAt"), str) or not value["issuedAt"].strip():
        raise EvidenceError(f"external evidence omitted issuedAt: {path}")
    return value


def parse_time_file(path: Path) -> tuple[float, int]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if ": " in line:
            key, value = line.strip().split(": ", 1)
            fields[key] = value
    elapsed_key = "Elapsed (wall clock) time (h:mm:ss or m:ss)"
    if elapsed_key not in fields:
        raise EvidenceError(f"GNU time evidence omitted elapsed time: {path}")
    try:
        rss = int(fields["Maximum resident set size (kbytes)"])
    except (KeyError, ValueError) as error:
        raise EvidenceError(f"GNU time evidence omitted maximum RSS: {path}") from error
    if rss <= 0:
        raise EvidenceError(f"maximum RSS must be positive: {path}")
    return parse_elapsed(fields[elapsed_key]), rss


def validate_run(path: Path, source_sha: str) -> dict[str, Any]:
    value = load_json(path)
    if value.get("source_sha") not in (None, source_sha):
        raise EvidenceError(f"target-host run is bound to another source: {path}")
    if value.get("terminal_observed") is not True:
        raise EvidenceError(f"target-host run omitted terminal observation: {path}")
    correlation = value.get("codex_terminal_correlation_digest")
    require_sha(correlation, f"{path.name}.correlation", HEX64)
    if value.get("boundary_status") not in ("Succeeded", "succeeded"):
        raise EvidenceError(f"target-host run did not succeed: {path}")
    return value


def validate_provider_audit(
    path: Path, source_sha: str, expected_requests: int
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.runtime-codex-provider-audit.v1":
        raise EvidenceError("provider audit has an unsupported schema")
    if value.get("sourceSha") != source_sha:
        raise EvidenceError("provider audit is bound to another source")
    if value.get("physicalRequestCount") != expected_requests:
        raise EvidenceError("provider audit did not prove exactly one send per canary")
    if value.get("duplicateRequestCount") != 0:
        raise EvidenceError("provider audit observed duplicate requests")
    request_ids = value.get("requestIds")
    if (
        not isinstance(request_ids, list)
        or len(request_ids) != expected_requests
        or len(set(request_ids)) != expected_requests
        or not all(isinstance(item, str) and item for item in request_ids)
    ):
        raise EvidenceError("provider audit request identities are incomplete or duplicated")
    require_sha(value.get("auditSha256"), "provider audit digest", HEX64)
    return value


def validate_fault(
    path: Path, scenario: str, source_sha: str
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.runtime-codex-fault-evidence.v1":
        raise EvidenceError(f"unsupported fault evidence schema: {path}")
    if value.get("schemaVersion") != 1 or value.get("scenario") != scenario:
        raise EvidenceError(f"fault evidence scenario mismatch: {path}")
    if value.get("sourceSha") != source_sha or value.get("verified") is not True:
        raise EvidenceError(f"fault evidence is unverified or source-mismatched: {path}")
    if value.get("physicalRequestCount") != 1:
        raise EvidenceError(f"fault scenario did not preserve one physical send: {path}")
    if value.get("duplicateRequestCount") != 0 or value.get("replayedRequestCount") != 0:
        raise EvidenceError(f"fault scenario observed a duplicate or replay: {path}")
    if value.get("durableOutcome") not in FAULT_OUTCOMES[scenario]:
        raise EvidenceError(f"fault scenario has an invalid durable outcome: {path}")
    if not isinstance(value.get("operationId"), str) or not value["operationId"]:
        raise EvidenceError(f"fault scenario omitted operation identity: {path}")
    require_sha(value.get("journalSha256"), f"{scenario}.journalSha256", HEX64)
    if scenario == "agentd-restart" and value.get("restartObserved") is not True:
        raise EvidenceError("Agentd restart evidence did not observe a restart")
    return value


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    source_sha = require_sha(args.source_sha, "source SHA", HEX40)
    source_tree = require_sha(args.source_tree, "source tree", HEX40)
    if args.iterations < 3 or args.iterations > 20:
        raise EvidenceError("iterations must be in 3..=20")
    if args.generation <= 0:
        raise EvidenceError("Agent generation must be positive")

    root = args.evidence_root
    run_dir = root / "runs"
    elapsed: list[float] = []
    rss: list[float] = []
    runs: list[dict[str, Any]] = []
    for index in range(1, args.iterations + 1):
        output = run_dir / f"{index}.json"
        log = run_dir / f"{index}.log"
        resource = run_dir / f"{index}.time"
        for path in (output, log, resource):
            if not path.is_file():
                raise EvidenceError(f"missing target-host run evidence: {path}")
        validate_run(output, source_sha)
        seconds, maximum_rss = parse_time_file(resource)
        elapsed.append(seconds)
        rss.append(float(maximum_rss))
        runs.append(
            {
                "index": index,
                "outputSha256": digest(output),
                "logSha256": digest(log),
                "resourceSha256": digest(resource),
                "elapsedSeconds": seconds,
                "maximumResidentSetKiB": maximum_rss,
            }
        )

    provider_audit_path = root / "provider-audit.json"
    validate_provider_audit(provider_audit_path, source_sha, args.iterations)

    external: dict[str, dict[str, Any]] = {}
    for name, schema in EVIDENCE_SCHEMAS.items():
        path = root / name
        if not path.is_file():
            raise EvidenceError(f"missing independent evidence: {path}")
        require_external_evidence(path, schema, source_sha)
        external[name] = {"sha256": digest(path), "schema": schema}

    faults: dict[str, dict[str, Any]] = {}
    for scenario in FAULT_SCENARIOS:
        path = root / "faults" / f"{scenario}.json"
        if not path.is_file():
            raise EvidenceError(f"missing fault evidence: {path}")
        value = validate_fault(path, scenario, source_sha)
        faults[scenario] = {
            "sha256": digest(path),
            "durableOutcome": value["durableOutcome"],
            "operationId": value["operationId"],
        }

    return {
        "schema": "hepta.runtime-codex-target-host-qualification.v2",
        "schemaVersion": 2,
        "module": "runtime.codex",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "host": {
            "node": platform.node(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "agentId": args.agent_id,
        "agentGeneration": args.generation,
        "model": args.model,
        "iterations": args.iterations,
        "runs": runs,
        "latencySeconds": {
            "p50": percentile(elapsed, 0.50),
            "p95": percentile(elapsed, 0.95),
            "p99": percentile(elapsed, 0.99),
            "maximum": max(elapsed),
        },
        "maximumResidentSetKiB": {
            "p50": percentile(rss, 0.50),
            "p95": percentile(rss, 0.95),
            "p99": percentile(rss, 0.99),
            "maximum": max(rss),
        },
        "providerAuditSha256": digest(provider_audit_path),
        "independentEvidence": external,
        "faultEvidence": faults,
        "claimBoundary": {
            "realProviderCanariesExecuted": True,
            "faultMatrixExecuted": True,
            "targetHostEvidenceCollected": True,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
    }


def write_manifest(args: argparse.Namespace) -> None:
    manifest = build_manifest(args)
    encoded = canonical_bytes(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    sidecar = args.output.with_suffix(args.output.suffix + ".sha256")
    sidecar.write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  {args.output.name}\n",
        encoding="utf-8",
    )


def verify_manifest(path: Path) -> None:
    raw = path.read_bytes()
    value = json.loads(raw)
    if raw != canonical_bytes(value):
        raise EvidenceError("manifest is not canonical JSON")
    if value.get("schema") != "hepta.runtime-codex-target-host-qualification.v2":
        raise EvidenceError("unsupported manifest schema")
    if value.get("module") != "runtime.codex":
        raise EvidenceError("manifest belongs to another module")
    require_sha(value.get("sourceSha"), "manifest source SHA", HEX40)
    require_sha(value.get("sourceTree"), "manifest source tree", HEX40)
    claims = value.get("claimBoundary")
    if not isinstance(claims, dict):
        raise EvidenceError("manifest omitted claim boundary")
    for field in ("independentAcceptance", "activation", "promotion", "release"):
        if claims.get(field) is not False:
            raise EvidenceError(f"manifest illegally claims {field}")
    sidecar = path.with_suffix(path.suffix + ".sha256")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(raw).hexdigest()
    if expected != actual:
        raise EvidenceError("manifest digest sidecar mismatch")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--evidence-root", type=Path, required=True)
    build.add_argument("--source-sha", required=True)
    build.add_argument("--source-tree", required=True)
    build.add_argument("--agent-id", required=True)
    build.add_argument("--generation", type=int, required=True)
    build.add_argument("--model", required=True)
    build.add_argument("--iterations", type=int, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "build":
        write_manifest(args)
    else:
        verify_manifest(args.manifest)


if __name__ == "__main__":
    main()
