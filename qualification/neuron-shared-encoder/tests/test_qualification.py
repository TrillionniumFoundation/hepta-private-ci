from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import pytest
import torch

from neuron_shared_encoder.contracts import (
    FeatureKey, ImmutableFeatureCache, evidence_gate, load_dataset, sha256_file,
)
from neuron_shared_encoder.models import Head, OfflineEncoder, OrganExpertBank, frozen_projection
from neuron_shared_encoder.experiment import _auc, _metrics, _run_head, _sample_data, _stress, _parser


def generated(tmp_path: Path) -> Path:
    path = tmp_path / 'input.jsonl'
    _sample_data(str(path), 42, 8, 4)
    return path


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()]


def rewrite(path: Path, values: list[dict]):
    path.write_text('\n'.join(json.dumps(x) for x in values) + '\n')


def test_dataset_valid_group_time_and_hash(tmp_path):
    p = generated(tmp_path)
    out, metadata = load_dataset(p, expected_sha256=sha256_file(p))
    assert metadata['rows'] == len(out)
    assert metadata['split_counts']['future'] == 8
    with pytest.raises(ValueError, match='digest'):
        load_dataset(p, expected_sha256='f'*64)


def test_dataset_cross_split_group_leak(tmp_path):
    p = generated(tmp_path)
    records = rows(p)
    future = next(r for r in records if r['split'] == 'future')
    future['source_group'] = records[0]['source_group']
    rewrite(p, records)
    with pytest.raises(ValueError, match='leaked'):
        load_dataset(p)


def test_dataset_future_window_travel(tmp_path):
    p = generated(tmp_path)
    r = rows(p)
    next(x for x in r if x['split'] == 'future')['event_time'] = r[0]['event_time']
    rewrite(p, r)
    with pytest.raises(ValueError, match='future'):
        load_dataset(p)


@pytest.mark.parametrize('bad', [True, -1, 4, '0'])
def test_dataset_invalid_label_rejected(tmp_path, bad):
    p = generated(tmp_path)
    r = rows(p)
    r[0]['label'] = bad
    rewrite(p, r)
    with pytest.raises(ValueError, match='label'):
        load_dataset(p)


def test_dataset_cross_cell_pool_rejected(tmp_path):
    p = generated(tmp_path)
    r = rows(p)
    r[1]['cell_id'] = 'other-cell'
    rewrite(p, r)
    args = _parser().parse_args(['head', '--dataset', str(p), '--output', str(tmp_path / 'results'),
                                 '--allow-synthetic'])
    with pytest.raises(ValueError, match='one scoped Cell'):
        _run_head(args)


def key(principal='p1', generation=1, epoch=1):
    digest = 'a' * 64
    return FeatureKey(principal, 'decision', digest, digest, digest, digest,
                      'b' * 64, digest, generation, epoch)


def test_cache_requires_fresh_admission_and_immutable():
    c = ImmutableFeatureCache()
    k = key()
    with pytest.raises(PermissionError):
        c.put(k, [1.0, 2.0], 1)
    c.put(k, [1.0, 2.0], 1, admitted=True)
    with pytest.raises(PermissionError):
        c.get(k, 2)
    v = c.get(k, 2, admitted=True)
    assert v == (1.0, 2.0)
    with pytest.raises(TypeError):
        v[0] = 99


def test_cache_full_scope_generation_epoch_and_invalidation():
    c = ImmutableFeatureCache()
    k = key()
    c.put(k, [1.0], 1, admitted=True)
    assert c.get(key('p2'), 1, admitted=True) is None
    assert c.get(key(generation=2), 1, admitted=True) is None
    assert c.get(key(epoch=2), 1, admitted=True) is None
    assert c.invalidate_scope('p1', 2) == 1
    assert c.get(k, 1, admitted=True) is None


def test_cache_ttl_lru_and_capacity():
    c = ImmutableFeatureCache(max_items=1, max_bytes=16, ttl_ticks=2)
    k1, k2 = key(), key(principal='p2')
    c.put(k1, [1.0, 2.0], 1, admitted=True)
    c.put(k2, [3.0], 1, admitted=True)
    assert c.get(k1, 1, admitted=True) is None
    assert c.get(k2, 3, admitted=True) is None
    assert c.bytes == 0
    with pytest.raises(ValueError):
        c.put(k1, [1.0, float('nan')], 1, admitted=True)


def test_gate_never_promotes_even_all_strings():
    g = evidence_gate({})
    assert g['status'] == 'BLOCKED'
    forged = {f: 'x'*200 for f in g['required']}
    assert evidence_gate(forged)['status'] == 'BLOCKED'
    assert evidence_gate(forged)['missing'] == []


@pytest.mark.parametrize('kind', ['linear', 'film', 'lowrank8', 'lowrank16', 'mlp', 'swiglu'])
def test_heads_real_parameter_counts(kind):
    for budget in [2048, 16384, 65536, 262144]:
        h = Head(kind, 256, 4, budget)
        assert h.parameter_count == sum(p.numel() for p in h.parameters())
        with torch.no_grad():
            assert h(torch.randn(3, 256)).shape == (3, 4)
        if kind in ('mlp', 'swiglu'):
            assert h.parameter_count <= budget


def test_organ_bank_and_projection_deterministic():
    x = torch.randn(5, 23)
    assert torch.equal(frozen_projection(x, 8, 42), frozen_projection(x, 8, 42))
    assert not torch.equal(frozen_projection(x, 8, 42), frozen_projection(x, 8, 43))
    m = OrganExpertBank(8, 4)
    assert m(frozen_projection(x, 8, 42)).shape == (5, 4)


def test_synthetic_head_smoke_and_no_change_distinguisher(tmp_path):
    p = generated(tmp_path)
    args = _parser().parse_args(['head', '--dataset', str(p), '--output', str(tmp_path/'head.json'),
                                '--allow-synthetic', '--steps', '2', '--budgets', '2048', '16384'])
    report = _run_head(args)
    assert report['production_admission'] == 'BLOCKED'
    assert report['evidence_class'] == 'SYNTHETIC_SMOKE'
    assert report['untrained_baseline_is_not_no_change']
    assert len(report['head_candidates']) == 12
    assert any(row['status'] == 'OVER_BUDGET' for row in report['head_candidates'])
    assert all(row['status'] in ('OVER_BUDGET', 'EVALUATED_SHADOW') for row in report['head_candidates'])


def test_real_model_fails_closed_if_missing_assets(tmp_path):
    path = generated(tmp_path)
    a = _parser().parse_args(['representation', '--dataset', str(path),
                              '--encoder', 'laya-joint', '--output', str(tmp_path/'result')])
    with pytest.raises(ValueError, match='dataset-sha256'):
        _run_head(a)
    a.dataset_sha256 = sha256_file(path)
    with pytest.raises(ValueError, match='checkpoint-dir'):
        _run_head(a)
    with pytest.raises(FileNotFoundError):
        OfflineEncoder('laya-joint', '/path/not/there', 'a'*64)


def test_representation_disallows_synthetic(tmp_path):
    path = generated(tmp_path)
    a = _parser().parse_args(['representation', '--dataset', str(path),
                              '--allow-synthetic', '--output', str(tmp_path/'result'),
                              '--steps', '1', '--budgets', '2048'])
    with pytest.raises(ValueError, match='authenticated real checkpoint'):
        _run_head(a, mode='representation')


def test_batch_scalar_gating_parity():
    torch.manual_seed(123)
    x = torch.randn(37, 256)
    gamma = torch.randn(37, 256)
    beta = torch.randn(37, 256)
    readout = torch.randn(256, 4)
    vector = (x * gamma + beta) @ readout
    scalar = torch.stack([((x[i] * gamma[i] + beta[i]) @ readout) for i in range(37)])
    assert torch.allclose(vector, scalar, atol=1e-5, rtol=1e-5)


def test_ood_auc_logic():
    assert _auc(torch.tensor([0.9, 0.8]), torch.tensor([0.1, 0.2])) == 1.
    assert _auc(torch.tensor([0.5]), torch.tensor([0.5])) == .5


def test_synthetic_stress_runs_and_records_real_batch_execution():
    args = _parser().parse_args(['stress', '--output', '/tmp/dummy', '--allow-synthetic',
                                 '--cell-counts', '64', '--rounds', '1', '--inference-batch', '16'])
    report = _stress(args)
    assert len(report['results']) == 9
    assert report['production_admission'] == 'BLOCKED'
    assert all(r['requests'] > 0 for r in report['results'])
    assert all(r['encoder_forward_rows'] > 0 for r in report['results'])
