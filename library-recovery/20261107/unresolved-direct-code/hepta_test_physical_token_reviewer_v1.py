"""Truly separate NumPy equations over saved Head bytes; never grants use."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import numpy as np
import pytest
import torch

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
    fit_sealed_token_pair_v1(features=features,by_cell=by_cell,output=tmp_path/'results',
            pins=pins,real_model_called=False,source_zip_sha256=source_sha,
            model_id='synthetic-interface-only',model_revision='synthetic',
            encoder_observation={'actual_pretrained_forward': False},
            rank=8,steps=2,seeds=(11,23))
    args={'results_dir':tmp_path/'results', 'source':rows, 'features':features,
          'pins':pins,'source_zip_sha256':source_sha,
          'model_id':'synthetic-interface-only','model_revision':'synthetic',
          'actual_reencoding':False}
    return args


def test_synthetic_numerical_replay_is_complete_and_always_blocked(tmp_path):
    args = prepared(tmp_path)
    audit = audit_sealed_token_pair(**args)
    assert audit['independent_numeric_replay_all_metrics_passed'] is True
    assert audit['real_pretrained_encoder_forward_reobserved'] is False
    assert audit['production_admission'] == 'BLOCKED'
    assert audit['selection_authorized'] is False
    assert not audit['verified_prospective_future_NDU']
    assert audit['training_seeds'] == [11,23]
    assert audit['checked_head_checkpoints'] == 8
    assert audit['checked_holdout_cases_per_seed'] == 32
    assert len(audit['descriptive_seed_repeated_deltas']) == 8


def test_independent_head_math_both_kinds_small_known_numbers():
    width=4
    values={'query':np.ones(width),
            'down.weight':np.ones((2,width))*.04,
            'up.weight':np.ones((width,2))*.07,
            'classifier.weight':np.vstack([np.ones(width),-np.ones(width)]),
            'classifier.bias':np.array([.1,-.1])}
    data=np.array([[[.2,-.1,.4,.5],[.1,.4,-.2,.3]]])
    mask=np.array([[True,True]])
    for kind in ('pooled_cached','token_query_prepared'):
        logits=numpy_head_logits(data,mask,values,kind)
        assert logits.shape==(1,2) and np.isfinite(logits).all()
        assert logits[0,0]>logits[0,1]
    with pytest.raises(ValueError,match='empty independent attention mask'):
        numpy_head_logits(data,np.array([[False,False]]),values,'token_query_prepared')


@pytest.mark.parametrize('failure,match',[
    ('model','wrong or self-promoting'),
    ('promotion','wrong or self-promoting'),
    ('candidate_digest','wrong signed-status/geometry/source Head manifest'),
    ('metric','independent NumPy Head metrics mismatch'),
    ('altered_weights','physical safe Head artifact digest mismatch'),
    ('missing_cell','invalid/incomplete sealed seed roster'),
])
def test_tampering_cannot_be_masked_by_self_reported_success(tmp_path,failure,match):
    args=prepared(tmp_path)
    root=tmp_path/'results'
    report_path=root/'report.json'
    report=json.loads(report_path.read_text())
    if failure=='model':report['model_id']='other-model'
    if failure=='promotion':report['selection_authorized']=True
    if failure=='candidate_digest':
        report['runs'][0]['candidate_heads'][0]['head_manifest_sha256']='a'*64
    if failure=='metric':
        report['runs'][0]['observations'][0]['pooled_cached']['brier']+=.05
    if failure=='missing_cell':report['runs'][0]['candidate_heads'].pop()
    if failure=='altered_weights':
        p=root/'seed-11-cell-0-pooled_cached'/'head.safetensors'
        original=bytearray(p.read_bytes());original[-1]^=1;p.write_bytes(original)
    else:
        report_path.write_text(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n')
    with pytest.raises(ValueError,match=match):
        audit_sealed_token_pair(**args)


def test_independent_source_refuses_relabeling_as_prospective():
    src=fake_public_rows()
    src[-1]['observed_at']='2026-10-14T00:00:00+00:00'
    with pytest.raises(ValueError,match='fake-time source'):
        _recreate_cell_rows(src)


def test_future_retrospective_metrics_cannot_modify_sealed_head_bytes(tmp_path):
    args=prepared(tmp_path)
    sealed=audit_sealed_token_pair(**args)
    source=deepcopy(args['source'])
    for row in source:
        if row['split']=='holdout':row['label']=(row['label']+1)%4
    with pytest.raises(ValueError,match='independent NumPy Head metrics mismatch'):
        audit_sealed_token_pair(**{**args,'source':source})
    assert sealed['production_admission']=='BLOCKED'
