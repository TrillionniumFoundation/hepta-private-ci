"""Separate NumPy equations over saved Head bytes; never grants model use."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import numpy as np
import pytest

from neuron_shared_encoder.physical_token_pair_v1 import (
    _public_rows, fit_sealed_token_pair_v1,
)
from neuron_shared_encoder.physical_token_reviewer_v1 import (
    _recreate_cell_rows, audit_sealed_token_pair, numpy_head_logits,
)
from test_physical_token_pair_v1 import fake_public_rows, fake_capture


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def prepared(tmp_path):
    rows = fake_public_rows()
    by_cell = _public_rows(rows)
    features = {cell: fake_capture(cell, [r['joint_text'] for r in by_cell[cell]], 16)[:2]
                for cell in (0, 1)}
    pins = {'encoder_sha256': sha(b'enc'), 'tokenizer_sha256': sha(b'tok'),
            'preprocessor_sha256': sha(b'proc'), 'normalizer_sha256': sha(b'norm'),
            'dataset_sha256': sha(b'dataset'), 'generation': 1, 'authority_epoch': 1}
    source_sha = sha(b'not-actual-pretrained')
    fit_sealed_token_pair_v1(features=features, by_cell=by_cell, output=tmp_path/'results',
            pins=pins, real_model_called=False, source_zip_sha256=source_sha,
            model_id='synthetic-interface-only', model_revision='synthetic',
            encoder_observation={'actual_pretrained_forward': False},
            rank=8, steps=2, seeds=(11, 23))
    return {'results_dir': tmp_path/'results', 'source': rows, 'features': features,
            'pins': pins, 'source_zip_sha256': source_sha,
            'model_id': 'synthetic-interface-only', 'model_revision': 'synthetic',
            'actual_reencoding': False}


def test_synthetic_numerical_replay_complete_and_always_blocked(tmp_path):
    result = audit_sealed_token_pair(**prepared(tmp_path))
    assert result['independent_numeric_replay_all_metrics_passed'] is True
    assert result['real_pretrained_encoder_forward_reobserved'] is False
    assert result['production_admission'] == 'BLOCKED'
    assert result['selection_authorized'] is False
    assert not result['verified_prospective_future_NDU']
    assert result['training_seeds'] == [11, 23]
    assert result['checked_head_checkpoints'] == 8
    assert result['checked_holdout_cases_per_seed'] == 32
    assert len(result['descriptive_seed_repeated_deltas']) == 8


def test_independent_head_math_for_both_readouts():
    values = {'query': np.ones(4),
              'down.weight': np.ones((2, 4)) * .04,
              'up.weight': np.ones((4, 2)) * .07,
              'classifier.weight': np.vstack([np.ones(4), -np.ones(4)]),
              'classifier.bias': np.array([.1, -.1])}
    data = np.array([[[.2, -.1, .4, .5], [.1, .4, -.2, .3]]])
    mask = np.array([[True, True]])
    for kind in ('pooled_cached', 'token_query_prepared'):
        logits = numpy_head_logits(data, mask, values, kind)
        assert logits.shape == (1, 2) and np.isfinite(logits).all()
        assert logits[0, 0] > logits[0, 1]
    with pytest.raises(ValueError, match='empty independent attention mask'):
        numpy_head_logits(data, np.array([[False, False]]), values, 'token_query_prepared')


@pytest.mark.parametrize('failure,match', [
    ('model', 'wrong or self-promoting'),
    ('promotion', 'wrong or self-promoting'),
    ('candidate_digest', 'wrong signed-status/geometry/source Head manifest'),
    ('metric', 'independent NumPy Head metrics mismatch'),
    ('altered_weights', 'physical safe Head artifact digest mismatch'),
    ('missing_cell', 'invalid/incomplete sealed seed roster'),
])
def test_forged_success_rejected(tmp_path, failure, match):
    args = prepared(tmp_path)
    root = tmp_path/'results'
    report_path = root/'report.json'
    report = json.loads(report_path.read_text())
    if failure == 'model':
        report['model_id'] = 'other-model'
    if failure == 'promotion':
        report['selection_authorized'] = True
    if failure == 'candidate_digest':
        report['runs'][0]['candidate_heads'][0]['head_manifest_sha256'] = 'a'*64
    if failure == 'metric':
        report['runs'][0]['observations'][0]['pooled_cached']['brier'] += .05
    if failure == 'missing_cell':
        report['runs'][0]['candidate_heads'].pop()
    if failure == 'altered_weights':
        path = root/'seed-11-cell-0-pooled_cached'/'head.safetensors'
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
    else:
        report_path.write_text(json.dumps(report, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=False, allow_nan=False)+'\n')
    with pytest.raises(ValueError, match=match):
        audit_sealed_token_pair(**args)


def test_source_cannot_fabricate_future_observation_time():
    source = fake_public_rows()
    source[-1]['observed_at'] = '2026-10-14T00:00:00+00:00'
    with pytest.raises(ValueError, match='fake-time source'):
        _recreate_cell_rows(source)


def test_heldout_label_change_cannot_pass_independent_review(tmp_path):
    args = prepared(tmp_path)
    baseline = audit_sealed_token_pair(**args)
    source = deepcopy(args['source'])
    for row in source:
        if row['split'] == 'holdout':
            row['label'] = (row['label']+1) % 4
    with pytest.raises(ValueError, match='independent NumPy Head metrics mismatch'):
        audit_sealed_token_pair(**{**args, 'source': source})
    assert baseline['production_admission'] == 'BLOCKED'
