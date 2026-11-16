#!/usr/bin/env python3
"""Versioned bounded physical tensor identity, independent of file metadata.

A shared helper for label-free forecast reuse and post-outcome review.
Neither the hash nor any caller grants model loading or effect authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from matched_train import unique_json, require

MAX_MODEL_BYTES = 8 << 20


def _frame(part: bytes) -> bytes:
    return len(part).to_bytes(8, 'big') + part


def canonical_tensor_sha(path: Path, expected_sha256: str | None = None) -> str:
    """Bind exact named tensor bytes, dtype and shape; ignore safetensors metadata.

    The caller separately enforces the complete admissible tensor schema and
    pinned file SHA (e.g. candidate_inventory.verify_artifact). This helper
    refuses physical changes during fingerprinting and a changed expected SHA.
    """
    require(not path.is_symlink() and not path.parent.is_symlink(),
            'symlinked physical model in tensor identity')
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
            'physical model changed during tensor fingerprint read')
    require(10 <= len(data) <= MAX_MODEL_BYTES, 'invalid physical model size')
    if expected_sha256 is not None:
        require(hashlib.sha256(data).hexdigest() == expected_sha256,
                'physical model changed after pinned receipt audit')
    header_len = int.from_bytes(data[:8], 'little')
    require(2 <= header_len <= (1 << 20) and 8+header_len <= len(data),
            'invalid safetensors header length')
    header = unique_json(data[8:8+header_len])
    require(type(header) is dict, 'invalid safetensors tensor dictionary')
    header.pop('__metadata__', None)
    require(header, 'missing physical tensors')
    payload = memoryview(data)[8+header_len:]
    h = hashlib.sha256(b'hepta.neuron.canonical-physical-tensors.v1\x00')
    spans = []
    for name in sorted(header):
        row = header[name]
        require(type(row) is dict and set(row) == {'dtype','shape','data_offsets'},
                'invalid exact physical tensor metadata')
        dtype, shape, offsets = row['dtype'],row['shape'],row['data_offsets']
        require(type(name) is str and type(dtype) is str and
                type(shape) is list and type(offsets) is list and len(offsets)==2 and
                all(type(v) is int and v >= 0 for v in shape+offsets),
                'invalid exact physical tensor descriptor')
        a,b = offsets
        require(a < b <= len(payload), 'physical tensor byte offsets out of bounds')
        spans.append((a,b))
        for token in (name.encode(),dtype.encode(),
                      json.dumps(shape,separators=(',',':')).encode(),bytes(payload[a:b])):
            h.update(_frame(token))
    end = 0
    for a,b in sorted(spans):
        require(a == end, 'physical tensor byte overlap or gap')
        end = b
    require(end == len(payload), 'unclaimed physical tensor bytes')
    return h.hexdigest()
