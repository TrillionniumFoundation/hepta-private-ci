"""Synthetic-interface tests only: never establish actual pretrained token quality."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
import torch
from safetensors.torch import save as save_safetensors

from neuron_shared_encoder.physical_token_pair_v1 import (
    _public_rows, fit_sealed_token_pair_v1, run_pinned_historical_token_pair,
)
from neuron_shared_encoder.trained_head_artifacts_v1 import _canonical


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fake_public_rows():
    rows=[]
    for i in range(128):
        split='train' if i<64 else 'calibration' if i<96 else 'holdout'
        rows.append({'case_id': f'ag-news:synthetic:{i}', 'group': f'synthetic-group:{i}',
                     'cell':i%2, 'label':(i//2)%4, 'observed_at':None,
                     'scope':'public-ag-news-research', 'split':split,
                     'text':f'Genuine source not loaded, synthetic fake article {i}'})
    return rows


def make_fixture(path: Path) -> str:
    from neuron_shared_encoder.physical_pooled_replay_v1 import MODEL
    prefix,model,revision,width,_ = MODEL['modernbert']
    rows=fake_public_rows()
    dataset=b''.join(_canonical(row) for row in rows)
    manifest=_canonical({'model':{'model_id':model,'revision':revision},
                         'dataset':{'sha256':sha(dataset)}})
    tensor=torch.randn((128,width),generator=torch.Generator().manual_seed(301))
    tensor_bytes=save_safetensors({'features':tensor})
    features_manifest=_canonical({
        'schema':'hepta.offline-frozen-features.v1','contains_labels':False,
        'simulated_encoder':True, 'shape':[128,width],
        'rows':[{'case_id':r['case_id'],'cell':r['cell'],'group':r['group'],
                 'scope':r['scope'],'split':r['split'],
                 'input_sha256':sha(_canonical([r['scope'],r['text']]))} for r in rows],
        'binding':{'dataset_sha256':sha(dataset),'manifest_sha256':sha(manifest)},
        'file_sha256':sha(tensor_bytes),'file_bytes':len(tensor_bytes),
        'tensor_sha256':sha(_canonical(['torch.float32',[128,width]])+
                             bytes(tensor.untyped_storage()))})
    report=_canonical({'frozen_features': {'manifest_sha256':sha(features_manifest),
                       'shape':[128,width], 'simulated_encoder':True}})
    with ZipFile(path,'w',ZIP_DEFLATED) as writer:
        writer.writestr(f'{prefix}/manifest.json',manifest)
        writer.writestr(f'{prefix}/dataset.jsonl',dataset)
        writer.writestr(f'{prefix}/execution/frozen-features/manifest.json',features_manifest)
        writer.writestr(f'{prefix}/execution/frozen-features/features.safetensors',tensor_bytes)
        writer.writestr(f'{prefix}/execution/report.json',report)
    return sha(path.read_bytes())


def fake_capture(cell: int, texts: list[str], length: int):
    assert len(texts)==64 and 'options' in texts[0] and 'question' in texts[0]
    assert length==16
    generator=torch.Generator().manual_seed(510 + cell)
    tokens=torch.randn((64,16,24),generator=generator).contiguous()
    mask=torch.ones((64,16),dtype=torch.bool)
    mask[:,-3:]=False
    return tokens,mask,{'synthetic_interface':True, 'real_model_forward':False}


def fixture_trial(tmp_path, *, source=None, split_callback=fake_capture, steps=2, seeds=(11,23)):
    path=tmp_path/'producer.zip'
    archive_sha=make_fixture(path)
    return run_pinned_historical_token_pair(archive_path=path,archive_sha256=archive_sha,
        checkpoint_dir=tmp_path/'absent-pretrained-model',bundle_sha256=sha(b'synthetic-only'),
        output=tmp_path/'output',max_length=16,steps=steps,seeds=seeds,
        allow_synthetic=True,synthetic_capture=split_callback)


def test_distinct_original_cells_and_retrospective_windows():
    groups=_public_rows(fake_public_rows())
    assert set(groups)=={0,1}
    assert [sum(r['split']==s for r in groups[0]) for s in ('train','calibration','holdout')]==[32,16,16]
    assert groups[0][0]['input_sha256'] != groups[0][1]['input_sha256']
    assert all(r['observed_at'] is None for cell in groups.values() for r in cell)


def test_real_mode_rejects_synthetic_source_without_loading_model(tmp_path):
    source=tmp_path/'source.zip'
    digest=make_fixture(source)
    with pytest.raises(ValueError,match='requires exactly observed physical ZIP'):
        run_pinned_historical_token_pair(archive_path=source,archive_sha256=digest,
             checkpoint_dir=tmp_path/'does-not-exist',bundle_sha256=sha(b'synthetic'),
             output=tmp_path/'must-not-exist')
    assert not (tmp_path/'must-not-exist').exists()


def test_synthetic_capture_may_only_be_used_in_explicit_test_mode(tmp_path):
    with pytest.raises(ValueError,match='synthetic model callbacks forbidden'):
        run_pinned_historical_token_pair(archive_path=tmp_path/'missing.zip',
            archive_sha256=sha(b'absent'),checkpoint_dir=tmp_path/'missing',
            bundle_sha256=sha(b'absent'),output=tmp_path/'none',
            synthetic_capture=fake_capture)


def test_two_cell_two_kind_multiple_seed_save_reload_packed_parity(tmp_path):
    report=fixture_trial(tmp_path)
    assert report['production_admission']=='BLOCKED'
    assert report['selection_authorized'] is False
    assert report['real_model_encoder_forward_observed'] is False
    assert report['retrospective_only_no_certified_observation_timestamps'] is True
    assert report['no_independent_future_or_ood_window_verified'] is True
    assert report['head_params_exactly_equal_within_encoder'] is True
    assert report['distinct_holdout_cases']==32
    assert len(report['runs'])==2
    assert len(list((tmp_path/'output').rglob('head.safetensors')))==8
    assert (tmp_path/'output'/'report.json').is_file()
    assert json.loads((tmp_path/'output'/'report.json').read_text())==report
    for run in report['runs']:
        assert run['all_32_holdout_rows_for_both_arms_verified'] is True
        assert run['max_packed_delta'] < 1e-5
        assert len(run['candidate_heads'])==4
        assert len(run['observations'])==4
        for cell in (0,1):
            arms=[r for r in run['candidate_heads'] if r['cell']==cell]
            assert len(arms)==2
            assert arms[0]['parameter_count']==arms[1]['parameter_count']
            assert arms[0]['training_sample_sha256']==arms[1]['training_sample_sha256']
    with pytest.raises(ValueError,match='fresh create-only'):
        run_pinned_historical_token_pair(archive_path=tmp_path/'producer.zip',
           archive_sha256=sha((tmp_path/'producer.zip').read_bytes()),
           checkpoint_dir=tmp_path/'none',bundle_sha256=sha(b'synthetic-only'),
           output=tmp_path/'output', max_length=16, steps=2,seeds=(11,23),
           allow_synthetic=True,synthetic_capture=fake_capture)


@pytest.mark.parametrize('corrupt,match',[
    ('duplicate_case','noncanonical public source'),
    ('duplicate_group','noncanonical public source'),
    ('future_window','noncanonical public source'),
    ('synthetic_clock','noncanonical public source'),
    ('foreign_scope','noncanonical public source'),
    ('label_error','noncanonical public source'),
    ('missing_class','incomplete training/calibration/holdout'),
])
def test_bad_source_identity_and_fake_time_denied(corrupt,match):
    rows=fake_public_rows()
    if corrupt=='duplicate_case': rows[1]['case_id']=rows[0]['case_id']
    if corrupt=='duplicate_group':rows[1]['group']=rows[0]['group']
    if corrupt=='future_window':rows[-1]['split']='future'
    if corrupt=='synthetic_clock':rows[-1]['observed_at']='2026-10-14T00:00:00+00:00'
    if corrupt=='foreign_scope':rows[-1]['scope']='secret-workspace'
    if corrupt=='label_error':rows[-1]['label']=20
    if corrupt=='missing_class':
        for row in rows:
            if row['cell']==0 and row['split']=='train':row['label']=0
    with pytest.raises(ValueError, match=match):
        _public_rows(rows)


def test_holdout_label_changes_cannot_change_saved_train_head_bytes(tmp_path):
    base=fake_public_rows()
    prepared=_public_rows(base)
    changed=deepcopy(base)
    for row in changed:
        if row['split']=='holdout': row['label']=(row['label']+1)%4
    changed_prepared=_public_rows(changed)
    assert [r['input_sha256'] for r in prepared[0]]==[
        r['input_sha256'] for r in changed_prepared[0]]
    features={cell:fake_capture(cell,[r['joint_text'] for r in prepared[cell]],16)[:2]
              for cell in (0,1)}
    pins={'encoder_sha256':sha(b'encoder'),'tokenizer_sha256':sha(b'tokenizer'),
          'preprocessor_sha256':sha(b'processor'),'normalizer_sha256':sha(b'normalizer'),
          'dataset_sha256':sha(b'pinned-dataset-metadata'),
          'generation':1,'authority_epoch':1}
    common=dict(features=features,pins=pins,real_model_called=False,
                source_zip_sha256=sha(b'not-physical-source'),
                model_id='synthetic-interface-only',model_revision='synthetic',
                encoder_observation={'real_model_forward':False},
                rank=8,steps=2,seeds=(11,))
    result0=fit_sealed_token_pair_v1(output=tmp_path/'left',by_cell=prepared,**common)
    result1=fit_sealed_token_pair_v1(output=tmp_path/'right',by_cell=changed_prepared,**common)
    for cell in (0,1):
        for kind in ('pooled_cached','token_query_prepared'):
            sub=f'seed-11-cell-{cell}-{kind}'
            assert (tmp_path/'left'/sub/'head.safetensors').read_bytes()==(
                tmp_path/'right'/sub/'head.safetensors').read_bytes()
            assert (tmp_path/'left'/sub/'manifest.json').read_bytes()==(
                tmp_path/'right'/sub/'manifest.json').read_bytes()
    before=[{k:v for k,v in entry.items() if k!='training_wall_ns'}
            for entry in result0['runs'][0]['candidate_heads']]
    after=[{k:v for k,v in entry.items() if k!='training_wall_ns'}
           for entry in result1['runs'][0]['candidate_heads']]
    assert before==after


def test_nonfinite_or_incompatible_mask_refused_without_artifacts(tmp_path):
    prepared=_public_rows(fake_public_rows())
    features={cell:fake_capture(cell,[r['joint_text'] for r in prepared[cell]],16)[:2]
              for cell in (0,1)}
    tokens,mask=features[0]
    tokens[0,0,0]=float('nan')
    pins={'encoder_sha256':sha(b'e'),'tokenizer_sha256':sha(b't'),
          'preprocessor_sha256':sha(b'p'),'normalizer_sha256':sha(b'n'),
          'dataset_sha256':sha(b'd'), 'generation':1,'authority_epoch':1}
    with pytest.raises(ValueError,match='finiteness or bounds violated'):
        fit_sealed_token_pair_v1(features=features,by_cell=prepared,output=tmp_path/'none',
            pins=pins,real_model_called=False,source_zip_sha256=sha(b'fixture'),
            model_id='synthetic',model_revision='synthetic',encoder_observation={},
            rank=8,steps=1,seeds=(11,))
    assert not (tmp_path/'none').exists()
