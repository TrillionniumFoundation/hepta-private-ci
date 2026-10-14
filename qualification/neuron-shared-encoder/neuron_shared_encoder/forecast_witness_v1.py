"""Offline E4 detached Ed25519 forecast-witness authenticity probe.

This module verifies signatures against a caller-supplied, separately pinned
public key. It does NOT establish who controls the key, the trustworthiness of
an asserted time, an independent append-only timestamp, or production final-use.
Do not interpret its result as a causal NDU, Selector, or release receipt.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from .prequential_receipts import input_digest, prequential_chain_audit

DOMAIN = b'hepta.neuron.forecast-witness.v1\x00'
SCHEMA = 'hepta.neuron.forecast-witness.v1'
MAX_FORECAST_PAIRS = 4096
SIGNATURE_FIELD = 'signature_ed25519_hex'


def _valid_digest(v: Any) -> bool:
    return isinstance(v, str) and len(v) == 64 and all(c in '0123456789abcdef' for c in v) and v != '0' * 64


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('witness time requires bounded timezone-aware ISO-8601 text')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid signed witness time claim') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('signed witness time requires timezone')
    return dt.astimezone(timezone.utc)


def canonical_witness_message(unsigned: dict) -> bytes:
    """Domain-separated exact signed bytes; excludes signature entirely."""
    if not isinstance(unsigned, dict) or SIGNATURE_FIELD in unsigned:
        raise ValueError('witness signing payload must exclude signature')
    try:
        raw = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('witness signing payload is not canonical JSON') from exc
    return DOMAIN + raw


def verify_forecast_witnesses(rows: list[dict], dataset_digest: str,
                              frozen_no_change: dict, candidate: dict,
                              event_log: dict, witness_bundle: dict,
                              operator_pinned_public_key: bytes) -> dict:
    """Validate one detached signature per pre-outcome pair of future forecasts.

    The public key is supplied OUT OF BAND, never accepted from witness_bundle.
    A real verifier must independently decide if this key belongs to a trusted
    time-witness issuer and prove the issuer's clock/ledger. Not done here.
    """
    chain = prequential_chain_audit(rows, dataset_digest, frozen_no_change, candidate, event_log)
    if not isinstance(operator_pinned_public_key, bytes) or len(operator_pinned_public_key) != 32:
        raise ValueError('separately pinned Ed25519 public key must be exactly 32 bytes')
    key_fingerprint = hashlib.sha256(operator_pinned_public_key).hexdigest()
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        public_key = Ed25519PublicKey.from_public_bytes(operator_pinned_public_key)
    except ValueError as exc:
        raise ValueError('invalid Ed25519 public key') from exc

    future_rows = {row['row_id']: row for row in rows if row.get('split') == 'future'}
    if not 1 <= len(future_rows) <= MAX_FORECAST_PAIRS:
        raise ValueError('future row count outside witness bound')
    if not isinstance(witness_bundle, dict) or set(witness_bundle) != {'schema', 'receipts'}:
        raise ValueError('invalid closed witness bundle schema')
    if witness_bundle['schema'] != SCHEMA or not isinstance(witness_bundle['receipts'], list):
        raise ValueError('invalid witness schema/version')
    if len(witness_bundle['receipts']) != len(future_rows):
        raise ValueError('exactly one witness receipt per future row required')
    forecast_by_row: dict[str, list[dict]] = {key: [] for key in future_rows}
    outcomes: dict[str, dict] = {}
    for ev in event_log['events']:
        if ev['kind'] == 'forecast':
            forecast_by_row[ev['row_id']].append(ev)
        elif ev['kind'] == 'outcome':
            outcomes[ev['row_id']] = ev
    witnessed_rows: set[str] = set()
    EXPECTED_FIELDS = {
        'schema', 'dataset_sha256', 'cell_scope', 'row_id', 'source_group',
        'input_digest', 'generation', 'authority_epoch', 'first_forecast_seq',
        'first_forecast_digest', 'second_forecast_seq', 'second_forecast_digest',
        'witness_claimed_at', 'public_key_sha256', SIGNATURE_FIELD,
    }
    for receipt in witness_bundle['receipts']:
        if not isinstance(receipt, dict) or set(receipt) != EXPECTED_FIELDS:
            raise ValueError('witness must contain only exact supported fields')
        row_id = receipt['row_id']
        if not isinstance(row_id, str) or row_id not in future_rows or row_id in witnessed_rows:
            raise ValueError('missing, unexpected or duplicate witness row ID')
        witnessed_rows.add(row_id)
        first, second = forecast_by_row[row_id]
        outcome = outcomes[row_id]
        row = future_rows[row_id]
        if (receipt['schema'] != SCHEMA or receipt['dataset_sha256'] != dataset_digest
                or receipt['cell_scope'] != event_log['cell_scope']
                or receipt['source_group'] != row['source_group']
                or receipt['input_digest'] != input_digest(row)
                or type(receipt['generation']) is not int
                or type(receipt['authority_epoch']) is not int
                or receipt['generation'] != chain['generation']
                or receipt['authority_epoch'] != chain['authority_epoch']
                or type(receipt['first_forecast_seq']) is not int
                or type(receipt['second_forecast_seq']) is not int
                or receipt['first_forecast_seq'] != first['seq']
                or receipt['second_forecast_seq'] != second['seq']
                or receipt['first_forecast_digest'] != first['event_digest']
                or receipt['second_forecast_digest'] != second['event_digest']
                or receipt['first_forecast_seq'] >= receipt['second_forecast_seq']
                or receipt['public_key_sha256'] != key_fingerprint):
            raise ValueError('witness not bound to pinned input/scope/forecast chain/key')
        # This is only a chronological claim *signed by a key of unknown trust*.
        observed = _time(receipt['witness_claimed_at'])
        if not (_time(second['recorded_at']) <= observed < _time(row['event_time'])
                and observed < _time(outcome['recorded_at'])):
            raise ValueError('signed witness time claim is inconsistent with event sequence')
        signature_hex = receipt[SIGNATURE_FIELD]
        if (not isinstance(signature_hex, str) or len(signature_hex) != 128
                or any(ch not in '0123456789abcdef' for ch in signature_hex)):
            raise ValueError('invalid bounded Ed25519 signature encoding')
        unsigned = {k: v for k, v in receipt.items() if k != SIGNATURE_FIELD}
        try:
            public_key.verify(bytes.fromhex(signature_hex), canonical_witness_message(unsigned))
        except (InvalidSignature, ValueError) as exc:
            raise ValueError('detached Ed25519 witness signature failed') from exc
    if witnessed_rows != set(future_rows):
        raise ValueError('witness receipts do not cover all future rows')
    return {
        'experiment': 'E4_DETACHED_ED25519_WITNESS_PROBE',
        'status': 'SIGNATURES_VALID_CLOCK_AND_ISSUER_UNVERIFIED',
        'verified_forecast_pairs': len(witnessed_rows),
        'public_key_sha256': key_fingerprint,
        'cryptographic_signature_valid_for_supplied_key': True,
        'independent_key_authority_verified': False,
        'independent_timestamp_witness_verified': False,
        'prediction_before_label_independently_verified': False,
        'causal_learning_verified': False, 'ndu_verified': False,
        'production_admission': 'BLOCKED',
        'warning': ('A detached signature proves only that the specified key signed the supplied '
                    'message. It does not establish issuer independence, real-world signing '
                    'time, data-use authority or trusted NDU.'),
    }
