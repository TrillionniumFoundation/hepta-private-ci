"""Exact, object-specific byte-cache contracts; no models or numeric solvers.

The caller must supply an independently authorized payload digest to get().
Integrity against that digest is not proof of numerical correctness. This
single-writer research store is bounded and create-only; incomplete entries
fail closed. It is not a multi-process production cache or durability claim.
"""
from pathlib import Path
import hashlib
import json
import math
import os
import re
import struct

SCHEMA = 'hepta.finite-cache-key.v1'
ENTRY_SCHEMA = 'hepta.finite-cache-entry.v1'
SHA_RE = re.compile(r'^[0-9a-f]{64}$')
MAX_PAYLOAD = 16 * 1024 * 1024
COMMON = {'checkpoint_gzip_sha256', 'checkpoint_decoded_sha256',
          'source_contract_sha256', 'basis_sha256', 'arithmetic_sha256'}
FIELDS = {
    'linear_operator': COMMON | {'generator_sha256', 'duration_f64_le',
                                 'output_contract_sha256'},
    'history_result': COMMON | {'generator_set_sha256', 'initial_joint_sha256',
                                'schedule_sha256', 'action_observation_sha256',
                                'decoder_sha256', 'horizon_intervals'},
}


class CacheRejected(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise CacheRejected('duplicate JSON key')
            value[key] = item
        return value

    def invalid(value):
        raise CacheRejected('nonfinite JSON number: ' + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def typed_bytes(value):
    """Type-tagged JSON; preserve binary64 signed zero and integer/float type."""
    def encode(x):
        if x is None:
            return ['null']
        if type(x) is bool:
            return ['bool', x]
        if type(x) is int:
            return ['int', str(x)]
        if type(x) is float:
            if not math.isfinite(x):
                raise CacheRejected('nonfinite typed value')
            return ['f64le', struct.pack('<d', x).hex()]
        if type(x) is str:
            return ['str', x]
        if type(x) is list or type(x) is tuple:
            return ['list', [encode(a) for a in x]]
        if type(x) is dict and all(type(k) is str for k in x):
            return ['dict', [[k, encode(x[k])] for k in sorted(x)]]
        raise CacheRejected('unsupported typed value')

    return json.dumps(encode(value), ensure_ascii=True, separators=(',', ':'),
                      allow_nan=False).encode('ascii')


def context_key(context):
    if type(context) is not dict or set(context) != {'schema', 'kind', 'bindings'}:
        raise CacheRejected('unknown context schema fields')
    if context['schema'] != SCHEMA or context['kind'] not in FIELDS:
        raise CacheRejected('unsupported cache object')
    bindings = context['bindings']
    if type(bindings) is not dict or set(bindings) != FIELDS[context['kind']]:
        raise CacheRejected('incomplete or unknown identity fields')
    for name, value in bindings.items():
        if name.endswith('_sha256'):
            if type(value) is not str or SHA_RE.fullmatch(value) is None:
                raise CacheRejected('invalid SHA256 field')
        elif name == 'duration_f64_le':
            if type(value) is not str or re.fullmatch('[0-9a-f]{16}', value) is None:
                raise CacheRejected('duration is not exact F64 bits')
            duration = struct.unpack('<d', bytes.fromhex(value))[0]
            if not math.isfinite(duration) or duration < 0:
                raise CacheRejected('invalid duration')
        elif name == 'horizon_intervals':
            if type(value) is not int or not (1 <= value <= 4096):
                raise CacheRejected('invalid finite horizon')
        else:
            raise CacheRejected('unknown identity coordinate')
    return sha(typed_bytes(context))


def context(kind, **bindings):
    value = dict(schema=SCHEMA, kind=kind, bindings=bindings)
    context_key(value)
    return value


def payload_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(',', ':'), allow_nan=False).encode('ascii')


def bounded_read(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise CacheRejected('nonregular or over-budget cache file')
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise CacheRejected('over-budget cache payload')
    return raw


class ContentStore:
    def __init__(self, root):
        self.root = Path(root)
        if self.root.is_symlink():
            raise CacheRejected('symlink cache root')
        self.root.mkdir(exist_ok=True)
        if not self.root.is_dir():
            raise CacheRejected('invalid cache root')

    def put(self, ctx, payload, expected_payload_sha256):
        key = context_key(ctx)
        if type(payload) is not bytes or len(payload) > MAX_PAYLOAD:
            raise CacheRejected('unsupported payload')
        if sha(payload) != expected_payload_sha256:
            raise CacheRejected('payload differs from authorized external pin')
        folder = self.root / key
        folder.mkdir()  # create-only; never overwrite an existing cache entry
        with (folder / 'payload.bin').open('xb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        meta = dict(schema=ENTRY_SCHEMA, context=ctx, context_sha256=key,
                    payload_sha256=expected_payload_sha256, payload_bytes=len(payload))
        with (folder / 'entry.json').open('xb') as handle:
            handle.write(payload_bytes(meta))
            handle.flush()
            os.fsync(handle.fileno())
        # No claim of crash durability: parent directories are not fsynced.
        return key

    def get(self, ctx, expected_payload_sha256):
        key = context_key(ctx)
        if type(expected_payload_sha256) is not str or not SHA_RE.fullmatch(expected_payload_sha256):
            raise CacheRejected('independent expected payload pin is required')
        folder = self.root / key
        if folder.is_symlink():
            raise CacheRejected('symlink entry')
        if not folder.exists():
            return None
        if not folder.is_dir():
            raise CacheRejected('invalid entry directory')
        meta = strict_json(bounded_read(folder / 'entry.json', 64 * 1024))
        if type(meta) is not dict or set(meta) != {'schema', 'context', 'context_sha256',
                                                  'payload_sha256', 'payload_bytes'}:
            raise CacheRejected('unknown entry fields')
        if (meta['schema'] != ENTRY_SCHEMA or meta['context_sha256'] != key
                or context_key(meta['context']) != key
                or typed_bytes(meta['context']) != typed_bytes(ctx)
                or meta['payload_sha256'] != expected_payload_sha256
                or type(meta['payload_bytes']) is not int
                or not 0 <= meta['payload_bytes'] <= MAX_PAYLOAD):
            raise CacheRejected('entry identity mismatch')
        raw = bounded_read(folder / 'payload.bin', MAX_PAYLOAD)
        if len(raw) != meta['payload_bytes'] or sha(raw) != expected_payload_sha256:
            raise CacheRejected('cold-restored payload integrity failure')
        return raw
