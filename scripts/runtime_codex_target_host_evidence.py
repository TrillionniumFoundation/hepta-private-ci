#!/usr/bin/env python3
"""Build and verify fail-closed runtime.codex target-host evidence.

This verifier consumes independently produced host, issuer, provider, fault,
rollback and review evidence. It never performs those qualifications itself and
never grants activation, promotion or release.
"""
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

MANIFEST_SCHEMA = "hepta.runtime-codex-target-host-qualification.v3"
MANIFEST_SCHEMA_VERSION = 3
FAULT_SCHEMA = "hepta.runtime-codex-fault-evidence.v2"
FAULT_SCHEMA_VERSION = 2
PROVIDER_AUDIT_SCHEMA = "hepta.runtime-codex-provider-audit.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_TEXT_BYTES = 128 * 1024 * 1024
MIN_CANARY_OPERATIONS = 30
MAX_CANARY_OPERATIONS = 200

FAULT_SCENARIOS = (
    "provider-ack-loss",
    "event-lag",
    "worker-kill-after-fence",
    "worker-restart",
    "agentd-restart",
    "revocation-advance-before-entry",
    "duplicate-owner",
    "stale-revision",
)
FAULT_OUTCOMES = {
    "provider-ack-loss": {"reconciled_terminal", "indeterminate", "quarantined"},
    "event-lag": {"quarantined"},
    "worker-kill-after-fence": {
        "reconciled_terminal",
        "indeterminate",
        "quarantined",
    },
    "worker-restart": {"reconciled_terminal", "indeterminate", "quarantined"},
    "agentd-restart": {"reconciled_terminal", "indeterminate", "quarantined"},
    "revocation-advance-before-entry": {"rejected_before_send"},
    "duplicate-owner": {"single_winner"},
    "stale-revision": {"rejected_before_send"},
}
ZERO_SEND_SCENARIOS = {
    "revocation-advance-before-entry",
    "stale-revision",
}
SCENARIO_FLAGS = {
    "provider-ack-loss": "providerAckLossObserved",
    "event-lag": "eventLagObserved",
    "worker-kill-after-fence": "workerKilledAfterFenceObserved",
    "worker-restart": "workerRestartObserved",
    "agentd-restart": "agentdRestartObserved",
    "revocation-advance-before-entry": "revocationAdvanceObserved",
    "duplicate-owner": "duplicateOwnerObserved",
    "stale-revision": "staleRevisionRejected",
}
EVIDENCE_SCHEMAS = {
    "host-identity.json": "hepta.runtime-codex-host-identity.v1",
    "issuer-custody.json": "hepta.runtime-codex-issuer-custody.v1",
    "anti-rollback.json": "hepta.runtime-codex-anti-rollback.v1",
    "canary-rollback.json": "hepta.runtime-codex-canary-rollback.v1",
    "independent-acceptance.json": "hepta.runtime-codex-independent-acceptance.v1",
}


class EvidenceError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise EvidenceError(f"unsafe or missing JSON evidence: {path}")
        if path.stat().st_size > MAX_JSON_BYTES:
            raise EvidenceError(f"oversized JSON evidence: {path}")
        value = json.loads(
            path.read_text(encoding="utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                EvidenceError(f"non-finite JSON value: {token}")
            ),
        )
    except EvidenceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid JSON evidence {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON evidence must be an object: {path}")
    return value


def require_int(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        suffix = f"..={maximum}" if maximum is not None else " or greater"
        raise EvidenceError(f"{field} must be an integer in {minimum}{suffix}")
    return value


def require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise EvidenceError(f"{field} must be a boolean")
    return value


def require_number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if type(value) not in (int, float):
        raise EvidenceError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise EvidenceError(f"{field} must be a finite number >= {minimum}")
    return number


def require_text(value: Any, field: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value.encode("utf-8", errors="strict").find(b"\x00") >= 0
    ):
        raise EvidenceError(f"{field} must be non-empty bounded text")
    return value


def require_sha(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value) or set(value) == {"0"}:
        raise EvidenceError(f"{field} must be an exact nonzero lowercase hexadecimal digest")
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
    if any(not math.isfinite(number) or number < 0 for number in numbers):
        raise EvidenceError(f"invalid elapsed-time value: {value!r}")
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
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise EvidenceError("percentile sample contains an invalid value")
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return float(
        ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    )


def require_external_evidence(path: Path, schema: str, source_sha: str) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != schema or value.get("schemaVersion") != 1:
        raise EvidenceError(f"unsupported external evidence schema: {path}")
    if value.get("sourceSha") != source_sha:
        raise EvidenceError(f"external evidence is bound to another source: {path}")
    if value.get("verified") is not True:
        raise EvidenceError(f"external evidence is not independently verified: {path}")
    require_sha(value.get("subjectSha256"), f"{path.name}.subjectSha256", HEX64)
    require_text(value.get("issuedAt"), f"{path.name}.issuedAt", maximum=128)
    require_text(value.get("issuerId"), f"{path.name}.issuerId", maximum=128)
    return value


def parse_time_file(path: Path) -> tuple[float, int]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_TEXT_BYTES:
        raise EvidenceError(f"unsafe or oversized GNU time evidence: {path}")
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if ": " in line:
            key, value = line.strip().split(": ", 1)
            if key in fields:
                raise EvidenceError(f"duplicate GNU time field {key!r}: {path}")
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
    require_sha(
        value.get("codex_terminal_correlation_digest"),
        f"{path.name}.correlation",
        HEX64,
    )
    if value.get("boundary_status") not in ("Succeeded", "succeeded"):
        raise EvidenceError(f"target-host run did not succeed: {path}")
    return value


def validate_provider_audit(path: Path, source_sha: str, expected_requests: int) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != PROVIDER_AUDIT_SCHEMA or value.get("schemaVersion", 1) != 1:
        raise EvidenceError("provider audit has an unsupported schema")
    if value.get("sourceSha") != source_sha:
        raise EvidenceError("provider audit is bound to another source")
    if require_int(value.get("physicalRequestCount"), "provider physicalRequestCount") != expected_requests:
        raise EvidenceError("provider audit did not prove exactly one send per canary")
    if require_int(value.get("duplicateRequestCount"), "provider duplicateRequestCount") != 0:
        raise EvidenceError("provider audit observed duplicate requests")
    if require_int(value.get("replayedRequestCount", 0), "provider replayedRequestCount") != 0:
        raise EvidenceError("provider audit observed replayed requests")
    request_ids = value.get("requestIds")
    if (
        not isinstance(request_ids, list)
        or len(request_ids) != expected_requests
        or len(set(request_ids)) != expected_requests
        or not all(isinstance(item, str) and 0 < len(item) <= 256 for item in request_ids)
    ):
        raise EvidenceError("provider audit request identities are incomplete or duplicated")
    require_sha(value.get("auditSha256"), "provider audit digest", HEX64)
    return value


def validate_binary_identity(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise EvidenceError("unsafe binary digest sidecar")
    parts = path.read_text(encoding="utf-8", errors="strict").strip().split()
    if len(parts) < 1:
        raise EvidenceError("binary digest sidecar is empty")
    return require_sha(parts[0], "binary SHA-256", HEX64)


def validate_source_receipt(path: Path, source_sha: str, lane: str) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.runtime-codex-source-qualification.v2":
        raise EvidenceError(f"unsupported source receipt schema: {path}")
    if value.get("module") != "runtime.codex" or value.get("status") != "passed":
        raise EvidenceError(f"source qualification did not pass: {path}")
    candidate = value.get("candidate")
    if (
        not isinstance(candidate, dict)
        or candidate.get("source") != source_sha
        or candidate.get("lane") != lane
    ):
        raise EvidenceError(f"source receipt is bound to another candidate/lane: {path}")
    claims = value.get("claims")
    if not isinstance(claims, dict) or claims.get("sourceQualification") is not True:
        raise EvidenceError(f"source receipt omitted source qualification: {path}")
    for field in ("targetHostIdentityQualified", "realProviderQualified",
                  "allCrashBoundariesQualified", "independentAcceptance",
                  "activation", "promotion", "release"):
        if claims.get(field) is not False:
            raise EvidenceError(f"source receipt illegally claims {field}: {path}")
    return value


def validate_source_qualification(root: Path, source_sha: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for lane in ("source-head", "base-merge"):
        receipt = root / f"{lane}-receipt.json"
        bundle = root / f"{lane}-attestation.jsonl"
        validate_source_receipt(receipt, source_sha, lane)
        if bundle.is_symlink() or not bundle.is_file() or not bundle.stat().st_size:
            raise EvidenceError(f"missing verified source attestation bundle: {bundle}")
        result[lane] = {
            "receiptSha256": digest(receipt),
            "attestationBundleSha256": digest(bundle),
        }
    return result


def validate_fault(path: Path, scenario: str, source_sha: str) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != FAULT_SCHEMA or value.get("schemaVersion") != FAULT_SCHEMA_VERSION:
        raise EvidenceError(f"unsupported fault evidence schema: {path}")
    if value.get("scenario") != scenario:
        raise EvidenceError(f"fault evidence scenario mismatch: {path}")
    if value.get("sourceSha") != source_sha or value.get("verified") is not True:
        raise EvidenceError(f"fault evidence is unverified or source-mismatched: {path}")
    require_text(value.get("operationId"), f"{scenario}.operationId", maximum=256)
    physical = require_int(value.get("physicalRequestCount"), f"{scenario}.physicalRequestCount", maximum=1)
    fresh = require_int(value.get("freshFenceAckCount"), f"{scenario}.freshFenceAckCount", maximum=1)
    if require_int(value.get("duplicateRequestCount"), f"{scenario}.duplicateRequestCount") != 0:
        raise EvidenceError(f"fault scenario observed a duplicate request: {path}")
    if require_int(value.get("replayedRequestCount"), f"{scenario}.replayedRequestCount") != 0:
        raise EvidenceError(f"fault scenario observed a replay: {path}")
    if require_bool(value.get("abortAfterFenceAccepted"), f"{scenario}.abortAfterFenceAccepted"):
        raise EvidenceError(f"fault scenario accepted a post-fence abort: {path}")
    if not require_bool(value.get("ownerRevisionMonotonic"), f"{scenario}.ownerRevisionMonotonic"):
        raise EvidenceError(f"fault scenario observed owner revision rollback: {path}")
    capacity_retained = require_bool(
        value.get("unresolvedCapacityRetained"),
        f"{scenario}.unresolvedCapacityRetained",
    )
    outcome = value.get("durableOutcome")
    if outcome not in FAULT_OUTCOMES[scenario]:
        raise EvidenceError(f"fault scenario has an invalid durable outcome: {path}")
    for field in ("journalSha256", "providerAuditSha256", "harnessSha256"):
        require_sha(value.get(field), f"{scenario}.{field}", HEX64)
    flag = SCENARIO_FLAGS[scenario]
    if value.get(flag) is not True:
        raise EvidenceError(f"fault scenario omitted required observation {flag}: {path}")

    if scenario in ZERO_SEND_SCENARIOS:
        if physical != 0 or fresh != 0:
            raise EvidenceError(f"pre-entry rejection scenario crossed the effect boundary: {path}")
        if capacity_retained:
            raise EvidenceError(f"definitely-unsent rejection retained execution capacity: {path}")
    elif scenario == "duplicate-owner":
        if physical != 1 or fresh != 1:
            raise EvidenceError("duplicate-owner scenario did not prove exactly one winner/send")
    elif scenario in ("provider-ack-loss", "event-lag"):
        if physical != 1 or fresh != 1 or not capacity_retained:
            raise EvidenceError(f"post-send fault scenario lost its exact ownership: {path}")
    else:
        if physical == 1 and fresh != 1:
            raise EvidenceError(f"physical send lacked a fresh effect-entry ACK: {path}")
        if outcome in {"indeterminate", "quarantined"} and not capacity_retained:
            raise EvidenceError(f"unresolved fault released capacity: {path}")

    return value


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    source_sha = require_sha(args.source_sha, "source SHA", HEX40)
    source_tree = require_sha(args.source_tree, "source tree", HEX40)
    require_int(
        args.iterations,
        "iterations",
        minimum=MIN_CANARY_OPERATIONS,
        maximum=MAX_CANARY_OPERATIONS,
    )
    require_int(args.generation, "Agent generation", minimum=1)
    require_text(args.agent_id, "Agent id", maximum=256)
    require_text(args.model, "model", maximum=256)

    root = args.evidence_root
    run_dir = root / "runs"
    elapsed: list[float] = []
    rss: list[float] = []
    correlations: set[str] = set()
    runs: list[dict[str, Any]] = []
    for index in range(1, args.iterations + 1):
        output = run_dir / f"{index}.json"
        log = run_dir / f"{index}.log"
        resource = run_dir / f"{index}.time"
        for path in (output, log, resource):
            if path.is_symlink() or not path.is_file():
                raise EvidenceError(f"missing or unsafe target-host run evidence: {path}")
            if path.stat().st_size > MAX_TEXT_BYTES:
                raise EvidenceError(f"oversized target-host run evidence: {path}")
        observed = validate_run(output, source_sha)
        correlation = observed["codex_terminal_correlation_digest"]
        if correlation in correlations:
            raise EvidenceError("canary terminal correlation digest was reused")
        correlations.add(correlation)
        seconds, maximum_rss = parse_time_file(resource)
        elapsed.append(seconds)
        rss.append(float(maximum_rss))
        runs.append(
            {
                "index": index,
                "outputSha256": digest(output),
                "logSha256": digest(log),
                "resourceSha256": digest(resource),
                "terminalCorrelationSha256": correlation,
                "elapsedSeconds": seconds,
                "maximumResidentSetKiB": maximum_rss,
            }
        )

    provider_audit_path = root / "provider-audit.json"
    validate_provider_audit(provider_audit_path, source_sha, args.iterations)
    binary_sha256 = validate_binary_identity(root / "binary.sha256")
    source_qualification = validate_source_qualification(
        root / "source-qualification", source_sha
    )

    external: dict[str, dict[str, Any]] = {}
    for name, schema in EVIDENCE_SCHEMAS.items():
        path = root / name
        if not path.is_file():
            raise EvidenceError(f"missing independent evidence: {path}")
        value = require_external_evidence(path, schema, source_sha)
        external[name] = {
            "sha256": digest(path),
            "schema": schema,
            "issuerId": value["issuerId"],
            "subjectSha256": value["subjectSha256"],
        }

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
            "physicalRequestCount": value["physicalRequestCount"],
            "freshFenceAckCount": value["freshFenceAckCount"],
            "unresolvedCapacityRetained": value["unresolvedCapacityRetained"],
            "journalSha256": value["journalSha256"],
            "providerAuditSha256": value["providerAuditSha256"],
            "harnessSha256": value["harnessSha256"],
        }

    return {
        "schema": MANIFEST_SCHEMA,
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "module": "runtime.codex",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "binarySha256": binary_sha256,
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
        "repositorySourceQualification": source_qualification,
        "independentEvidence": external,
        "faultEvidence": faults,
        "claimBoundary": {
            "repositorySourceQualificationVerified": True,
            "realProviderCanariesExecuted": True,
            "faultMatrixExecuted": True,
            "targetHostEvidenceCollected": True,
            "independentAcceptanceReviewCollected": True,
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
    value = load_json(path)
    if raw != canonical_bytes(value):
        raise EvidenceError("manifest is not canonical JSON")
    if value.get("schema") != MANIFEST_SCHEMA or value.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        raise EvidenceError("unsupported manifest schema")
    if value.get("module") != "runtime.codex":
        raise EvidenceError("manifest belongs to another module")
    require_sha(value.get("sourceSha"), "manifest source SHA", HEX40)
    require_sha(value.get("sourceTree"), "manifest source tree", HEX40)
    require_sha(value.get("binarySha256"), "manifest binary SHA-256", HEX64)
    iterations = require_int(
        value.get("iterations"),
        "manifest iterations",
        minimum=MIN_CANARY_OPERATIONS,
        maximum=MAX_CANARY_OPERATIONS,
    )
    require_int(value.get("agentGeneration"), "manifest Agent generation", minimum=1)
    require_text(value.get("agentId"), "manifest Agent id", maximum=256)
    require_text(value.get("model"), "manifest model", maximum=256)
    require_text(value.get("generatedAt"), "manifest generatedAt", maximum=128)
    host = value.get("host")
    if not isinstance(host, dict):
        raise EvidenceError("manifest omitted host identity summary")
    for field in ("node", "platform", "machine"):
        require_text(host.get(field), f"manifest host.{field}", maximum=1024)

    runs = value.get("runs")
    if not isinstance(runs, list) or len(runs) != iterations:
        raise EvidenceError("manifest run inventory does not match iterations")
    correlations: set[str] = set()
    for expected_index, run in enumerate(runs, start=1):
        if not isinstance(run, dict) or run.get("index") != expected_index:
            raise EvidenceError("manifest run indices are not exact and ordered")
        for field in ("outputSha256", "logSha256", "resourceSha256",
                      "terminalCorrelationSha256"):
            require_sha(run.get(field), f"manifest run {expected_index}.{field}", HEX64)
        correlation = run["terminalCorrelationSha256"]
        if correlation in correlations:
            raise EvidenceError("manifest terminal correlation was reused")
        correlations.add(correlation)
        require_number(run.get("elapsedSeconds"), f"run {expected_index}.elapsedSeconds")
        require_int(run.get("maximumResidentSetKiB"),
                    f"run {expected_index}.maximumResidentSetKiB", minimum=1)

    for section in ("latencySeconds", "maximumResidentSetKiB"):
        metrics = value.get(section)
        if not isinstance(metrics, dict) or set(metrics) != {"p50", "p95", "p99", "maximum"}:
            raise EvidenceError(f"manifest {section} metrics are incomplete")
        ordered = [require_number(metrics.get(field), f"{section}.{field}")
                   for field in ("p50", "p95", "p99", "maximum")]
        if ordered != sorted(ordered):
            raise EvidenceError(f"manifest {section} percentiles are not monotonic")
    require_sha(value.get("providerAuditSha256"), "manifest provider audit digest", HEX64)

    faults = value.get("faultEvidence")
    if not isinstance(faults, dict) or set(faults) != set(FAULT_SCENARIOS):
        raise EvidenceError("manifest fault inventory is incomplete or open world")
    for scenario, evidence in faults.items():
        if not isinstance(evidence, dict):
            raise EvidenceError(f"manifest fault summary is malformed: {scenario}")
        require_sha(evidence.get("sha256"), f"{scenario}.sha256", HEX64)
        require_text(evidence.get("operationId"), f"{scenario}.operationId", maximum=256)
        if evidence.get("durableOutcome") not in FAULT_OUTCOMES[scenario]:
            raise EvidenceError(f"manifest fault outcome is invalid: {scenario}")
        require_int(evidence.get("physicalRequestCount"),
                    f"{scenario}.physicalRequestCount", maximum=1)
        require_int(evidence.get("freshFenceAckCount"),
                    f"{scenario}.freshFenceAckCount", maximum=1)
        require_bool(evidence.get("unresolvedCapacityRetained"),
                     f"{scenario}.unresolvedCapacityRetained")
        for field in ("journalSha256", "providerAuditSha256", "harnessSha256"):
            require_sha(evidence.get(field), f"{scenario}.{field}", HEX64)

    source_qualification = value.get("repositorySourceQualification")
    if (
        not isinstance(source_qualification, dict)
        or set(source_qualification) != {"source-head", "base-merge"}
    ):
        raise EvidenceError("manifest source qualification inventory is incomplete")
    for lane, evidence in source_qualification.items():
        if not isinstance(evidence, dict):
            raise EvidenceError(f"manifest source evidence is malformed: {lane}")
        require_sha(evidence.get("receiptSha256"), f"{lane} receipt digest", HEX64)
        require_sha(
            evidence.get("attestationBundleSha256"),
            f"{lane} attestation digest",
            HEX64,
        )

    external = value.get("independentEvidence")
    if not isinstance(external, dict) or set(external) != set(EVIDENCE_SCHEMAS):
        raise EvidenceError("manifest independent evidence inventory is incomplete")
    for name, evidence in external.items():
        if not isinstance(evidence, dict) or evidence.get("schema") != EVIDENCE_SCHEMAS[name]:
            raise EvidenceError(f"manifest independent evidence is malformed: {name}")
        require_sha(evidence.get("sha256"), f"{name}.sha256", HEX64)
        require_sha(evidence.get("subjectSha256"), f"{name}.subjectSha256", HEX64)
        require_text(evidence.get("issuerId"), f"{name}.issuerId", maximum=128)

    claims = value.get("claimBoundary")
    if not isinstance(claims, dict):
        raise EvidenceError("manifest omitted claim boundary")
    for field in ("independentAcceptance", "activation", "promotion", "release"):
        if claims.get(field) is not False:
            raise EvidenceError(f"manifest illegally claims {field}")
    for field in (
        "repositorySourceQualificationVerified",
        "realProviderCanariesExecuted",
        "faultMatrixExecuted",
        "targetHostEvidenceCollected",
        "independentAcceptanceReviewCollected",
    ):
        if claims.get(field) is not True:
            raise EvidenceError(f"manifest omitted required evidence claim {field}")

    sidecar = path.with_suffix(path.suffix + ".sha256")
    if sidecar.is_symlink() or not sidecar.is_file():
        raise EvidenceError("manifest digest sidecar is missing or unsafe")
    fields = sidecar.read_text(encoding="utf-8", errors="strict").split()
    if len(fields) < 1:
        raise EvidenceError("manifest digest sidecar is empty")
    expected = require_sha(fields[0], "manifest sidecar digest", HEX64)
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


def main() -> int:
    args = parser().parse_args()
    if args.command == "build":
        write_manifest(args)
        verify_manifest(args.output)
        print(json.dumps({"status": "passed", "sha256": digest(args.output)}))
    else:
        verify_manifest(args.manifest)
        print(json.dumps({"status": "passed", "sha256": digest(args.manifest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
