"""Measure actual CPU readout and enforce fair pooled-cache control; no authority."""
from __future__ import annotations

from copy import deepcopy

import pytest
import torch

from test_token_reader_v1 import sample
from neuron_shared_encoder.token_reader_v1 import CellHead, snapshot_sha256
from neuron_shared_encoder.token_reader_cost_v1 import (
    cached_pooled_logits, measure_cached_head_cost, prepared_token_query_logits,
)


def probe(tokens, mask, labels, rows, pins, **kwargs):
    return measure_cached_head_cost(tokens, mask, labels, rows, pins,
                                    snapshot_sha256(tokens, mask, rows, pins),
                                    cells=4, rank=4, rounds=3, warmups=1, **kwargs)


def test_correct_cache_parity_with_same_heads_and_no_production_claims():
    x, mask, labels, rows, pins = sample()
    report = probe(x, mask, labels, rows, pins)
    assert report['production_admission'] == 'BLOCKED'
    assert not report['physical_worker_batch_verified']
    assert not report['real_encoder_forward_measured_by_this_probe']
    assert not report['runtime_final_use_or_source_entitlement_verified']
    assert not report['independent_NDU_or_future_utility_verified']
    assert report['active_cell_count'] == 4
    assert report['cached_pooled_feature_bytes'] == x.shape[2] * 4
    assert report['prepared_full_token_bytes'] == x.shape[1] * x.shape[2] * 4 + x.shape[1]
    assert report['independent_parameter_bank_bytes'] == 4 * report['head_parameters_per_cell'] * 4
    assert report['process_rss_after_head_bank_bytes'] is None or report['process_rss_after_head_bank_bytes'] > 0
    for arm in ('pooled_cached', 'token_query_prepared'):
        outcome = report['observations'][arm]
        assert outcome['rounds'] == 3
        assert outcome['batch_wall_ms_p95'] is None  # require >=20 observed rounds
        assert outcome['batch_wall_ms_p99'] is None  # require >=100 observed rounds
        assert all(v >= 0 for v in outcome['wall_ms_samples'])
        assert len(outcome['logit_sum_checksum_sha256']) == 64
    assert 'rows' not in report and 'input_features' not in report
    assert 'labels' not in str(report)


def test_full_model_math_parity_on_masked_and_nonuniform_features():
    x, m, *_ = sample()
    head = CellHead(x.shape[-1], 4, 2).eval()
    x = x[:1]
    m = m[:1]
    with torch.inference_mode():
        masked = x.masked_fill(~m.unsqueeze(-1), 0)
        pooled = masked.sum(1) / m.sum(1, keepdim=True)
        assert torch.allclose(head(x, m, 'pooled_feature_gate'),
                              cached_pooled_logits(head, pooled), atol=1e-6)
        assert torch.allclose(head(x, m, 'token_query_gate'),
                              prepared_token_query_logits(head, masked, m), atol=1e-6)
    x2 = x.clone(); x2[~m] = 1e6
    with torch.inference_mode():
        assert torch.equal(head(x2, m, 'token_query_gate'), head(x, m, 'token_query_gate'))


def test_fails_closed_on_snapshot_drift_and_source_scope_collision():
    x, m, labels, rows, pins = sample()
    digest = snapshot_sha256(x, m, rows, pins)
    x2 = x.clone(); x2[0, 0, 0] += 1
    with pytest.raises(ValueError, match='snapshot digest mismatch'):
        measure_cached_head_cost(x2, m, labels, rows, pins, digest, cells=1)
    other_rows = deepcopy(rows); other_rows[2]['principal'] = 'other'
    with pytest.raises(ValueError, match='cross-Cell'):
        probe(x, m, labels, other_rows, pins)
    other_rows = deepcopy(rows); other_rows[2]['source_group'] = rows[24]['source_group']
    with pytest.raises(ValueError, match='source group leakage'):
        probe(x, m, labels, other_rows, pins)


@pytest.mark.parametrize('kw', [
    {'cells': 0}, {'cells': 4097}, {'rounds': 0}, {'rounds': 129},
    {'warmups': 17}, {'rank': 33}, {'seed': -1},
])
def test_rejects_invalid_benchmark_work_budget(kw):
    x, m, labels, rows, pins = sample()
    with pytest.raises(ValueError, match='bounded active Cell'):
        measure_cached_head_cost(x, m, labels, rows, pins,
                                 snapshot_sha256(x, m, rows, pins), **kw)


def test_call_budget_rejection_precedes_expensive_head_allocation():
    x, m, labels, rows, pins = sample()
    with pytest.raises(ValueError, match='bounded active Cell'):
        measure_cached_head_cost(x, m, labels, rows, pins,
                                 snapshot_sha256(x, m, rows, pins), cells=4096, rounds=128)


def test_reader_rejects_unbound_preprocessed_input():
    head = CellHead(12, 4, 2)
    pooled = torch.ones((1, 13))
    with pytest.raises(ValueError, match='incompatible cached pooled'):
        cached_pooled_logits(head, pooled)
    with pytest.raises(ValueError, match='incompatible prepared token'):
        prepared_token_query_logits(head, torch.ones((1, 2, 12)), torch.zeros((1, 2), dtype=torch.bool))
