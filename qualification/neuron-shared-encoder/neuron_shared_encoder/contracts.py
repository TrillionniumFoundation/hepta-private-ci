"""Bounded, fail-closed dataset and shared feature contracts for qualification only.

The cache has no authority to authorize a caller. Its key *must* contain the
already-admitted scope, generation, artifact identities and source digest. Nothing
in this module is a production effect-authorizer or an NDU evaluator.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SPLITS = frozenset({'train', 'validation', 'future', 'ood'})
MAX_BYTES = 10 * 1024 * 1024


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _datetime(s: str) -> datetime:
    if not isinstance(s, str):
        raise ValueError('event_time must be an ISO-8601 timestamp')
    value = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('naive event time rejected')
    return value.astimezone(timezone.utc)


def _record(obj: Any, line: int, width: int | None) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f'line {line}: object expected')
    required = ('row_id', 'source_group', 'event_time', 'split', 'principal',
                'organ_id', 'cell_id', 'state', 'question', 'options', 'label')
    for k in required:
        if k not in obj:
            raise ValueError(f'line {line}: missing {k}')
    for k in ('row_id', 'source_group', 'principal', 'organ_id', 'cell_id', 'question'):
        if not isinstance(obj[k], str) or not obj[k] or len(obj[k]) > 256:
            raise ValueError(f'line {line}: invalid {k}')
    if not isinstance(obj['state'], (str, dict, list)):
        raise ValueError(f'line {line}: invalid state')
    if obj['split'] not in SPLITS:
        raise ValueError(f'line {line}: invalid split')
    if not isinstance(obj['options'], list) or not 2 <= len(obj['options']) <= 16:
        raise ValueError(f'line {line}: options must contain 2..16 choices')
    if any(not isinstance(x, str) or not x or len(x) > 512 for x in obj['options']):
        raise ValueError(f'line {line}: empty or oversized option')
    if len(set(obj['options'])) != len(obj['options']):
        raise ValueError(f'line {line}: duplicate option')
    if width is not None and len(obj['options']) != width:
        raise ValueError(f'line {line}: variable class width is not supported by these heads')
    if type(obj['label']) is not int or not 0 <= obj['label'] < len(obj['options']):
        raise ValueError(f'line {line}: label must be an in-range integer')
    _datetime(obj['event_time'])
    return obj


def load_dataset(path: str | Path, *, expected_sha256: str | None = None,
                 max_bytes: int = MAX_BYTES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    p = Path(path)
    size = p.stat().st_size
    if size == 0 or size > max_bytes:
        raise ValueError('empty or oversized dataset')
    digest = sha256_file(p)
    if expected_sha256 is not None and expected_sha256 != digest:
        raise ValueError('dataset digest mismatch')
    seen_ids: set[str] = set()
    group_splits: dict[tuple[str, str], str] = {}
    timestamps: dict[str, list[datetime]] = {s: [] for s in SPLITS}
    rows: list[dict[str, Any]] = []
    width: int | None = None
    with p.open(encoding='utf-8') as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            row = _record(json.loads(raw), line_no, width)
            width = len(row['options'])
            if row['row_id'] in seen_ids:
                raise ValueError(f'line {line_no}: duplicate row id')
            seen_ids.add(row['row_id'])
            # Source group leakage across any train/validation/future/OOD split forbidden,
            # independent of whether row IDs or cell IDs differ.
            group_key = (row['principal'], row['source_group'])
            previous = group_splits.setdefault(group_key, row['split'])
            if previous != row['split']:
                raise ValueError('source group leaked across splits')
            timestamps[row['split']].append(_datetime(row['event_time']))
            rows.append(row)
    for split in SPLITS:
        if not timestamps[split]:
            raise ValueError(f'missing split: {split}')
    if min(timestamps['future']) <= max(timestamps['train'] + timestamps['validation']):
        raise ValueError('future window overlaps train/validation time')
    return rows, {'dataset_sha256': digest, 'rows': len(rows), 'width': width,
                  'split_counts': {s: len(timestamps[s]) for s in sorted(SPLITS)}}


@dataclass(frozen=True)
class FeatureKey:
    principal: str
    purpose: str
    source_digest: str
    encoder_digest: str
    tokenizer_digest: str
    preprocessor_digest: str
    input_digest: str
    effective_bundle_digest: str
    generation: int
    authority_epoch: int

    def __post_init__(self) -> None:
        for field in ('source_digest', 'encoder_digest', 'tokenizer_digest',
                      'preprocessor_digest', 'input_digest', 'effective_bundle_digest'):
            s = getattr(self, field)
            if not isinstance(s, str) or len(s) != 64 or any(c not in '0123456789abcdef' for c in s):
                raise ValueError(f'invalid SHA256: {field}')
        if not self.principal or not self.purpose:
            raise ValueError('missing scope')
        if self.generation <= 0 or self.authority_epoch <= 0:
            raise ValueError('invalid generation/epoch')


class ImmutableFeatureCache:
    """Admission-scoped in-process read cache, not an authorization cache.

    Caller must recheck live source eligibility, revocation, and authority before
    calling get. A TTL is not equivalent to grant validity. Entries are tuples,
    never writable views into an encoder's output. Bounded by item count and bytes.
    """
    def __init__(self, max_items: int = 1024, max_bytes: int = 8 * 1024 * 1024,
                 ttl_ticks: int = 10):
        if min(max_items, max_bytes, ttl_ticks) <= 0:
            raise ValueError('capacity/TTL must be positive')
        self.max_items = max_items
        self.max_bytes = max_bytes
        self.ttl_ticks = ttl_ticks
        self.items: OrderedDict[FeatureKey, tuple[tuple[float, ...], int, int]] = OrderedDict()
        self.bytes = 0
        self.hits = 0
        self.misses = 0

    def get(self, key: FeatureKey, tick: int, *, admitted: bool = False) -> tuple[float, ...] | None:
        if not admitted:
            raise PermissionError('fresh independent admission required')
        if tick < 0:
            raise ValueError('invalid clock')
        v = self.items.get(key)
        if v is None:
            self.misses += 1
            return None
        data, expires, item_size = v
        if tick >= expires:
            del self.items[key]
            self.bytes -= item_size
            self.misses += 1
            return None
        self.items.move_to_end(key)
        self.hits += 1
        return data

    def put(self, key: FeatureKey, tensor: Any, tick: int,
            *, admitted: bool = False) -> None:
        if not admitted:
            raise PermissionError('fresh independent admission required')
        if tick < 0:
            raise ValueError('invalid clock')
        data = tuple(float(x) for x in tensor)
        if not data or any(not math.isfinite(x) for x in data):
            raise ValueError('invalid feature values')
        item_size = len(data) * 8
        if item_size > self.max_bytes:
            raise ValueError('feature exceeds cache budget')
        prev = self.items.pop(key, None)
        if prev:
            self.bytes -= prev[2]
        while self.items and (len(self.items) >= self.max_items or self.bytes + item_size > self.max_bytes):
            _, old = self.items.popitem(last=False)
            self.bytes -= old[2]
        self.items[key] = (data, tick + self.ttl_ticks, item_size)
        self.bytes += item_size

    def invalidate_scope(self, principal: str, minimum_epoch: int) -> int:
        """Remove old authority epochs on revocation / fenced restart."""
        removed = 0
        for key in list(self.items):
            if key.principal == principal and key.authority_epoch < minimum_epoch:
                self.bytes -= self.items.pop(key)[2]
                removed += 1
        return removed


def evidence_gate(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """No benchmark file can grant production promotion authority."""
    required = ('source_commit', 'model_artifact_digest', 'dataset_digest',
                'split_manifest_digest', 'hardware_receipt', 'baseline_receipt',
                'independent_evaluator_receipt', 'ndu_receipt',
                'future_window_receipt', 'negative_transfer_receipt',
                'recovery_receipt', 'final_use_authorization')
    found = evidence if isinstance(evidence, dict) else {}
    missing = [name for name in required if not found.get(name)]
    return {'status': 'BLOCKED', 'missing': missing, 'required': list(required),
            'reason': ('Independent signature, issuer authority, revocation, final-use and '
                       'artifact CAS checks cannot be established by this harness. '
                       'Receipt field presence never authorizes deployment.')}
