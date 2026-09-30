#!/usr/bin/env python3
"""Evaluate bounded channel.matrix diagnostic snapshots against an explicit policy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from channel_matrix_evidence import file_digest, read_object

ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA = "hepta.channel-matrix-alert-policy.v1"
SNAPSHOT_SCHEMA = "hepta.channel-matrix-diagnostics.v1"
RESULT_SCHEMA = "hepta.channel-matrix-alert-evaluation.v1"

OUTBOX = ("pending", "in_flight", "retry_scheduled", "sent", "permanent_failure")
LEDGER = (
    "dispatched",
    "accepted",
    "indeterminate",
    "succeeded",
    "observed_unqualified",
    "failed",
    "redacted",
)
FAILURES = (
    "retryable",
    "rate_limited",
    "dns",
    "tls",
    "connect_timeout",
    "connect_failure",
    "read_timeout",
    "connection_reset",
    "response_lost",
    "server_unavailable",
    "permanent",
    "authority_denied",
)
RECOVERY_FAILURES = (
    "dependency_unavailable",
    "identity_conflict",
    "binding_unrecoverable",
    "invalid_input",
)
BASE_ALERTS = {
    "unresolved_capacity",
    "sync_checkpoint_stale",
    "queue_age",
    "expired_claims",
    "parked_work",
    "inbox_quarantine",
}
POLICY_ALERTS = {
    "sync_checkpoint_stale_with_unresolved_work",
    "indeterminate_age",
    "rate_limit_pressure",
    "authority_denial_pressure",
    "response_loss_pressure",
    "inbox_dependency_pressure",
    "claim_expiry_pressure",
    "parked_work_pressure",
    "redaction_propagation_lag",
}
SEVERITY = {"warning": 1, "critical": 2}
POLICY_FIELDS = {
    "schema",
    "syncStaleMs",
    "queueAgeWarningMs",
    "indeterminateAgeWarningMs",
    "rateLimitedEventsWarning",
    "authorityDeniedEventsCritical",
    "responseLostEventsWarning",
    "inboxDependencyUnavailableWarning",
    "expiredClaimCountWarning",
    "expiredClaimAgeWarningMs",
    "parkedQueueWarning",
    "parkedAgeWarningMs",
    "redactionPropagationWarningMs",
}


def _count_map(value: object, labels: tuple[str, ...], name: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != set(labels):
        raise ValueError(f"{name} must use the closed label inventory")
    result: dict[str, int] = {}
    for label in labels:
        count = value[label]
        if type(count) is not int or not 0 <= count <= 2**63 - 1:
            raise ValueError(f"invalid {name} count")
        result[label] = count
    return result


def _optional_age(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f"invalid {name}")
    return value


def _count(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f"invalid {name}")
    return value


def load_policy(path: Path) -> dict[str, int | str]:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file() or resolved != path.absolute():
        raise ValueError("canonical regular alert policy required")
    if resolved.stat().st_size > 64 * 1024:
        raise ValueError("alert policy exceeds budget")
    row = read_object(resolved)
    if set(row) != POLICY_FIELDS or row.get("schema") != POLICY_SCHEMA:
        raise ValueError("unsupported alert policy")
    for key in POLICY_FIELDS - {"schema"}:
        value = row[key]
        if type(value) is not int or not 1 <= value <= 7 * 24 * 60 * 60 * 1000:
            raise ValueError("invalid alert threshold")
    return row


def _base_alerts(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("snapshot alerts must be a list")
    result = []
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != {"code", "severity", "action"}
            or row.get("code") not in BASE_ALERTS
            or row.get("severity") not in SEVERITY
            or not isinstance(row.get("action"), str)
            or not row["action"]
        ):
            raise ValueError("unsupported built-in alert")
        result.append(dict(row))
    return result


def evaluate(snapshot: dict, policy: dict) -> dict:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("unsupported diagnostic snapshot")
    if policy.get("schema") != POLICY_SCHEMA or set(policy) != POLICY_FIELDS:
        raise ValueError("unsupported alert policy")

    outbox = _count_map(snapshot.get("outbox"), OUTBOX, "outbox")
    dispatch = _count_map(snapshot.get("dispatch"), LEDGER, "dispatch")
    failures = _count_map(snapshot.get("failures_last_300s"), FAILURES, "failure")
    recovery_failures = _count_map(
        snapshot.get("recovery_failures"), RECOVERY_FAILURES, "recovery failure"
    )
    sync_age = _optional_age(snapshot.get("sync_checkpoint_age_ms"), "sync age")
    queue_age = _optional_age(snapshot.get("oldest_queue_age_ms"), "queue age")
    indeterminate_age = _optional_age(
        snapshot.get("oldest_indeterminate_age_ms"), "indeterminate age"
    )
    parked_age = _optional_age(snapshot.get("oldest_parked_age_ms"), "parked age")
    expired_age = _optional_age(
        snapshot.get("oldest_expired_claim_age_ms"), "expired claim age"
    )
    redaction_latency = _optional_age(
        snapshot.get("redaction_propagation_max_last_300s_ms"),
        "redaction propagation latency",
    )
    parked = _count(snapshot.get("parked_queue", 0), "parked queue")
    expired = _count(snapshot.get("expired_claims", 0), "expired claims")
    unresolved = sum(dispatch[label] for label in LEDGER[:3])
    pending = sum(outbox[label] for label in OUTBOX[:3])
    if snapshot.get("unresolved") != unresolved:
        raise ValueError("snapshot unresolved count is inconsistent")
    if snapshot.get("authority_granted") is not False:
        raise ValueError("diagnostics cannot grant authority")

    alerts = _base_alerts(snapshot.get("alerts"))
    by_code = {row["code"]: row for row in alerts}

    def add(code: str, severity: str, action: str) -> None:
        current = by_code.get(code)
        if current is None:
            row = {"code": code, "severity": severity, "action": action}
            alerts.append(row)
            by_code[code] = row
        elif SEVERITY[severity] > SEVERITY[current["severity"]]:
            current["severity"] = severity
            current["action"] = action

    if (pending or unresolved) and (
        sync_age is None or sync_age >= policy["syncStaleMs"]
    ):
        add(
            "sync_checkpoint_stale_with_unresolved_work",
            "critical",
            "stop_new_admission_restore_authenticated_sync_preserve_transactions",
        )
    if queue_age is not None and queue_age >= policy["queueAgeWarningMs"]:
        add("queue_age", "warning", "inspect_owner_and_reconciliation")
    if (
        indeterminate_age is not None
        and indeterminate_age >= policy["indeterminateAgeWarningMs"]
    ):
        add(
            "indeterminate_age",
            "warning",
            "restore_authenticated_sync_preserve_same_transaction",
        )
    if failures["rate_limited"] >= policy["rateLimitedEventsWarning"]:
        add("rate_limit_pressure", "warning", "inspect_retry_after_and_capacity")
    if failures["authority_denied"] >= policy["authorityDeniedEventsCritical"]:
        add(
            "authority_denial_pressure",
            "critical",
            "stop_dispatch_restore_broker_and_revocation_freshness",
        )
    if failures["response_lost"] >= policy["responseLostEventsWarning"]:
        add(
            "response_loss_pressure",
            "warning",
            "restore_sync_and_reconcile_unknown_effects",
        )
    if (
        recovery_failures["dependency_unavailable"]
        >= policy["inboxDependencyUnavailableWarning"]
    ):
        add(
            "inbox_dependency_pressure",
            "warning",
            "restore_dependency_keep_event_identity_and_backoff",
        )
    if expired >= policy["expiredClaimCountWarning"] or (
        expired_age is not None and expired_age >= policy["expiredClaimAgeWarningMs"]
    ):
        add(
            "claim_expiry_pressure",
            "warning",
            "verify_process_lease_and_run_fenced_recovery_never_edit_claims",
        )
    if parked >= policy["parkedQueueWarning"] or (
        parked_age is not None and parked_age >= policy["parkedAgeWarningMs"]
    ):
        add(
            "parked_work_pressure",
            "warning",
            "restore_authenticated_sync_preserve_stable_transactions",
        )
    if (
        redaction_latency is not None
        and redaction_latency >= policy["redactionPropagationWarningMs"]
    ):
        add(
            "redaction_propagation_lag",
            "warning",
            "inspect_sync_redaction_frontier_and_preserve_terminal_lineage",
        )

    alerts.sort(key=lambda row: (-SEVERITY[row["severity"]], row["code"]))
    maximum = max((SEVERITY[row["severity"]] for row in alerts), default=0)
    return {
        "schema": RESULT_SCHEMA,
        "observed_at_ms": snapshot.get("observed_at_ms"),
        "status": ("critical" if maximum == 2 else "warning" if maximum == 1 else "ok"),
        "alerts": alerts,
        "policy": {
            key: policy[key] for key in sorted(POLICY_FIELDS) if key != "schema"
        },
        "scope": "policy_evaluation_of_read_only_snapshot_not_authority",
        "authority_granted": False,
        "activation": False,
        "release": False,
    }


def prometheus(row: dict) -> str:
    lines = [
        f'hepta_matrix_policy_status{{state="{state}"}} {int(row["status"] == state)}'
        for state in ("ok", "warning", "critical")
    ]
    allowed = BASE_ALERTS | POLICY_ALERTS
    for alert in row["alerts"]:
        if alert["code"] not in allowed or alert["severity"] not in SEVERITY:
            raise ValueError("open-ended alert label")
        lines.append(
            f'hepta_matrix_policy_alert{{code="{alert["code"]}",'
            f'severity="{alert["severity"]}"}} 1'
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "docs/modules/channel.matrix/ALERT_POLICY.json",
    )
    parser.add_argument("--format", choices=("json", "prometheus"), default="json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        snapshot_path = args.snapshot.resolve(strict=True)
        if args.snapshot.is_symlink() or not snapshot_path.is_file():
            raise ValueError("canonical regular snapshot required")
        snapshot = read_object(snapshot_path)
        policy = load_policy(args.policy)
        row = evaluate(snapshot, policy)
        row["snapshot_sha256"] = file_digest(snapshot_path)
        row["policy_sha256"] = file_digest(args.policy.resolve(strict=True))
        print(
            json.dumps(row, indent=2, sort_keys=True)
            if args.format == "json"
            else prometheus(row),
            end="\n",
        )
        if not args.check:
            return 0
        return {"ok": 0, "warning": 1, "critical": 2}[row["status"]]
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print(
            json.dumps(
                {
                    "schema": RESULT_SCHEMA,
                    "status": "unavailable",
                    "authority_granted": False,
                    "activation": False,
                    "release": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
