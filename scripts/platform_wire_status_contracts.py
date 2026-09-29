"""Closed lifecycle receipt field contracts for platform.wire evidence."""
from __future__ import annotations

import re

SCHEMA = "hepta.platform-wire.receipt.v2"
PASS = {"pass", "passed", "success", "qualified", "accepted", "released"}
H40 = re.compile(r"[0-9a-f]{40}")
H64 = re.compile(r"[0-9a-f]{64}")
PERF = "platform-wire-performance"
PROD = "platform-wire-production"
DESIGN = (
    "docs/modules/platform.wire/README.md",
    "docs/modules/platform.wire/TECHNICAL.md",
    "docs/lane-a-foundation/platform.wire/WIRE_V1.md",
    "docs/lane-a-foundation/platform.wire/WIRE_V2.md",
    "docs/lane-a-foundation/platform.wire/NEGOTIATION_V1.md",
    "docs/modules/platform.wire/SECURITY_AND_QUALIFICATION.md",
)
IMPL = tuple(
    "codex-rs/hepta-wire/src/" + name
    for name in (
        "envelope.rs",
        "envelope_v2.rs",
        "frame.rs",
        "frame_header.rs",
        "version.rs",
        "session.rs",
        "stream.rs",
        "schema.rs",
        "registry.rs",
        "secure_session.rs",
        "directional_session.rs",
        "authentication.rs",
        "managed_session.rs",
        "codec_binding.rs",
        "feed.rs",
    )
)
WORK = {
    "platform-wire-exact-head",
    "platform-wire-synthetic-merge",
    "platform-wire-target-host",
    PERF,
    PROD,
}
ACCEPT = {
    "platform-wire-reviewer-acceptance": "independent-reviewer",
    "platform-wire-operations-acceptance": "operations",
}
PROD_METRICS = {
    "authenticated-ingress": {
        "authenticated_sessions",
        "rejected_untrusted_peers",
    },
    "gateway-provider-e2e": {
        "completed_operations",
        "terminal_receipts",
    },
    "bounded-pressure": {
        "max_connections_observed",
        "connection_limit",
        "max_transport_queue_bytes",
        "transport_queue_limit_bytes",
        "max_consumer_retained_bytes",
        "consumer_retained_limit_bytes",
        "max_active_fragment_bytes",
        "active_fragment_limit_bytes",
        "pressure_samples",
        "max_rss_bytes",
    },
    "deadline-cancellation": {
        "deadline_cases",
        "cancellation_cases",
        "reconciled_indeterminate_cases",
        "blind_retries",
    },
    "reconnect-restart": {
        "reconnects",
        "process_restarts",
        "stale_session_rejections",
    },
    "key-rotation-retirement": {
        "rotations",
        "retired_session_rejections",
    },
    "mixed-version-rolling": {
        "rolling_steps",
        "downgrade_rejections",
        "mixed_version_sessions",
    },
    "canary-rollback": {
        "canary_windows",
        "rollback_rehearsals",
        "failed_rollbacks",
    },
}
ASSERTS = {
    scenario: (
        5
        if scenario
        in {
            "authenticated-ingress",
            "gateway-provider-e2e",
            "bounded-pressure",
        }
        else 4
    )
    for scenario in PROD_METRICS
}


def string(payload: dict, name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value.strip()


def sha(payload: dict, name: str) -> str:
    value = string(payload, name)
    if H40.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def dig(payload: dict, name: str) -> str:
    value = string(payload, name)
    if H64.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def pos(payload: dict, name: str) -> int:
    value = payload.get(name)
    if type(value) is not int or value <= 0:
        raise ValueError(f"invalid {name}")
    return value


def nonneg(payload: dict, name: str) -> int:
    value = payload.get(name)
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def perf(payload: dict) -> None:
    if string(payload, "reference_transport") != "grpc" or pos(payload, "path_count") != 5:
        raise ValueError("performance shape")
    policy = (
        pos(payload, "size_ratio_numerator"),
        pos(payload, "size_ratio_denominator"),
        pos(payload, "p99_ratio_numerator"),
        pos(payload, "p99_ratio_denominator"),
    )
    if policy != (70, 100, 80, 100):
        raise ValueError("performance policy")
    rows = payload.get("paths")
    if not isinstance(rows, list) or len(rows) != 5:
        raise ValueError("performance paths")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("performance row")
        identity = string(row, "path_id")
        if identity in seen or pos(row, "sample_count") < 100:
            raise ValueError("performance identity/count")
        seen.add(identity)
        candidate_size = pos(row, "candidate_package_bytes")
        reference_size = pos(row, "reference_package_bytes")
        candidate_p99 = pos(row, "candidate_p99_ns")
        reference_p99 = pos(row, "reference_p99_ns")
        if candidate_size * 100 > reference_size * 70:
            raise ValueError("performance threshold")
        if candidate_p99 * 100 > reference_p99 * 80:
            raise ValueError("performance threshold")


def production(payload: dict) -> None:
    if pos(payload, "scenario_count") != 8:
        raise ValueError("production count")
    transport = payload.get("transport")
    if not isinstance(transport, dict):
        raise ValueError("production transport")
    if string(transport, "network_scope") not in {
        "host-network",
        "cluster-network",
        "cross-host",
    }:
        raise ValueError("production transport")
    if string(transport, "channel_binding") not in {
        "tls-exporter",
        "noise-handshake-hash",
        "mutually-authenticated-local-binding",
    }:
        raise ValueError("production transport")
    string(transport, "peer_identity_scheme")
    string(transport, "key_provenance")
    rows = payload.get("scenarios")
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("production scenarios")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("production row")
        scenario = string(row, "scenario_id")
        if scenario not in PROD_METRICS or scenario in seen:
            raise ValueError("production scenario identity")
        seen.add(scenario)
        attempts = pos(row, "attempts")
        if pos(row, "completed_operations") > attempts:
            raise ValueError("production scenario outcome")
        if nonneg(row, "unexpected_failures") != 0:
            raise ValueError("production scenario outcome")
        if pos(row, "assertion_count") != ASSERTS[scenario]:
            raise ValueError("production scenario outcome")
        dig(row, "artifact_sha256")
        dig(row, "log_sha256")
        metrics = row.get("metrics")
        if not isinstance(metrics, dict) or set(metrics) != PROD_METRICS[scenario]:
            raise ValueError("production metrics")
        values = {name: nonneg(metrics, name) for name in metrics}
        for name, value in values.items():
            if name not in {"blind_retries", "failed_rollbacks"} and value <= 0:
                raise ValueError("production metric positive")
        if scenario == "bounded-pressure":
            for observed, limit in (
                ("max_connections_observed", "connection_limit"),
                ("max_transport_queue_bytes", "transport_queue_limit_bytes"),
                ("max_consumer_retained_bytes", "consumer_retained_limit_bytes"),
                ("max_active_fragment_bytes", "active_fragment_limit_bytes"),
            ):
                if values[observed] > values[limit]:
                    raise ValueError("production resource ceiling")
            if values["pressure_samples"] < 100:
                raise ValueError("pressure sample floor")
        if scenario == "deadline-cancellation" and values["blind_retries"]:
            raise ValueError("blind retry")
        if scenario == "mixed-version-rolling" and values["rolling_steps"] < 2:
            raise ValueError("rolling floor")
        if scenario == "canary-rollback" and values["failed_rollbacks"]:
            raise ValueError("rollback failure")
    if seen != set(PROD_METRICS):
        raise ValueError("production coverage")
