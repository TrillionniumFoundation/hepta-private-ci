#!/usr/bin/env python3
"""Fail-closed Prometheus sidecar for learning.artifacts owner metrics.

The owner writes its real operational JSON projection through the authenticated
product surface. This sidecar only projects that snapshot and an optional
owning-system quarantine observation; it grants no writer, selection,
activation, promotion or release authority.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

COMMAND_SCHEMA = "hepta.learning-artifactd.metrics.v1"
OPERATIONAL_SCHEMA = "hepta.learning-artifactd.operational-metrics.v1"
QUARANTINE_SCHEMA = "hepta.learning-artifactd.quarantine-observation.v1"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
MAX_SNAPSHOT_BYTES = 1_048_576

COMMAND_COUNTERS = {
    "requestsReceived": "hepta_learning_artifact_owner_requests_received_total",
    "requestsAuthenticated": "hepta_learning_artifact_owner_requests_authenticated_total",
    "authenticationFailures": "hepta_learning_artifact_owner_authentication_failures_total",
    "exactReplays": "hepta_learning_artifact_owner_exact_replays_total",
    "replayConflicts": "hepta_learning_artifact_owner_replay_conflicts_total",
    "publicationsSucceeded": "hepta_learning_artifact_owner_publications_succeeded_total",
    "publicationsFailed": "hepta_learning_artifact_owner_publications_failed_total",
    "recoveryPublicationsSucceeded": "hepta_learning_artifact_owner_recovery_publications_succeeded_total",
    "withdrawalFrontiersInstalled": "hepta_learning_artifact_owner_withdrawal_frontiers_installed_total",
    "authzReloads": "hepta_learning_artifact_owner_authz_reloads_total",
    "backupsSucceeded": "hepta_learning_artifact_owner_backups_succeeded_total",
    "commandFailures": "hepta_learning_artifact_owner_command_failures_total",
}

OPERATIONAL_COUNTERS = {
    "recoveryReconciliationFailures": "hepta_learning_artifact_owner_recovery_failures_total",
    "withdrawalBlocks": "hepta_learning_artifact_owner_withdrawal_blocks_total",
    "identityConflicts": "hepta_learning_artifact_owner_identity_conflicts_total",
    "staleOwnerRejections": "hepta_learning_artifact_owner_stale_owner_failures_total",
    "persistenceUnknown": "hepta_learning_artifact_owner_persistence_unknown_failures_total",
    "capacityRejections": "hepta_learning_artifact_owner_capacity_failures_total",
    "observabilityFailures": "hepta_learning_artifact_owner_observability_failures_total",
}

OPTIONAL_GAUGES = {
    "oldestPendingAttemptAgeSeconds": "hepta_learning_artifact_owner_oldest_pending_attempt_age_seconds",
    "drainAgeSeconds": "hepta_learning_artifact_owner_drain_age_seconds",
}


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedSnapshot:
    value: dict[str, Any]
    modified_at: int


@dataclass(frozen=True)
class QuarantineObservation:
    observed_at: int
    items: int
    source_digest: str


def _load(path: pathlib.Path, expected_schema: str) -> LoadedSnapshot:
    try:
        raw = path.read_bytes()
        modified_at = int(path.stat().st_mtime)
    except OSError as exc:
        raise SnapshotError(f"cannot read {path}: {exc}") from exc
    if not raw or len(raw) > MAX_SNAPSHOT_BYTES:
        raise SnapshotError(f"invalid snapshot size for {path}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != expected_schema:
        raise SnapshotError(f"wrong schema in {path}")
    return LoadedSnapshot(value=value, modified_at=modified_at)


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SnapshotError(f"{field} must be a non-negative integer")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise SnapshotError(f"{field} must be a 64-character digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise SnapshotError(f"{field} must be lowercase hexadecimal") from exc
    if value != value.lower():
        raise SnapshotError(f"{field} must be lowercase hexadecimal")
    return value


def _emit(lines: list[str], metric_type: str, name: str, value: int) -> None:
    lines.append(f"# TYPE {name} {metric_type}")
    lines.append(f"{name} {value}")


def _emit_optional(lines: list[str], name: str, value: Any, field: str) -> None:
    _emit(lines, "gauge", f"{name}_known", int(value is not None))
    if value is not None:
        _emit(lines, "gauge", name, _nonnegative_int(value, field))


def _validate_base(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != COMMAND_SCHEMA:
        raise SnapshotError("operational base metrics have the wrong schema")
    for field in COMMAND_COUNTERS:
        _nonnegative_int(value.get(field), f"base.{field}")
    return value


def _validate_retention(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SnapshotError("retention must be null or an object")
    _nonnegative_int(value.get("pinnedBytes"), "retention.pinnedBytes")
    _nonnegative_int(
        value.get("pendingPhysicalEraseBytes"),
        "retention.pendingPhysicalEraseBytes",
    )
    _nonnegative_int(value.get("observedAt"), "retention.observedAt")
    _digest(value.get("sourceDigest"), "retention.sourceDigest")
    return value


def _validate_operational(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    base = _validate_base(value.get("base"))
    for field in OPERATIONAL_COUNTERS:
        _nonnegative_int(value.get(field), field)
    for field in OPTIONAL_GAUGES:
        if value.get(field) is not None:
            _nonnegative_int(value.get(field), field)
    stages = value.get("stageSummaries")
    if not isinstance(stages, dict):
        raise SnapshotError("stageSummaries must be an object")
    return base, _validate_retention(value.get("retention"))


def _load_quarantine(path: pathlib.Path | None, now: int, maximum_age: int) -> QuarantineObservation | None:
    if path is None:
        return None
    loaded = _load(path, QUARANTINE_SCHEMA)
    value = loaded.value
    observed_at = _nonnegative_int(value.get("observedAt"), "quarantine.observedAt")
    items = _nonnegative_int(value.get("items"), "quarantine.items")
    source_digest = _digest(value.get("sourceDigest"), "quarantine.sourceDigest")
    _require_fresh(observed_at, now, maximum_age, "quarantine observation")
    return QuarantineObservation(observed_at, items, source_digest)


def _require_fresh(observed_at: int, now: int, maximum_age: int, label: str) -> None:
    if now < observed_at or now - observed_at > maximum_age:
        raise SnapshotError(f"{label} is stale or from the future")


def render(
    operational: dict[str, Any],
    observed_at: int,
    quarantine: QuarantineObservation | None,
) -> bytes:
    base, retention = _validate_operational(operational)
    lines: list[str] = []
    for field, metric in COMMAND_COUNTERS.items():
        _emit(lines, "counter", metric, _nonnegative_int(base.get(field), f"base.{field}"))
    for field, metric in OPERATIONAL_COUNTERS.items():
        _emit(lines, "counter", metric, _nonnegative_int(operational.get(field), field))
    _emit(
        lines,
        "gauge",
        "hepta_learning_artifact_owner_observed_at_seconds",
        observed_at,
    )
    for field, metric in OPTIONAL_GAUGES.items():
        _emit_optional(lines, metric, operational.get(field), field)

    pinned = None if retention is None else retention["pinnedBytes"]
    pending_erase = None if retention is None else retention["pendingPhysicalEraseBytes"]
    _emit_optional(lines, "hepta_learning_artifact_owner_pinned_bytes", pinned, "retention.pinnedBytes")
    _emit_optional(
        lines,
        "hepta_learning_artifact_owner_pending_physical_erasure_bytes",
        pending_erase,
        "retention.pendingPhysicalEraseBytes",
    )
    _emit(
        lines,
        "gauge",
        "hepta_learning_artifact_owner_retention_observation_known",
        int(retention is not None),
    )
    quarantine_items = None if quarantine is None else quarantine.items
    _emit_optional(
        lines,
        "hepta_learning_artifact_owner_quarantine_items",
        quarantine_items,
        "quarantine.items",
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


class Exporter:
    def __init__(
        self,
        operational_path: pathlib.Path,
        quarantine_path: pathlib.Path | None,
        maximum_age: int,
    ) -> None:
        self.operational_path = operational_path
        self.quarantine_path = quarantine_path
        self.maximum_age = maximum_age

    def snapshot(self) -> bytes:
        now = int(time.time())
        operational = _load(self.operational_path, OPERATIONAL_SCHEMA)
        _require_fresh(
            operational.modified_at,
            now,
            self.maximum_age,
            "operational metrics snapshot",
        )
        quarantine = _load_quarantine(self.quarantine_path, now, self.maximum_age)
        return render(operational.value, operational.modified_at, quarantine)


def handler_for(exporter: Exporter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "hepta-learning-artifacts-exporter/1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path not in {"/metrics", "/healthz"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                metrics = exporter.snapshot()
            except SnapshotError as exc:
                body = (str(exc) + "\n").encode("utf-8")
                self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = metrics if self.path == "/metrics" else b"ok\n"
            content_type = CONTENT_TYPE if self.path == "/metrics" else "text/plain; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def parse_listen(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError("listen address must be HOST:PORT")
    try:
        number = int(port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("listen port must be numeric") from exc
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("listen port is out of range")
    return host, number


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operational-metrics", required=True, type=pathlib.Path)
    parser.add_argument("--quarantine-observation", type=pathlib.Path)
    parser.add_argument("--listen", default="127.0.0.1:9469", type=parse_listen)
    parser.add_argument("--maximum-age-seconds", default=120, type=int)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.maximum_age_seconds <= 0:
        parser.error("--maximum-age-seconds must be positive")
    exporter = Exporter(
        args.operational_metrics,
        args.quarantine_observation,
        args.maximum_age_seconds,
    )
    if args.check:
        exporter.snapshot()
        return 0
    server = ThreadingHTTPServer(args.listen, handler_for(exporter))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
