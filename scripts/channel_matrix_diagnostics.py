#!/usr/bin/env python3
"""Bounded read-only Matrix diagnostics. No repair, send or authority operation."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

MAX_I64 = 2**63 - 1
SCHEMA_VERSION = 12
OUTBOX = ('pending', 'in_flight', 'retry_scheduled', 'sent', 'permanent_failure')
LEDGER = ('dispatched', 'accepted', 'indeterminate', 'succeeded',
          'observed_unqualified', 'failed', 'redacted')
PHASES = ('claimed', 'authorized', 'dispatching')
FAILURES = ('retryable', 'rate_limited', 'dns', 'tls', 'connect_timeout',
            'connect_failure', 'read_timeout', 'connection_reset', 'response_lost',
            'server_unavailable', 'permanent', 'authority_denied')
UNMEASURED = ('live_authority_freshness', 'redaction_propagation_latency',
              'supervisor_restarts', 'encrypted_session_continuity')


def grouped(db: sqlite3.Connection, query: str, allowed: tuple[str, ...], args=()) -> dict:
    result = dict.fromkeys(allowed, 0)
    for key, count in db.execute(query, args):
        if key not in result:
            raise ValueError('unsupported durable state')
        result[key] = count
    return result


def age(now: int, timestamp: int | None) -> int | None:
    if timestamp is None:
        return None
    if timestamp > now or timestamp < 0:
        raise ValueError('clock precedes durable observation')
    return now - timestamp


def diagnose(db: sqlite3.Connection, now_ms: int, capacity: int = 4096,
             transaction: str | None = None) -> dict:
    if type(now_ms) is not int or not 0 <= now_ms <= MAX_I64:
        raise ValueError('invalid observation time')
    if type(capacity) is not int or not 1 <= capacity <= 1_000_000:
        raise ValueError('invalid capacity policy')
    if transaction is not None and not 1 <= len(transaction.encode()) <= 512:
        raise ValueError('invalid transaction identity')
    versions = db.execute('SELECT version, success FROM _sqlx_migrations ORDER BY version').fetchall()
    if versions != [(version, 1) for version in range(1, SCHEMA_VERSION + 1)]:
        raise ValueError('unsupported or incomplete migration history')
    # All SQL identifiers are fixed source literals, not user input.
    outbox = grouped(db, 'SELECT state, count(*) FROM outbox_messages GROUP BY state', OUTBOX)
    ledger = grouped(db, 'SELECT state, count(*) FROM matrix_dispatch_ledger GROUP BY state', LEDGER)
    claims = grouped(db, 'SELECT phase, count(*) FROM matrix_dispatch_active_claims GROUP BY phase', PHASES)
    failures = grouped(db, '''SELECT failure_class, count(*) FROM matrix_dispatch_attempt_events
        WHERE recorded_at_ms >= ? AND recorded_at_ms <= ? AND failure_class IS NOT NULL
        GROUP BY failure_class''', FAILURES, (max(0, now_ms - 300_000), now_ms))
    checkpoint = db.execute('SELECT updated_at_ms FROM matrix_sync_checkpoint WHERE singleton=1').fetchone()
    sync_age = age(now_ms, checkpoint[0] if checkpoint else None)
    oldest = db.execute("SELECT min(created_at_ms) FROM outbox_messages WHERE state IN ('pending','in_flight','retry_scheduled')").fetchone()[0]
    oldest_age = age(now_ms, oldest)
    expired = db.execute('SELECT count(*) FROM matrix_dispatch_active_claims WHERE lease_until_ms <= ?', (now_ms,)).fetchone()[0]
    holds = db.execute('''SELECT count(*) FROM matrix_dispatch_legacy_content_holds h
        JOIN matrix_dispatch_ledger d USING(stable_txn_id)
        WHERE d.state IN ('dispatched','accepted','indeterminate')''').fetchone()[0]
    parked = db.execute('''SELECT count(*) FROM outbox_messages
        WHERE state IN ('pending','in_flight','retry_scheduled') AND next_attempt_at_ms=?''', (MAX_I64,)).fetchone()[0]
    unresolved = sum(ledger[state] for state in LEDGER[:3])
    pending = sum(outbox[state] for state in OUTBOX[:3])
    alerts = []
    if unresolved >= capacity:
        alerts.append({'code': 'unresolved_capacity', 'severity': 'critical', 'action': 'stop_admission_preserve_evidence'})
    elif unresolved * 5 >= capacity * 4:
        alerts.append({'code': 'unresolved_capacity', 'severity': 'warning', 'action': 'plan_authenticated_retention'})
    if pending and (sync_age is None or sync_age >= 120_000):
        alerts.append({'code': 'sync_checkpoint_stale', 'severity': 'critical', 'action': 'inspect_sync_no_new_transaction'})
    if oldest_age is not None and oldest_age >= 300_000:
        alerts.append({'code': 'queue_age', 'severity': 'warning', 'action': 'inspect_owner_and_reconciliation'})
    if expired:
        alerts.append({'code': 'expired_claims', 'severity': 'warning', 'action': 'inspect_process_lease_never_edit_claim'})
    selected = None
    if transaction is not None:
        row = db.execute('''SELECT o.state, d.state, o.attempts, o.next_attempt_at_ms,
            EXISTS(SELECT 1 FROM matrix_dispatch_legacy_content_holds h WHERE h.stable_txn_id=o.stable_txn_id),
            EXISTS(SELECT 1 FROM matrix_dispatch_use_entries u WHERE u.stable_txn_id=o.stable_txn_id)
            FROM outbox_messages o LEFT JOIN matrix_dispatch_ledger d USING(stable_txn_id)
            WHERE o.stable_txn_id=?''', (transaction,)).fetchone()
        if row is None:
            selected = {'reason': 'not_found'}
        else:
            queue, state, attempts, next_ms, held, entered = row
            if queue not in OUTBOX or state not in (*LEDGER, None):
                raise ValueError('unsupported selected state')
            terminal = state in ('succeeded', 'observed_unqualified', 'failed', 'redacted')
            if terminal:
                reason, retry = 'terminal_observed', 'not_applicable'
            elif held:
                reason, retry = 'legacy_hold_requires_authenticated_reconciliation', 'forbidden'
            elif next_ms == MAX_I64:
                reason, retry = 'parked_requires_authenticated_reconciliation', 'forbidden'
            elif state in ('accepted', 'indeterminate'):
                reason, retry = 'remote_result_not_yet_reconciled', 'owner_policy_same_transaction_only'
            else:
                reason, retry = 'pending_owner_execution', 'owner_policy_only'
            selected = {'queue_state': queue, 'dispatch_state': state, 'attempts': attempts,
                        'entered_evidence_exists': bool(entered), 'reason': reason, 'retry': retry}
    return {'schema': 'hepta.channel-matrix-diagnostics.v1', 'observed_at_ms': now_ms,
            'scope': 'read_only_durable_snapshot_not_authority_or_native_integrity_proof',
            'schema_version': SCHEMA_VERSION, 'capacity_policy': capacity,
            'outbox': outbox, 'dispatch': ledger, 'active_claims': claims,
            'failures_last_300s': failures, 'unresolved': unresolved,
            'unresolved_legacy_holds': holds, 'parked_queue': parked,
            'expired_claims': expired, 'sync_checkpoint_age_ms': sync_age,
            'oldest_queue_age_ms': oldest_age, 'alerts': alerts,
            'admission': ('blocked_at_unresolved_capacity' if unresolved >= capacity
                          else 'capacity_available_not_authorization'),
            'selected': selected, 'not_in_snapshot': list(UNMEASURED), 'authority_granted': False}


def inspect(path: Path, now_ms: int, capacity: int = 4096, transaction: str | None = None) -> dict:
    absolute = path.absolute()
    if absolute.is_symlink() or not absolute.is_file() or absolute.resolve() != absolute:
        raise ValueError('canonical regular database required')
    started = time.monotonic()
    calls = 0
    def budget():
        nonlocal calls
        calls += 1
        return int(calls > 20_000 or time.monotonic() - started > 2)
    # Never use immutable=1: it would ignore a live WAL and can report stale truth.
    db = sqlite3.connect(absolute.as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(budget, 1000)
        db.execute('BEGIN')
        return diagnose(db, now_ms, capacity, transaction)
    finally:
        db.close()


def prometheus(row: dict) -> str:
    lines = []
    for metric, key in (('outbox', 'outbox'), ('dispatch', 'dispatch'), ('active_claims', 'active_claims'),
                        ('failure_events_last_300s', 'failures_last_300s')):
        for state, value in row[key].items():
            lines.append(f'hepta_matrix_{metric}{{state="{state}"}} {value}')
    for key in ('unresolved', 'unresolved_legacy_holds', 'parked_queue', 'expired_claims',
                'sync_checkpoint_age_ms', 'oldest_queue_age_ms'):
        value = row[key]
        lines.append(f'hepta_matrix_{key}_available {int(value is not None)}')
        if value is not None:
            lines.append(f'hepta_matrix_{key} {value}')
    for alert in row['alerts']:
        lines.append(f'hepta_matrix_alert{{code="{alert["code"]}",severity="{alert["severity"]}"}} 1')
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--transaction')
    parser.add_argument('--capacity', type=int, default=4096)
    parser.add_argument('--format', choices=('json', 'prometheus'), default='json')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        row = inspect(args.database, time.time_ns() // 1_000_000, args.capacity, args.transaction)
        print(json.dumps(row, indent=2, sort_keys=True) if args.format == 'json' else prometheus(row), end='\n')
        severity = max(({'warning': 1, 'critical': 2}[a['severity']] for a in row['alerts']), default=0)
        return severity if args.check else 0
    except (OSError, ValueError, sqlite3.Error):
        # Paths, payloads and SQLite exception text are intentionally not logged.
        print(json.dumps({'schema': 'hepta.channel-matrix-diagnostics.v1',
                          'status': 'unavailable', 'authority_granted': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
