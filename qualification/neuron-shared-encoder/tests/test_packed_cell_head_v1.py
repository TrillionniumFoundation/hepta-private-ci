"""Physical Torch batched-head numerical and isolation tests (shadow-only)."""
from __future__ import annotations

import pytest
import torch

from neuron_shared_encoder.packed_cell_head_v1 import (
    PackedCellHeadBankV1, measure_packed_readout,
)
from neuron_shared_encoder.token_reader_v1 import CellHead, snapshot_sha256
from test_token_reader_v1 import sample


def test_batched_computation_parity_same_independent_weights():
    torch.manual_seed(123)
    heads = [(f'cell-{i}', CellHead(12, 4, 2).eval()) for i in range(16)]
    original = [(name, {k: v.detach().clone() for k, v in h.state_dict().items()})
                for name, h in heads]
    packed = PackedCellHeadBankV1(heads)
    tokens, mask, *_ = sample()
    for kind, original_kind in (('pooled_cached', 'pooled_feature_gate'),
                                ('token_query_prepared', 'token_query_gate')):
        source = tokens[0]
        valid = mask[0]
        with torch.inference_mode():
            scalar = torch.cat([h(source.unsqueeze(0), valid.unsqueeze(0), original_kind)
                                for _, h in heads], dim=0)
            batched = packed.execute(source, valid, kind=kind)
        assert batched.shape == (len(heads), 2)
        assert torch.allclose(batched, scalar, atol=1e-5, rtol=1e-5)
    assert packed.head_weight_bytes == sum(p.numel() * p.element_size()
                                            for _, h in heads for p in h.parameters())
    assert len(packed.bank_sha256) == 64
    # Changing currently-selected tensors after load must not change the packed snapshot.
    first = packed.execute(tokens[0], mask[0], kind='pooled_cached').clone()
    with torch.no_grad():
        heads[0][1].query.add_(100)
    assert torch.equal(first, packed.execute(tokens[0], mask[0], kind='pooled_cached'))
    assert original[0][0] == 'cell-0'


def test_negative_inputs_fail_closed():
    h = CellHead(12, 4, 2)
    with pytest.raises(ValueError, match='nonempty Cell'):
        PackedCellHeadBankV1([])
    with pytest.raises(ValueError, match='unique bounded Cell'):
        PackedCellHeadBankV1([('a', h), ('a', CellHead(12, 4, 2))])
    with pytest.raises(ValueError, match='mutable Cell parameter alias'):
        PackedCellHeadBankV1([('a', h), ('b', h)])
    with pytest.raises(ValueError, match='incompatible Cell Head geometry'):
        PackedCellHeadBankV1([('a', h), ('b', CellHead(13, 4, 2))])
    bad = CellHead(12, 4, 2)
    with torch.no_grad(): bad.query[0] = float('nan')
    with pytest.raises(ValueError, match='nonfinite/unsupported'):
        PackedCellHeadBankV1([('a', bad)])
    bank = PackedCellHeadBankV1([('a', h)])
    t, m, *_ = sample()
    with pytest.raises(ValueError, match='compatible token'):
        bank.execute(t[0], torch.zeros_like(m[0]), kind='token_query_prepared')
    with pytest.raises(ValueError, match='compatible token'):
        bank.execute(torch.ones((3, 13)), torch.ones((3,), dtype=torch.bool), kind='pooled_cached')
    with pytest.raises(ValueError, match='unknown packed'):
        bank.execute(t[0], m[0], kind='unknown')


def test_packed_shadow_receipts_no_promotion_or_inferred_true_batch():
    tokens, mask, labels, rows, pins = sample()
    report = measure_packed_readout(tokens, mask, labels, rows, pins,
                                     snapshot_sha256(tokens, mask, rows, pins),
                                     cells=16, rank=4, rounds=2, warmups=1)
    assert report['production_admission'] == 'BLOCKED'
    assert not report['selection_authorized']
    assert not report['native_rust_worker_batch_verified']
    assert not report['actual_pretrained_encoder_called_in_this_probe']
    assert report['physical_distinct_Cell_head_parameters']
    assert report['full_Cell_bank_numerical_parity_checked']
    assert report['cell_count'] == 16
    assert len(report['timings']) == 4
    assert all(v['p95_ms'] is None and v['p99_ms'] is None for v in report['timings'].values())
    assert all(len(v['raw_ms']) == 2 for v in report['timings'].values())


@pytest.mark.parametrize('controls', [
    {'cells': 0}, {'cells': 4097}, {'rank': 0},
    {'rounds': 0}, {'rounds': 129}, {'warmups': 17}, {'seed': -1},
])
def test_invalid_profiles_reject_before_allocating(controls):
    x, m, labels, rows, pins = sample()
    with pytest.raises(ValueError, match='bounded Cell/readout'):
        measure_packed_readout(x, m, labels, rows, pins,
                              snapshot_sha256(x, m, rows, pins), **controls)


def test_maximum_weight_memory_rejects_before_allocating():
    x, m, labels, rows, pins = sample(width=768)
    with pytest.raises(ValueError, match='exceeds memory cap'):
        measure_packed_readout(x, m, labels, rows, pins,
                              snapshot_sha256(x, m, rows, pins),
                              cells=4096, rank=32, rounds=1)


def test_input_masked_padding_cannot_change_packed_output():
    h = PackedCellHeadBankV1([('c0', CellHead(12, 3, 2)),
                              ('c1', CellHead(12, 3, 2))])
    x, m, *_ = sample()
    a = x[0].clone()
    b = a.clone()
    b[~m[0]] = 1000000
    for kind in ('pooled_cached', 'token_query_prepared'):
        assert torch.equal(h.execute(a, m[0], kind=kind), h.execute(b, m[0], kind=kind))
