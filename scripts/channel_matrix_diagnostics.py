#!/usr/bin/env python3
"""Bounded read-only Matrix diagnostics. No repair, send or authority operation."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

MAX_I64 = 2**63 - 1
SCHEMA_VERSION = 13
RECOVERY = ("running", "ready", "retry", "quarantined")
RECOVERY_FAILURES = (
    "dependency_unavailable",
    "identity_conflict",
    "binding_unrecoverable",
    "invalid_input",
)
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
PHASES = ("claimed", "authorized", "dispatching")
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
ATTEMPT_EVENTS = (
    "claimed",
    "prepared",
    "authorized",
    "dispatching",
    "transport_accepted",
    "indeterminate",
    "retry_scheduled",
    "confirmed",
    "redacted",
    "permanently_rejected",
    "revoked",
    "canceled",
    "expired",
)
UNMEASURED = (
    "live_authority_freshness",
    "supervisor_restarts",
    "encrypted_session_continuity",
)


def grouped(
    db: sqlite3.Connection, query: str, allowed: tuple[str, ...], args=()
) -> dict:
    result = dict.fromkeys(allowed, 0)
    for key, count in db.execute(query, args):
        if key not in result:
            raise ValueError("unsupported durable state")
        result[key] = count
    return result


def age(now: int, timestamp: int | None) -> int | None:
    if timestamp is None:
        return None
    if timestamp > now or timestamp < 0:
        raise ValueError("clock precedes durable observation")
    return now - timestamp


def selected_dispatch(row: tuple | None, now_ms: int) -> dict:
    """Classify one selected transaction without returning its identifier or payload."""
    if row is None:
        return {"reason": "not_found"}
    (
        queue,
        state,
        attempts,
        next_ms,
        held,
        entered,
        phase,
        lease_until_ms,
        latest_event,
        latest_failure,
        latest_retry_after_ms,
    ) = row
    if queue not in OUTBOX or state not in (*LEDGER, None):
        raise ValueError("unsupported selected state")
    if phase not in (*PHASES, None):
        raise ValueError("unsupported active claim phase")
    if latest_event not in (*ATTEMPT_EVENTS, None):
        raise ValueError("unsupported attempt event")
    if latest_failure not in (*FAILURES, None):
        raise ValueError("unsupported attempt failure")
    if type(attempts) is not int or attempts < 0:
        raise ValueError("invalid attempt count")
    for value in (next_ms, lease_until_ms, latest_retry_after_ms):
        if value is not None and (
            type(value) is not int or not 0 <= value <= MAX_I64
        ):
            raise ValueError("invalid diagnostic timestamp or delay")

    terminal = state in ("succeeded", "observed_unqualified", "failed", "redacted")
    if terminal:
        reason, retry, action = "terminal_observed", "not_applicable", "none"
    elif held:
        reason = "legacy_hold_requires_authenticated_reconciliation"
        retry, action = "forbidden", "restore_authenticated_sync_preserve_transaction"
    elif next_ms == MAX_I64:
        reason = "parked_requires_authenticated_reconciliation"
        retry, action = "forbidden", "restore_authenticated_sync_preserve_transaction"
    elif state in ("accepted", "indeterminate"):
        reason = "remote_result_not_yet_reconciled"
        retry = "owner_policy_same_transaction_only"
        action = "restore_authenticated_sync_preserve_transaction"
    elif phase is not None and lease_until_ms is not None and lease_until_ms <= now_ms:
        reason = "expired_active_claim_requires_fenced_recovery"
        retry = "owner_fenced_recovery_only"
        action = "verify_process_lease_then_expire_same_claim"
    elif phase is not None:
        reason = {
            "claimed": "active_claim_preparing",
            "authorized": "active_claim_authorized",
            "dispatching": "active_claim_dispatching_or_unknown_effect",
        }[phase]
        retry = "forbidden_while_live_claim"
        action = "wait_exact_owner_or_fenced_recovery"
    elif queue == "retry_scheduled" and next_ms is not None and next_ms > now_ms:
        reason = "retry_window_not_due"
        retry = "wait_until_next_attempt_at"
        action = "wait_owner_schedule"
    elif latest_failure == "authority_denied":
        reason = "fresh_authority_required"
        retry = "owner_fresh_grant_only"
        action = "restore_broker_and_revocation_freshness"
    elif queue == "permanent_failure":
        reason, retry, action = (
            "permanent_failure",
            "forbidden",
            "inspect_terminal_evidence",
        )
    else:
        reason, retry, action = (
            "pending_owner_execution",
            "owner_policy_only",
            "wait_owner",
        )

    return {
        "queue_state": queue,
        "dispatch_state": state,
        "attempts": attempts,
        "next_attempt_at_ms": next_ms,
        "active_claim_phase": phase,
        "active_claim_lease_until_ms": lease_until_ms,
        "latest_attempt_event": latest_event,
        "latest_failure_class": latest_failure,
        "latest_retry_after_ms": latest_retry_after_ms,
        "entered_evidence_exists": bool(entered),
        "reason": reason,
        "retry": retry,
        "action": action,
    }


def diagnose(
    db: sqlite3.Connection,
    now_ms: int,
    capacity: int = 4096,
    transaction: str | None = None,
    event: str | None = None,
) -> dict:
    if type(now_ms) is not int or not 0 <= now_ms <= MAX_I64:
        raise ValueError("invalid observation time")
    if type(capacity) is not int or not 1 <= capacity <= 1_000_000:
        raise ValueError("invalid capacity policy")
    if transaction is not None and not 1 <= len(transaction.encode()) <= 512:
        raise ValueError("invalid transaction identity")
    if event is not None and not 1 <= len(event.encode()) <= 512:
        raise ValueError("invalid event identity")
    versions = db.execute(
        "SELECT version, success FROM _sqlx_migrations ORDER BY version"
    ).fetchall()
    if versions != [(version, 1) for version in range(1, SCHEMA_VERSION + 1)]:
        raise ValueError("unsupported or incomplete migration history")

    outbox = grouped(
        db, "SELECT state, count(*) FROM outbox_messages GROUP BY state", OUTBOX
    )
    ledger = grouped(
        db, "SELECT state, count(*) FROM matrix_dispatch_ledger GROUP BY state", LEDGER
    )
    claims = grouped(
        db,
        "SELECT phase, count(*) FROM matrix_dispatch_active_claims GROUP BY phase",
        PHASES,
    )
    failures = grouped(
        db,
        """SELECT failure_class, count(*) FROM matrix_dispatch_attempt_events
        WHERE recorded_at_ms >= ? AND recorded_at_ms <= ? AND failure_class IS NOT NULL
        GROUP BY failure_class""",
        FAILURES,
        (max(0, now_ms - 300_000), now_ms),
    )
    checkpoint = db.execute(
        "SELECT updated_at_ms FROM matrix_sync_checkpoint WHERE singleton=1"
    ).fetchone()
    sync_age = age(now_ms, checkpoint[0] if checkpoint else None)
    oldest = db.execute(
        """SELECT min(created_at_ms) FROM outbox_messages
        WHERE state IN ('pending','in_flight','retry_scheduled')"""
    ).fetchone()[0]
    oldest_age = age(now_ms, oldest)
    expired = db.execute(
        "SELECT count(*) FROM matrix_dispatch_active_claims WHERE lease_until_ms <= ?",
        (now_ms,),
    ).fetchone()[0]
    oldest_expired_lease = db.execute(
        """SELECT min(lease_until_ms) FROM matrix_dispatch_active_claims
        WHERE lease_until_ms <= ?""",
        (now_ms,),
    ).fetchone()[0]
    holds = db.execute(
        """SELECT count(*) FROM matrix_dispatch_legacy_content_holds h
        JOIN matrix_dispatch_ledger d USING(stable_txn_id)
        WHERE d.state IN ('dispatched','accepted','indeterminate')"""
    ).fetchone()[0]
    parked = db.execute(
        """SELECT count(*) FROM outbox_messages
        WHERE state IN ('pending','in_flight','retry_scheduled')
          AND next_attempt_at_ms=?""",
        (MAX_I64,),
    ).fetchone()[0]
    oldest_parked = db.execute(
        """SELECT min(created_at_ms) FROM outbox_messages
        WHERE state IN ('pending','in_flight','retry_scheduled')
          AND next_attempt_at_ms=?""",
        (MAX_I64,),
    ).fetchone()[0]
    redaction_latency = db.execute(
        """SELECT max(
               redaction.observed_at_ms -
               (SELECT min(send.observed_at_ms)
                  FROM matrix_dispatch_observations send
                 WHERE send.stable_txn_id=redaction.stable_txn_id
                   AND send.observation_kind='homeserver_event'
                   AND send.observed_at_ms <= redaction.observed_at_ms)
           )
          FROM matrix_dispatch_observations redaction
         WHERE redaction.observation_kind='redaction'
           AND redaction.observed_at_ms >= ?
           AND redaction.observed_at_ms <= ?
           AND EXISTS (
               SELECT 1 FROM matrix_dispatch_observations send
                WHERE send.stable_txn_id=redaction.stable_txn_id
                  AND send.observation_kind='homeserver_event'
                  AND send.observed_at_ms <= redaction.observed_at_ms
           )""",
        (max(0, now_ms - 300_000), now_ms),
    ).fetchone()[0]
    if redaction_latency is not None and (
        type(redaction_latency) is not int or redaction_latency < 0
    ):
        raise ValueError("invalid redaction propagation latency")

    unresolved = sum(ledger[state] for state in LEDGER[:3])
    pending = sum(outbox[state] for state in OUTBOX[:3])
    inbox_oldest = db.execute(
        "SELECT min(received_at_ms) FROM matrix_visible_inbox_events_v2 WHERE state='pending'"
    ).fetchone()[0]
    unknown_oldest = db.execute(
        "SELECT min(prepared_at_ms) FROM matrix_dispatch_ledger WHERE state='indeterminate'"
    ).fetchone()[0]
    recovery = grouped(
        db,
        """SELECT r.outcome, count(*) FROM matrix_inbox_recovery r
        JOIN matrix_visible_inbox_events_v2 i USING(event_id) WHERE i.state='pending'
        GROUP BY r.outcome""",
        RECOVERY,
    )
    recovery_failures = grouped(
        db,
        """SELECT r.failure_class, count(*) FROM matrix_inbox_recovery r
        JOIN matrix_visible_inbox_events_v2 i USING(event_id) WHERE i.state='pending'
        AND r.failure_class IS NOT NULL GROUP BY r.failure_class""",
        RECOVERY_FAILURES,
    )
    recovery_attempts = db.execute(
        "SELECT COALESCE(sum(attempts),0) FROM matrix_inbox_recovery"
    ).fetchone()[0]
    selected_event = None
    if event is not None:
        detail = db.execute(
            """SELECT i.state, r.outcome, r.attempts, r.failure_class, r.next_attempt_at_ms
            FROM matrix_visible_inbox_events_v2 i
            LEFT JOIN matrix_inbox_recovery r USING(event_id)
            WHERE i.event_id=?""",
            (event,),
        ).fetchone()
        if detail is None:
            selected_event = {"reason": "not_visible_or_absent"}
        else:
            state, outcome, attempts, failure, next_ms = detail
            if outcome not in (*RECOVERY, None) or failure not in (
                *RECOVERY_FAILURES,
                None,
            ):
                raise ValueError("unsupported recovery state")
            action = (
                "none"
                if state == "processed"
                else "inspect_binding_preserve_identity_no_manual_unquarantine"
                if outcome == "quarantined"
                else "wait_dependency_and_owner_backoff"
                if outcome == "retry"
                else "wait_same_identity_reconciliation"
                if outcome == "running"
                else "wait_owner"
            )
            selected_event = {
                "inbox_state": state,
                "recovery_state": outcome,
                "attempts": attempts or 0,
                "failure_class": failure,
                "next_attempt_at_ms": next_ms,
                "action": action,
            }

    alerts = []
    if unresolved >= capacity:
        alerts.append(
            {
                "code": "unresolved_capacity",
                "severity": "critical",
                "action": "stop_admission_preserve_evidence",
            }
        )
    elif unresolved * 5 >= capacity * 4:
        alerts.append(
            {
                "code": "unresolved_capacity",
                "severity": "warning",
                "action": "plan_authenticated_retention",
            }
        )
    if pending and (sync_age is None or sync_age >= 120_000):
        alerts.append(
            {
                "code": "sync_checkpoint_stale",
                "severity": "critical",
                "action": "inspect_sync_no_new_transaction",
            }
        )
    if oldest_age is not None and oldest_age >= 300_000:
        alerts.append(
            {
                "code": "queue_age",
                "severity": "warning",
                "action": "inspect_owner_and_reconciliation",
            }
        )
    if expired:
        alerts.append(
            {
                "code": "expired_claims",
                "severity": "warning",
                "action": "inspect_process_lease_never_edit_claim",
            }
        )
    if parked:
        alerts.append(
            {
                "code": "parked_work",
                "severity": "warning",
                "action": "restore_authenticated_sync_preserve_transaction",
            }
        )
    if recovery["quarantined"]:
        alerts.append(
            {
                "code": "inbox_quarantine",
                "severity": "warning",
                "action": "inspect_exact_binding_preserve_pending_event",
            }
        )

    selected = None
    if transaction is not None:
        row = db.execute(
            """SELECT o.state, d.state, o.attempts, o.next_attempt_at_ms,
            EXISTS(SELECT 1 FROM matrix_dispatch_legacy_content_holds h
                   WHERE h.stable_txn_id=o.stable_txn_id),
            EXISTS(SELECT 1 FROM matrix_dispatch_use_entries u
                   WHERE u.stable_txn_id=o.stable_txn_id),
            c.phase, c.lease_until_ms,
            (SELECT e.event_kind FROM matrix_dispatch_attempt_events e
             WHERE e.stable_txn_id=o.stable_txn_id ORDER BY e.event_seq DESC LIMIT 1),
            (SELECT e.failure_class FROM matrix_dispatch_attempt_events e
             WHERE e.stable_txn_id=o.stable_txn_id AND e.failure_class IS NOT NULL
             ORDER BY e.event_seq DESC LIMIT 1),
            (SELECT e.retry_after_ms FROM matrix_dispatch_attempt_events e
             WHERE e.stable_txn_id=o.stable_txn_id AND e.retry_after_ms IS NOT NULL
             ORDER BY e.event_seq DESC LIMIT 1)
            FROM outbox_messages o
            LEFT JOIN matrix_dispatch_ledger d USING(stable_txn_id)
            LEFT JOIN matrix_dispatch_active_claims c USING(stable_txn_id)
            WHERE o.stable_txn_id=?""",
            (transaction,),
        ).fetchone()
        selected = selected_dispatch(row, now_ms)

    return {
        "schema": "hepta.channel-matrix-diagnostics.v1",
        "observed_at_ms": now_ms,
        "scope": "read_only_durable_snapshot_not_authority_or_native_integrity_proof",
        "schema_version": SCHEMA_VERSION,
        "capacity_policy": capacity,
        "outbox": outbox,
        "dispatch": ledger,
        "active_claims": claims,
        "failures_last_300s": failures,
        "unresolved": unresolved,
        "unresolved_legacy_holds": holds,
        "parked_queue": parked,
        "expired_claims": expired,
        "sync_checkpoint_age_ms": sync_age,
        "oldest_queue_age_ms": oldest_age,
        "oldest_parked_age_ms": age(now_ms, oldest_parked),
        "oldest_expired_claim_age_ms": age(now_ms, oldest_expired_lease),
        "redaction_propagation_max_last_300s_ms": redaction_latency,
        "alerts": alerts,
        "oldest_pending_inbox_age_ms": age(now_ms, inbox_oldest),
        "oldest_indeterminate_age_ms": age(now_ms, unknown_oldest),
        "recovery": recovery,
        "recovery_failures": recovery_failures,
        "recovery_attempts_lifetime": recovery_attempts,
        "selected_event": selected_event,
        "admission": (
            "blocked_at_unresolved_capacity"
            if unresolved >= capacity
            else "capacity_available_not_authorization"
        ),
        "selected": selected,
        "not_in_snapshot": list(UNMEASURED),
        "authority_granted": False,
    }


def inspect(
    path: Path,
    now_ms: int,
    capacity: int = 4096,
    transaction: str | None = None,
    event: str | None = None,
) -> dict:
    absolute = path.absolute()
    if absolute.is_symlink() or not absolute.is_file() or absolute.resolve() != absolute:
        raise ValueError("canonical regular database required")
    started = time.monotonic()
    calls = 0

    def budget():
        nonlocal calls
        calls += 1
        return int(calls > 20_000 or time.monotonic() - started > 2)

    db = sqlite3.connect(absolute.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(budget, 1000)
        db.execute("BEGIN")
        return diagnose(db, now_ms, capacity, transaction, event)
    finally:
        db.close()


def prometheus(row: dict) -> str:
    lines = []
    for metric, key in (
        ("outbox", "outbox"),
        ("dispatch", "dispatch"),
        ("active_claims", "active_claims"),
        ("failure_events_last_300s", "failures_last_300s"),
        ("inbox_recovery", "recovery"),
        ("inbox_recovery_failures", "recovery_failures"),
    ):
        for state, value in row[key].items():
            lines.append(f'hepta_matrix_{metric}{{state="{state}"}} {value}')
    for key in (
        "unresolved",
        "unresolved_legacy_holds",
        "parked_queue",
        "expired_claims",
        "sync_checkpoint_age_ms",
        "oldest_queue_age_ms",
        "oldest_parked_age_ms",
        "oldest_expired_claim_age_ms",
        "redaction_propagation_max_last_300s_ms",
        "oldest_pending_inbox_age_ms",
        "oldest_indeterminate_age_ms",
        "recovery_attempts_lifetime",
    ):
        value = row[key]
        lines.append(f"hepta_matrix_{key}_available {int(value is not None)}")
        if value is not None:
            lines.append(f"hepta_matrix_{key} {value}")
    for alert in row["alerts"]:
        lines.append(
            f'hepta_matrix_alert{{code="{alert["code"]}",'
            f'severity="{alert["severity"]}"}} 1'
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--transaction")
    parser.add_argument("--event")
    parser.add_argument("--capacity", type=int, default=4096)
    parser.add_argument("--format", choices=("json", "prometheus"), default="json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        row = inspect(
            args.database,
            time.time_ns() // 1_000_000,
            args.capacity,
            args.transaction,
            args.event,
        )
        print(
            json.dumps(row, indent=2, sort_keys=True)
            if args.format == "json"
            else prometheus(row),
            end="\n",
        )
        severity = max(
            ({"warning": 1, "critical": 2}[alert["severity"]] for alert in row["alerts"]),
            default=0,
        )
        return severity if args.check else 0
    except (OSError, ValueError, sqlite3.Error):
        print(
            json.dumps(
                {
                    "schema": "hepta.channel-matrix-diagnostics.v1",
                    "status": "unavailable",
                    "authority_granted": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
