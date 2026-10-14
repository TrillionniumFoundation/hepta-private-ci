"""Adversarial and paired smoke for shadow token-level Cell readout."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
import torch

from neuron_shared_encoder.token_reader_v1 import (
    CellHead, paired_token_reader_trial, snapshot_sha256,
)


def sample(width: int = 12, sequence: int = 5, per_split: int = 12):
    rows = []
    labels = []
    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for split, offset in [('train', 0), ('validation', 100), ('future', 200), ('ood', 300)]:
        for j in range(per_split):
            label = j % 2
            input_digest = sha256(f'{split}:{j}:question+ordered options'.encode()).hexdigest()
            rows.append({'row_id': f'{split}-{j}', 'principal': 'principal-A',
                         'purpose': 'offline-study', 'organ_id': 'organ-A', 'cell_id': 'cell-A',
                         'source_group': f'family-{split}-{j}',
                         'event_time': (anchor + timedelta(days=offset + j)).isoformat(),
                         'split': split, 'label': label, 'options': ['no', 'yes'],
                         'input_sha256': input_digest})
            labels.append(label)
    generator = torch.Generator().manual_seed(391)
    tokens = torch.randn(len(rows), sequence, width, generator=generator, dtype=torch.float32)
    mask = torch.ones(len(rows), sequence, dtype=torch.bool)
    mask[:, -1] = False
    pins = {key: sha256(key.encode()).hexdigest() for key in (
        'encoder_sha256', 'tokenizer_sha256', 'preprocessor_sha256',
        'normalizer_sha256', 'dataset_sha256')}
    pins['generation'] = 1
    pins['authority_epoch'] = 2
    return tokens, mask, torch.tensor(labels, dtype=torch.long), rows, pins


def trial(tokens, mask, labels, rows, pins, **kwargs):
    return paired_token_reader_trial(tokens, mask, labels, rows, pins,
                                     snapshot_sha256(tokens, mask, rows, pins),
                                     steps=2, batch=8, seeds=(7, 19), **kwargs)


def test_fair_paired_training_has_real_matched_parameters_and_no_grants():
    inputs = sample()
    report = trial(*inputs)
    assert report['production_admission'] == 'BLOCKED'
    assert not report['winner_selected']
    assert not report['selection_authorized']
    assert not report['independent_issuer_or_NDU_verified']
    assert not report['encoder_execution_verified']
    assert not report['actual_worker_batch_verified']
    assert not report['future_used_to_select_winner']
    assert report['paired_initialization'] and report['train_only_normalization']
    assert report['per_cell_head_parameters'] <= 16384
    assert report['snapshot_tensor_bytes_once'] == inputs[0].numel() * 4 + inputs[1].numel()
    assert len(report['runs']) == 2
    for run in report['runs']:
        left = run['candidates']['pooled_feature_gate']
        right = run['candidates']['token_query_gate']
        assert left['parameter_count'] == right['parameter_count'] == report['per_cell_head_parameters']
        assert left['optimizer_state_bytes'] == right['optimizer_state_bytes'] > 0
        assert len(run['same_sampling_sha256']) == 64
        for kind in ('validation', 'future'):
            assert 0 <= left[kind]['accuracy'] <= 1
            assert 0 <= right[kind]['accuracy'] <= 1
    replay = trial(*inputs)
    assert [r['same_sampling_sha256'] for r in report['runs']] == [r['same_sampling_sha256'] for r in replay['runs']]
    assert report['validation_brier_delta_token_minus_pooled'] == pytest.approx(
        replay['validation_brier_delta_token_minus_pooled'], abs=1e-6)


def test_attention_mask_prevents_padding_features_from_changing_predictions():
    tokens, mask, *_ = sample()
    model = CellHead(tokens.shape[-1], 4, 2)
    altered = tokens.clone()
    altered[~mask] = 1e6
    for kind in ('pooled_feature_gate', 'token_query_gate'):
        first = model(tokens, mask, kind)
        second = model(altered, mask, kind)
        assert torch.equal(first, second)
    assert not torch.equal(model(tokens, mask, 'token_query_gate'),
                           model(tokens, mask, 'pooled_feature_gate'))


def test_digest_rejects_mutated_features_mask_source_or_scope():
    tokens, mask, labels, rows, pins = sample()
    before = snapshot_sha256(tokens, mask, rows, pins)
    tokens[0, 0, 0] += 1
    with pytest.raises(ValueError, match='snapshot digest mismatch'):
        paired_token_reader_trial(tokens, mask, labels, rows, pins, before, steps=1, seeds=(1,))
    tokens, mask, labels, rows, pins = sample()
    before = snapshot_sha256(tokens, mask, rows, pins)
    mask[0, 2] = False
    with pytest.raises(ValueError, match='snapshot digest mismatch'):
        paired_token_reader_trial(tokens, mask, labels, rows, pins, before, steps=1, seeds=(1,))
    tokens, mask, labels, rows, pins = sample()
    before = snapshot_sha256(tokens, mask, rows, pins)
    rows[0]['input_sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='snapshot digest mismatch'):
        paired_token_reader_trial(tokens, mask, labels, rows, pins, before, steps=1, seeds=(1,))


@pytest.mark.parametrize('corrupt,match', [
    ('principal', 'cross-Cell'),
    ('purpose', 'cross-Cell'),
    ('cell_id', 'cross-Cell'),
    ('missing_input', 'input digest'),
    ('source_leak', 'source group leakage'),
    ('repeated_id', 'duplicate'),
    ('naive_time', 'timezone-aware'),
    ('non_future', 'future not strictly after'),
    ('bad_options', 'option count/uniqueness'),
    ('missing_train_class', 'all classes'),
    ('bad_labels', 'label/option'),
    ('empty_mask', 'attention mask'),
    ('nan', 'finite token'),
])
def test_fail_closed_even_with_consistent_self_reported_hash(corrupt, match):
    t, m, y, rows, pins = sample()
    rows = deepcopy(rows)
    if corrupt == 'principal': rows[3]['principal'] = 'principal-B'
    if corrupt == 'purpose': rows[3]['purpose'] = 'future-use'
    if corrupt == 'cell_id': rows[3]['cell_id'] = 'another'
    if corrupt == 'missing_input': rows[3]['input_sha256'] = ''
    if corrupt == 'source_leak': rows[24]['source_group'] = rows[0]['source_group']
    if corrupt == 'repeated_id': rows[24]['row_id'] = rows[0]['row_id']
    if corrupt == 'naive_time': rows[24]['event_time'] = '2026-02-01T00:00:00'
    if corrupt == 'non_future': rows[24]['event_time'] = '2026-01-02T00:00:00+00:00'
    if corrupt == 'bad_options': rows[24]['options'] = ['yes', 'yes']
    if corrupt == 'missing_train_class':
        for i in range(12): y[i] = 0; rows[i]['label'] = 0
    if corrupt == 'bad_labels': rows[24]['label'] = 1 - rows[24]['label']
    if corrupt == 'empty_mask': m[24] = False
    if corrupt == 'nan': t[24, 0, 0] = float('nan')
    with pytest.raises(ValueError, match=match):
        trial(t, m, y, rows, pins)


def test_budget_shape_and_digest_pins_are_hard_limits():
    t, m, y, rows, pins = sample(width=64)
    with pytest.raises(ValueError, match='ceiling exceeded'):
        trial(t, m, y, rows, pins, rank=32, budget=2048)
    with pytest.raises(ValueError, match='bounded parameter and training'):
        trial(t, m, y, rows, pins, rank=0)
    with pytest.raises(ValueError, match='distinct bounded training'):
        paired_token_reader_trial(t, m, y, rows, pins, snapshot_sha256(t, m, rows, pins), seeds=(1, 1))
    pins2 = dict(pins)
    pins2['generation'] = 0
    with pytest.raises(ValueError, match='complete immutable'):
        trial(t, m, y, rows, pins2)
    t2 = t.to(torch.float64)
    with pytest.raises(ValueError, match='CPU float32'):
        trial(t2, m, y, rows, pins)


def test_future_label_change_cannot_affect_trained_parameters_or_validation():
    t, m, y, rows, pins = sample()
    baseline = trial(t, m, y, rows, pins)
    modified = deepcopy(rows)
    second_y = y.clone()
    for i, row in enumerate(modified):
        if row['split'] == 'future':
            second_y[i] = 1 - second_y[i]
            row['label'] = int(second_y[i])
    replay = trial(t, m, second_y, modified, pins)
    for left, right in zip(baseline['runs'], replay['runs']):
        assert left['same_sampling_sha256'] == right['same_sampling_sha256']
        for kind in ('pooled_feature_gate', 'token_query_gate'):
            assert left['candidates'][kind]['validation'] == right['candidates'][kind]['validation']
    assert baseline['validation_brier_delta_token_minus_pooled'] == replay['validation_brier_delta_token_minus_pooled']

def test_snapshot_hash_without_numpy_preserves_exact_float32_and_mask(monkeypatch):
    """Hosted torch-only wheels need no implicit numpy installation."""
    from neuron_shared_encoder.token_reader_v1 import snapshot_sha256
    import hashlib
    import struct
    import json

    tokens, mask, _y, rows, pins = sample()
    original = snapshot_sha256(tokens, mask, rows, pins)
    header = json.dumps({'shape': list(tokens.shape), 'dtype': str(tokens.dtype),
                         'mask_shape': list(mask.shape), 'rows': rows, 'pins': pins},
                        sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    packed = struct.pack('<' + 'f' * tokens.numel(), *tokens.reshape(-1).tolist())
    mask_bytes = bytes(int(v) for v in mask.reshape(-1).tolist())
    digest = hashlib.sha256(b'hepta.token-reader.shadow.snapshot.v1\0')
    for section in (header, packed, mask_bytes):
        digest.update(len(section).to_bytes(8, 'big'))
        digest.update(section)
    assert original == digest.hexdigest()
    def unavailable(*_args, **_kwargs):
        raise RuntimeError('NumPy is not installed in hosted CI')
    monkeypatch.setattr(torch.Tensor, 'numpy', unavailable)
    assert snapshot_sha256(tokens, mask, rows, pins) == original


def test_snapshot_hash_does_not_include_bytes_outside_contiguous_view():
    from neuron_shared_encoder.token_reader_v1 import snapshot_sha256
    tokens, mask, _y, rows, pins = sample()
    big_tokens = torch.empty((len(tokens) + 1, *tokens.shape[1:]))
    big_tokens[0] = 999
    big_tokens[1:] = tokens
    big_mask = torch.zeros((len(mask) + 1, mask.shape[1]), dtype=torch.bool)
    big_mask[1:] = mask
    offset_tokens = big_tokens[1:]
    offset_mask = big_mask[1:]
    assert offset_tokens.is_contiguous() and offset_tokens.storage_offset() > 0
    assert offset_mask.is_contiguous() and offset_mask.storage_offset() > 0
    original = snapshot_sha256(tokens, mask, rows, pins)
    assert snapshot_sha256(offset_tokens, offset_mask, rows, pins) == original
    big_tokens[0].fill_(1.0)
    big_mask[0].fill_(True)
    assert snapshot_sha256(offset_tokens, offset_mask, rows, pins) == original
