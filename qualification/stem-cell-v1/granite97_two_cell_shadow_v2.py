"""Run two bounded, untrained V1 Cell Heads on reviewed Granite97 Q24 tokens.

Real CPU Head numeric execution; no added Encoder/model forward, optimizer,
semantic labels, authoritative approval or split. Uses the independent V2 bridge.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import struct
import time

from granite97_feature_bridge_v2 import BridgeError, Q24, bridge, read_regular
from multimodal_stem_v1 import CellHead, select_cells


def shadow_two_cells(source: bytes, export: bytes, review: bytes, *, now_ms: int) -> dict:
    state = bridge(source, export, review, now_ms=now_ms)
    raw = state.q24_blob
    width = state.envelope.width
    count = state.envelope.slot_count
    if len(raw) != count * width * 8:
        raise BridgeError('complete Q24 row bound')
    flat = [value[0] for value in struct.iter_unpack('>q', raw)]
    slots = [tuple(flat[j * width + k] / Q24 for k in range(width))
             for j in range(count)]
    # Distinct parameter tensors, fixed and untrained; never a learned outcome.
    head0 = CellHead('cell:axis0', (1.0,) + (0.0,) * (width - 1), 0.0)
    head1 = CellHead('cell:axis1', (0.0, 1.0) + (0.0,) * (width - 2), 0.0)
    before = time.process_time_ns()
    selected = select_cells((head0, head1), slots, top_k=2)
    head_cpu_ns = time.process_time_ns() - before
    if head_cpu_ns <= 0 or len(selected) != 2:
        raise BridgeError('two genuine numerical Cell evaluations required')
    actual = {name: round(value * Q24) for name,value in selected}
    # Independent pure-integer mean proves these two simple selectors consumed
    # the correct ordered Q24 bytes, not an arbitrary float feature object.
    expected = {
        'cell:axis0': round(Fraction(sum(flat[0::width]), count)),
        'cell:axis1': round(Fraction(sum(flat[1::width]), count)),
    }
    if any(abs(actual[k] - expected[k]) > 1 for k in expected):
        raise BridgeError('Q24 Cell numeric verification failed')
    state_digest = hashlib.sha256(json.dumps(actual, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return {
        'schema': 'hepta.stem.granite97-two-cell-shadow.v2',
        'source_sha256': state.replay['source_sha256'],
        'q24_feature_sha256': state.replay['q24_blob_sha256'],
        'independent_review_sha256': state.replay['review_sha256'],
        'feature_envelope_key': state.replay['feature_envelope_key'],
        'parameter_profile': 'fixed-axis-original-q24-v2',
        'score_q24': actual,
        'score_sha256': state_digest,
        'measured_cell_cpu_ns': head_cpu_ns,
        'cell_head_forward_count': 2,
        'bridge_encoder_forward_count': 0,
        'independent_model_issuer_signature_verified': False,
        'cell_parameters_trained': False,
        'task_quality_attested': False,
        'source_disjoint_generalization_attested': False,
        'production_authorized': False,
        'authority': 'DENY_ALL',
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ('source', 'export', 'review', 'output'):
        cli.add_argument('--' + arg, required=True)
    args = cli.parse_args()
    source = read_regular(args.source, 65536)
    export = read_regular(args.export, 2_500_000)
    review = read_regular(args.review, 65536)
    result = shadow_two_cells(source, export, review, now_ms=time.time_ns() // 1_000_000)
    target = Path(args.output)
    if target.exists() or target.is_symlink():
        raise BridgeError('refuse to overwrite prior Cell result')
    with target.open('xb') as out:
        out.write((json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode())
        out.flush()
        os.fsync(out.fileno())

if __name__ == '__main__':
    main()
