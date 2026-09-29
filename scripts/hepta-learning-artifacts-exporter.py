#!/usr/bin/env python3
"""Fail-closed Prometheus sidecar for learning.artifacts owner metrics.

The owner writes authenticated JSON snapshots through its normal operations
surface. This sidecar only projects those snapshots; it grants no owner,
selection, activation, promotion or release authority.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

COMMAND_SCHEMA = "hepta.learning-artifactd.metrics.v1"
OPERATIONAL_SCHEMA = "hepta.learning-artifactd.operational-metrics.v1"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

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
    "recoveryFailures": "hepta_learning_artifact_owner_recovery_failures_total",
    "withdrawalBlocks": "hepta_learning_artifact_owner_withdrawal_blocks_total",
    "withdrawalBlockSeconds": "hepta_learning_artifact_owner_withdrawal_block_seconds_total",
    "identityConflicts": "hepta_learning_artifact_owner_identity_conflicts_total",
    "staleOwnerFailures": "hepta_learning_artifact_owner_stale_owner_failures_total",
    "persistenceUnknownFailures": "hepta_learning_artifact_owner_persistence_unknown_failures_total",
    "capacityFailures": "hepta_learning_artifact_owner_capacity_failures_total",
    "observabilityFailures": "hepta_learning_artifact_owner_observability_failures_total",
}

OPERATIONAL_GAUGES = {
    "startedAt": "hepta_learning_artifact_owner_started_at_seconds",
    "observedAt": "hepta_learning_artifact_owner_observed_at_seconds",
    "pendingAttempts": "hepta_learning_artifact_owner_pending_attempts",
}

OPTIONAL_GAUGES = {
    "oldestPendingAttemptAgeSeconds": "hepta_learning_artifact_owner_oldest_pending_attempt_age_seconds",
    "drainAgeSeconds": "hepta_learning_artifact_owner_drain_age_seconds",
    "pinnedBytes": "hepta_learning_artifact_owner_pinned_bytes",
    "pendingPhysicalErasureBytes": "hepta_learning_artifact_owner_pending_physical_erasure_bytes",
}


class SnapshotError(RuntimeError):
    pass


def _load(path: pathlib.Path, expected_schema: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SnapshotError(f"cannot read {path}: {exc}") from exc
    if not raw or len(raw) > 1_048_576:
        raise SnapshotError(f"invalid snapshot size for {path}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != expected_schema:
        raise SnapshotError(f"wrong schema in {path}")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SnapshotError(f"{field} must be a non-negative integer")
    return value


def _emit(lines: list[str], metric_type: str, name: str, value: int) -> None:
    lines.append(f"# TYPE {name} {metric_type}")
    lines.append(f"{name} {value}")


def _emit_optional(lines: list[str], name: str, value: Any, field: str) -> None:
    _emit(lines, "gauge", f"{name}_known", int(value is not None))
    if value is not None:
        _emit(lines, "gauge", name, _nonnegative_int(value, field))


def render(command: dict[str, Any], operational: dict[str, Any], now: int, maximum_age: int) -> bytes:
    observed = _nonnegative_int(operational.get("observedAt"), "observedAt")
    if now < observed or now - observed > maximum_age:
        raise SnapshotError("operational snapshot is stale or from the future")
    lines: list[str] = []
    for field, metric in COMMAND_COUNTERS.items():
        _emit(lines, "counter", metric, _nonnegative_int(command.get(field), field))
    for field, metric in OPERATIONAL_COUNTERS.items():
        _emit(lines, "counter", metric, _nonnegative_int(operational.get(field), field))
    for field, metric in OPERATIONAL_GAUGES.items():
        _emit(lines, "gauge", metric, _nonnegative_int(operational.get(field), field))
    for field, metric in OPTIONAL_GAUGES.items():
        _emit_optional(lines, metric, operational.get(field), field)
    retention = operational.get("retentionObservationDigest")
    if retention is not None and (not isinstance(retention, str) or len(retention) != 64):
        raise SnapshotError("retentionObservationDigest must be null or a 64-character digest")
    _emit(
        lines,
        "gauge",
        "hepta_learning_artifact_owner_retention_observation_known",
        int(retention is not None),
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


class Exporter:
    def __init__(
        self,
        command_path: pathlib.Path,
        operational_path: pathlib.Path,
        maximum_age: int,
    ) -> None:
        self.command_path = command_path
        self.operational_path = operational_path
        self.maximum_age = maximum_age

    def snapshot(self) -> bytes:
        command = _load(self.command_path, COMMAND_SCHEMA)
        operational = _load(self.operational_path, OPERATIONAL_SCHEMA)
        return render(command, operational, int(time.time()), self.maximum_age)


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
    parser.add_argument("--command-metrics", required=True, type=pathlib.Path)
    parser.add_argument("--operational-metrics", required=True, type=pathlib.Path)
    parser.add_argument("--listen", default="127.0.0.1:9469", type=parse_listen)
    parser.add_argument("--maximum-age-seconds", default=120, type=int)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.maximum_age_seconds <= 0:
        parser.error("--maximum-age-seconds must be positive")
    exporter = Exporter(
        args.command_metrics,
        args.operational_metrics,
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
