"""Prevent costly Producer/Reviewer retokenization drift (shadow research only)."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from neuron_shared_encoder.physical_token_reviewer_v1 import require_exact_capture_profile
from test_physical_token_pair_v1 import fixture_trial


def sample(max_length: int = 168, batch: int = 8) -> dict:
    return {
        'encoder_observation': {
            'capture_profile': {'max_length': max_length, 'batch': batch},
            'cells': [
                {'cell': cell,
                 'padded_token_slots': 64 * max_length,
                 'total_encoder_batches': (64 + batch - 1) // batch,
                 'model_forward_observation': {
                     'rows_attempted': 64, 'rows_completed': 64,
                     'module_forward_attempts': (64 + batch - 1) // batch,
                     'module_forward_completions': (64 + batch - 1) // batch,
                     'module_forward_failures_or_incomplete': 0,
                 }} for cell in (0, 1)
            ]
        }
    }


def test_same_profile_and_forward_counters_accepted():
    require_exact_capture_profile(sample(), max_length=168, batch=8)
    require_exact_capture_profile(sample(max_length=16, batch=4), max_length=16, batch=4)


@pytest.mark.parametrize('length,batch', [(128,8), (168,4), (True,8), (168,False), (257,8), (168,0)])
def test_mismatched_pretrained_reader_length_or_batch_is_hard_error(length, batch):
    with pytest.raises(ValueError, match='independent replay'):
        require_exact_capture_profile(sample(), max_length=length, batch=batch)


@pytest.mark.parametrize('fault', [
    'missing_profile', 'missing_cell', 'duplicate_cell', 'backwards_cell',
    'injected_profile_field', 'boolean_length', 'padded_slots', 'forward_fail',
    'forward_rows', 'forward_attempts', 'fractional_batches',
])
def test_self_reported_capture_drift_rejected_before_model_load(fault):
    item = deepcopy(sample())
    obs = item['encoder_observation']
    if fault == 'missing_profile': obs.pop('capture_profile')
    if fault == 'missing_cell': obs['cells'].pop()
    if fault == 'duplicate_cell': obs['cells'][1]['cell'] = 0
    if fault == 'backwards_cell': obs['cells'] = list(reversed(obs['cells']))
    if fault == 'injected_profile_field': obs['capture_profile']['grant'] = True
    if fault == 'boolean_length': obs['capture_profile']['max_length'] = True
    if fault == 'padded_slots': obs['cells'][0]['padded_token_slots'] -= 1
    if fault == 'forward_fail': obs['cells'][0]['model_forward_observation']['module_forward_failures_or_incomplete'] = 1
    if fault == 'forward_rows': obs['cells'][1]['model_forward_observation']['rows_completed'] = 63
    if fault == 'forward_attempts': obs['cells'][1]['model_forward_observation']['module_forward_attempts'] = 7
    if fault == 'fractional_batches': obs['cells'][1]['total_encoder_batches'] = 8.0
    with pytest.raises(ValueError, match='(profile|observations|observation|capture counts)'):
        require_exact_capture_profile(item, max_length=168, batch=8)


def test_synthetic_producer_records_requested_profile_without_claiming_pretrained(tmp_path):
    report = fixture_trial(tmp_path, steps=1, seeds=(11,))
    assert report['encoder_observation']['capture_profile'] == {'max_length': 16, 'batch': 8}
    assert report['production_admission'] == 'BLOCKED'
    assert report['real_model_encoder_forward_observed'] is False
    with pytest.raises(ValueError):
        require_exact_capture_profile(report, max_length=16, batch=8)


def test_hosted_job_freezes_one_length_and_batch_for_both_model_calls():
    root = Path(__file__).resolve().parents[3]
    workflow = (root / '.github/workflows/hepta-neuron-physical-token-pair-shadow.yml').read_text()
    assert 'TOKEN_CAPTURE_MAX_LENGTH: "168"' in workflow
    assert 'TOKEN_CAPTURE_BATCH: "8"' in workflow
    assert workflow.count('--max-length "$TOKEN_CAPTURE_MAX_LENGTH"') == 2
    assert '--encoder-batch "$TOKEN_CAPTURE_BATCH"' in workflow
    assert '--batch "$TOKEN_CAPTURE_BATCH"' in workflow
    assert '--max-length 128' not in workflow
