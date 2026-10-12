"""Bounded serialized evidence retention; no timing/GC/policy waiver.

The model loop retains immutable JSON bytes rather than each nested trace graph.
Existing JSON array artifacts are emitted verbatim, and decoding is per row.
Serialization and final emission remain inside the study CPU envelope. This is
not a persistent native log: process crash durability is not authenticated.
"""
import hashlib
from pathlib import Path
from four_gate_common import canonical, require, strict_loads

LEGACY = 'retained_objects_v1'
COMPACT = 'serialized_records_v2'
PROFILES = (LEGACY, COMPACT)


class RecordBuffer:
    """Study-scoped immutable byte snapshots with a shared hard allocation budget."""
    def __init__(self, budget, *, max_rows=250_000, max_row_bytes=512*1024):
        require(type(budget) is dict and set(budget) == {'used', 'limit'} and
                type(budget['used']) is int and type(budget['limit']) is int and
                0 <= budget['used'] <= budget['limit'] <= 256*1024*1024,
                'bounded shared record budget')
        require(type(max_rows) is int and 1 <= max_rows <= 250_000 and
                type(max_row_bytes) is int and 1 <= max_row_bytes <= 512*1024,
                'bounded record dimensions')
        self.budget, self.max_rows, self.max_row_bytes = budget, max_rows, max_row_bytes
        self._rows, self.nbytes, self.sealed = [], 0, False

    def append(self, row):
        require(not self.sealed and len(self._rows) < self.max_rows, 'record capacity or sealed')
        raw = canonical(row)
        require(len(raw) <= self.max_row_bytes and
                self.budget['used'] + len(raw) <= self.budget['limit'],
                'record byte budget exhausted')
        self._rows.append(raw)
        self.nbytes += len(raw)
        self.budget['used'] += len(raw)

    def __len__(self):
        return len(self._rows)

    def __iter__(self):
        for raw in self._rows:
            yield strict_loads(raw)

    def write_once(self, path):
        """No whole-stream decoding and no overwrite; partial write is an error."""
        require(not self.sealed, 'record buffer already sealed')
        path = Path(path)
        hasher = hashlib.sha256()
        with path.open('xb') as stream:
            stream.write(b'['); hasher.update(b'[')
            for i, raw in enumerate(self._rows):
                if i:
                    stream.write(b',\n'); hasher.update(b',\n')
                stream.write(raw); hasher.update(raw)
            stream.write(b']\n'); hasher.update(b']\n')
        self.sealed = True
        return {'rows': len(self), 'serialized_payload_bytes': self.nbytes,
                'file_sha256': hasher.hexdigest(), 'native_durability_claimed': False}


def audit_recording(directory):
    """Reconcile saved arrays and retention totals; no model or timing PASS."""
    root = Path(directory)
    plan = strict_loads((root/'plan.json').read_bytes())
    meta = strict_loads((root/'record-retention.json').read_bytes())
    require(meta['profile'] == plan['record_profile'] == COMPACT, 'serialized profile required')
    require(set(meta['streams']) == set(plan['arms']) | {'proposals'}, 'complete record streams')
    used = rows = 0
    for name, expected in meta['streams'].items():
        require('/' not in name and '\\' not in name and name not in ('.', '..'), 'record name')
        path = root/(name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64*1024*1024,
                'bounded regular record artifact')
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected['file_sha256'], 'record byte hash')
        data = strict_loads(raw)
        require(type(data) is list and len(data) == expected['rows'] <= 250_000, 'record count')
        size = sum(len(canonical(row)) for row in data)
        require(size == expected['serialized_payload_bytes'], 'record payload accounting')
        used += size; rows += len(data)
    require(used == meta['retained_payload_bytes'] <= meta['shared_payload_limit_bytes'] <= 256*1024*1024,
            'shared record byte accounting')
    require(type(meta['recording_cpu_ns']) is int and meta['recording_cpu_ns'] >= 0,
            'recording CPU required')
    return {'rows': rows, 'payload_bytes': used, 'streams': len(meta['streams']),
            'array_contract_preserved': True, 'budget_stability_established': False,
            'execution_authenticated': False, 'production_promotion_permitted': False}
