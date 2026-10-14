#!/usr/bin/env python3
"""Inspect the *physical* private five-arm safetensors inventory, without promotion.

This is a closed-world research artifact format, not a production native model
loader, signature verifier or a claim of Q24 execution equivalence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
from typing import Any

Q = 1 << 24
MAX_MODEL_BYTES = 8 << 20
MAX_HEADER_BYTES = 1 << 20
HEX = set('0123456789abcdef')
DTYPE_BYTES = {'F32': 4, 'I64': 8}


def require(ok: bool, explanation: str) -> None:
    if not ok:
        raise ValueError(explanation)


def unique_json(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for name, value in items:
            require(name not in result, 'duplicate safetensors header field')
            result[name] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid physical safetensors header') from exc
    require(type(value) is dict, 'safetensors header must be an object')
    return value


def expected_geometry(arm: str, width: int, rank: int | None) -> dict[str, tuple[str, tuple[int, ...]]]:
    require(type(width) is int and 5 <= width <= 256, 'invalid frozen Cell width')
    expected = {
        'structure.projection': ('I64', (width,)),
        'head.weight': ('F32', (1, width)),
        'head.bias': ('F32', (1,)),
    }
    if arm == 'v2':
        require(rank is None, 'V2 has no low-rank temporal rank')
    elif arm == 'v3':
        require(rank is None, 'V3 has no low-rank temporal rank')
        for name in ('gate_bias', 'input_gain', 'change_gain'):
            expected['temporal.' + name] = ('I64', (width,))
    elif arm == 'ssm':
        require(rank is None, 'SSM has no low-rank temporal rank')
        for name in ('decay_per_step', 'input_gain'):
            expected['temporal.' + name] = ('I64', (width,))
    elif arm == 'min_gru':
        require(type(rank) is int and 1 <= rank <= width, 'invalid minGRU rank')
        for name, shape in {
            'gate_input': (rank, width), 'gate_output': (width, rank),
            'candidate_input': (rank, width), 'candidate_output': (width, rank),
            'gate_bias': (width,), 'candidate_bias': (width,),
        }.items():
            expected['temporal.' + name] = ('I64', shape)
    else:
        raise ValueError('unknown experimental Cell arm')
    return expected


def verify_artifact(path: Path, expected_sha256: str, *, arm: str,
                    width: int, rank: int | None, expected_count: int) -> dict[str, Any]:
    """Reopen one physical artifact and inspect geometry, values and exact bytes.

    Caller pins expected SHA and Cell shape in a separate receipt. It is not a
    verifier for the independent training history, owner or host.
    """
    path = Path(path)
    require(type(expected_sha256) is str and len(expected_sha256) == 64
            and expected_sha256 != '0' * 64 and all(c in HEX for c in expected_sha256),
            'untrusted candidate artifact digest')
    require(not path.is_symlink() and not path.parent.is_symlink(), 'symlinked candidate file/directory')
    geometry = expected_geometry(arm, width, rank)
    require(type(expected_count) is int and 0 < expected_count <= 262144,
            'invalid expected private parameter count')
    flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and 8 < before.st_size <= MAX_MODEL_BYTES,
                'invalid physical candidate file/size')
        raw = handle.read(MAX_MODEL_BYTES + 1)
        after = os.fstat(handle.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'candidate file changed while inspected')
    require(len(raw) == before.st_size and len(raw) <= MAX_MODEL_BYTES,
            'short or oversized artifact read')
    require(hashlib.sha256(raw).hexdigest() == expected_sha256,
            'physical candidate SHA256 mismatch')
    header_size = int.from_bytes(raw[:8], 'little')
    require(2 <= header_size <= MAX_HEADER_BYTES and header_size <= len(raw)-8,
            'malformed safetensors header length')
    header = unique_json(raw[8:8+header_size])
    metadata = header.pop('__metadata__', None)
    if metadata is not None:
        require(type(metadata) is dict and all(type(k) is str and type(v) is str
                                                for k, v in metadata.items()),
                'invalid safetensors metadata')
    require(set(header) == set(geometry), 'missing or unexpected physical tensor')
    data = memoryview(raw)[8+header_size:]
    ranges = []
    counted = 0
    for name, (dtype, shape) in geometry.items():
        entry = header[name]
        require(type(entry) is dict and set(entry) == {'dtype', 'shape', 'data_offsets'},
                name+': invalid tensor descriptor')
        actual_shape, offsets = entry['shape'], entry['data_offsets']
        require(entry['dtype'] == dtype and type(actual_shape) is list
                and tuple(actual_shape) == shape and all(type(x) is int for x in actual_shape),
                name+': wrong dtype or tensor shape')
        require(type(offsets) is list and len(offsets) == 2
                and all(type(v) is int for v in offsets), name+': invalid byte offsets')
        start, end = offsets
        count = math.prod(shape)
        require(0 <= start < end <= len(data)
                and end - start == count * DTYPE_BYTES[dtype], name+': bad tensor bytes')
        ranges.append((start, end))
        counted += count
        payload = data[start:end]
        if dtype == 'F32':
            require(all(math.isfinite(v[0]) for v in struct.iter_unpack('<f', payload)),
                    name+': NaN or infinity is not a trained weight')
        else:
            values = (v[0] for v in struct.iter_unpack('<q', payload))
            if name == 'structure.projection':
                require(all(v == Q for v in values), 'projection must be the exact frozen Q24 identity')
            elif name in {'temporal.gate_bias', 'temporal.decay_per_step'} and arm in ('v3', 'ssm'):
                require(all(0 <= v <= Q for v in values), name+': native Q24 gate/decay bound')
            else:
                require(all(-Q <= v <= Q for v in values), name+': Q24 parameter out of bounds')
    end_at = 0
    for start, end in sorted(ranges):
        require(start == end_at, 'overlapping, missing, or unclaimed safetensors bytes')
        end_at = end
    require(end_at == len(data), 'unclaimed trailing safetensors bytes')
    require(counted == expected_count, 'physical private parameter count mismatch')
    return {
        'sha256': expected_sha256, 'arm': arm, 'width': width, 'rank': rank,
        'tensor_count': len(geometry), 'private_parameter_count': counted,
        'physical_model_bytes': len(raw),
        'native_q24_parameter_constraints_verified': True,
        'native_q24_prediction_parity_verified': False,
        'production_qualification': False,
    }
