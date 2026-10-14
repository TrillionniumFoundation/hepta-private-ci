"""Offline E4 forecast/outcome hash-chain consistency checks (non-authorizing).

A hash chain detects accidental mutation of a frozen byte sequence; its
root, timestamps, actor identity and publication order are NOT independently
witnessed or signed. A forged complete chain can always be recomputed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

DOMAIN = b'hepta.neuron.prequential-shadow.v1\x00'
INPUT_DOMAIN = b'hepta.neuron.prequential-input.v1\x00'
GENESIS = '0' * 64
MAX_EVENTS = 12288


def _digest(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value)
            and value != GENESIS)


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError('timezone-aware timestamps required')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid event timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone-aware timestamps required')
    return parsed.astimezone(timezone.utc)


def input_digest(row: dict) -> str:
    """Bind a forecast to admitted *pre-outcome* question/options/state bytes."""
    payload = {k: row[k] for k in (
        'row_id', 'source_group', 'principal', 'organ_id', 'cell_id',
        'state', 'question', 'options')}
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(INPUT_DOMAIN + raw).hexdigest()


def event_digest(event: dict) -> str:
    """Canonical chain entry, excluding its own digest; not a signature."""
    if not isinstance(event, dict) or 'event_digest' in event:
        raise ValueError('pass event without event_digest for hashing')
    encoded = json.dumps(event, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(DOMAIN + encoded).hexdigest()


def prequential_chain_audit(rows: list[dict], dataset_digest: str,
                            frozen_no_change: dict, candidate: dict,
                            event_log: dict) -> dict:
    """Check chain, scope, model, ordered predictions and future outcomes.

    Claims *internal consistency only*. Real causal verification requires an
    independently trusted timestamp/witness, immutable owner, sealed baseline,
    source entitlements and signed NDU outside this module.
    """
    if not _digest(dataset_digest) or not isinstance(rows, list) or not rows:
        raise ValueError('pinned nonempty dataset required')
    if not isinstance(event_log, dict) or event_log.get('dataset_sha256') != dataset_digest:
        raise ValueError('event-log dataset identity mismatch')
    scope = [rows[0].get(k) for k in ('principal', 'organ_id', 'cell_id')]
    if any(not isinstance(v, str) or not v for v in scope):
        raise ValueError('complete Cell scope required')
    if event_log.get('cell_scope') != scope:
        raise ValueError('event-log Cell scope mismatch')
    if any([r.get(k) for k in ('principal', 'organ_id', 'cell_id')] != scope for r in rows):
        raise ValueError('cross-scope dataset cannot be audited')
    futures = {r['row_id']: (i, r) for i, r in enumerate(rows) if r.get('split') == 'future'}
    if not futures or len(futures) != sum(r.get('split') == 'future' for r in rows):
        raise ValueError('missing or duplicate future row identity')
    events = event_log.get('events')
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise ValueError('invalid bounded event log')
    if len(events) != len(futures) * 3:
        raise ValueError('exactly two forecasts and one outcome per future row required')
    snapshots = {'frozen_no_change': frozen_no_change, 'candidate': candidate}
    for role, snapshot in snapshots.items():
        if (not isinstance(snapshot, dict) or snapshot.get('role') != role
                or snapshot.get('dataset_sha256') != dataset_digest
                or snapshot.get('cell_scope') != scope
                or not _digest(snapshot.get('artifact_digest'))
                or snapshot.get('row_ids') != [r['row_id'] for r in rows]
                or not isinstance(snapshot.get('probabilities'), list)
                or len(snapshot['probabilities']) != len(rows)):
            raise ValueError(f'{role}: frozen snapshot identity/prediction mismatch')
    if frozen_no_change['artifact_digest'] == candidate['artifact_digest']:
        raise ValueError('candidate and frozen no-change artifact must differ')
    prev = GENESIS
    observed: dict[str, dict[str, tuple[int, datetime]]] = {}
    generation = None
    epoch = None
    previous_recorded_at = None
    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError('event object required')
        proof = event.get('event_digest')
        raw = {k: v for k, v in event.items() if k != 'event_digest'}
        if not _digest(proof) or proof != event_digest(raw) or raw.get('previous_digest') != prev:
            raise ValueError('event digest/chain discontinuity')
        prev = proof
        if raw.get('seq') != idx or type(raw.get('seq')) is not int:
            raise ValueError('event sequence out of order')
        if raw.get('dataset_sha256') != dataset_digest or raw.get('cell_scope') != scope:
            raise ValueError('event dataset/Cell scope mismatch')
        g, e = raw.get('generation'), raw.get('authority_epoch')
        if type(g) is not int or g <= 0 or type(e) is not int or e <= 0:
            raise ValueError('invalid generation/authority epoch')
        if generation is None:
            generation, epoch = g, e
        if (g, e) != (generation, epoch):
            raise ValueError('mixed generation or authority epoch')
        row_id = raw.get('row_id')
        if row_id not in futures:
            raise ValueError('unexpected or cross-split row')
        row_index, row = futures[row_id]
        if (raw.get('source_group') != row.get('source_group')
                or raw.get('input_digest') != input_digest(row)):
            raise ValueError('forecast/outcome source and admitted input identity mismatch')
        stamp = _time(raw.get('recorded_at'))
        if previous_recorded_at is not None and stamp < previous_recorded_at:
            raise ValueError('event log clock moved backwards')
        previous_recorded_at = stamp
        per_row = observed.setdefault(row_id, {})
        kind = raw.get('kind')
        if kind == 'forecast':
            role = raw.get('role')
            if role not in snapshots or role in per_row or 'outcome' in per_row:
                raise ValueError('duplicate/late/invalid forecast role')
            snapshot = snapshots[role]
            if raw.get('artifact_digest') != snapshot['artifact_digest']:
                raise ValueError('forecast model digest mismatch')
            expected = snapshot['probabilities'][row_index]
            actual = raw.get('probabilities')
            width = len(row['options'])
            if (not isinstance(expected, list) or not isinstance(actual, list)
                    or len(expected) != width or len(actual) != width
                    or any(type(v) not in (int, float) or not math.isfinite(v)
                           or v < 0 or v > 1 for v in actual)
                    or abs(sum(actual) - 1) > 1e-6
                    or any(type(a) not in (int, float) or not math.isfinite(a)
                           or type(b) not in (int, float) or not math.isfinite(b)
                           or abs(a - b) > 1e-8 for a, b in zip(actual, expected))):
                raise ValueError('forecast probabilities/snapshot mismatch')
            if stamp >= _time(row.get('event_time')):
                raise ValueError('forecast not earlier than future event')
            per_row[role] = (idx, stamp)
        elif kind == 'outcome':
            if 'outcome' in per_row or set(per_row) != set(snapshots):
                raise ValueError('outcome before two distinct forecasts or duplicate outcome')
            if type(raw.get('label')) is not int or raw['label'] != row['label']:
                raise ValueError('outcome label does not match pinned data')
            if stamp < _time(row.get('event_time')):
                raise ValueError('outcome recorded before event time')
            if any(predicted >= stamp for _, predicted in per_row.values()):
                raise ValueError('forecast not earlier than recorded outcome')
            per_row['outcome'] = (idx, stamp)
        else:
            raise ValueError('invalid event type')
    if any(set(observed.get(row_id, {})) != {'frozen_no_change', 'candidate', 'outcome'}
           for row_id in futures):
        raise ValueError('missing forecast/outcome event')
    return {
        'experiment': 'E4_PREQUENTIAL_EVENT_CHAIN',
        'status': 'HASH_CHAIN_CONSISTENT_UNVERIFIED',
        'events_checked': len(events), 'future_rows_checked': len(futures),
        'chain_head_digest': prev, 'generation': generation, 'authority_epoch': epoch,
        'producer_signature_verified': False,
        'independent_timestamp_witness_verified': False,
        'prediction_before_label_independently_verified': False,
        'causal_learning_verified': False, 'ndu_verified': False,
        'production_admission': 'BLOCKED',
        'warning': 'Any actor can recompute this unsigned chain and backdate claimed timestamps.',
    }