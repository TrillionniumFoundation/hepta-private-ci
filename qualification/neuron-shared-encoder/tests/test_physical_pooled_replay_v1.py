"""Synthetic-only source integrity tests for the retrospective physical import."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import torch
from safetensors.torch import save as safe_save

from neuron_shared_encoder.trained_head_artifacts_v1 import _canonical
from neuron_shared_encoder.physical_pooled_replay_v1 import (
    MODEL, read_public_physical_features, run_pooled_trained_readback,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_archive(path: Path, *, corrupt: str = '') -> str:
    prefix, model, revision, width, _ = MODEL['mmbert']
    samples = []
    for i in range(128):
        split = 'train' if i < 64 else 'calibration' if i < 96 else 'holdout'
        samples.append({'case_id': f'example-{i}', 'cell': i % 2,
                        'group': f'source-{i}', 'label': i % 4,
                        'observed_at': None, 'scope': 'public-ag-news-research',
                        'split': split, 'text': f'public synthetic text {i}'})
    dataset = b''.join(_canonical(row) for row in samples)
    manifest = _canonical({'model':{'model_id':model,'revision':revision},
                           'dataset': {'sha256':sha(dataset)}})
    gen = torch.Generator().manual_seed(41)
    tensor = torch.randn((128, width), generator=gen)
    bytes_tensor = safe_save({'features': tensor})
    rows = [{'case_id':r['case_id'],'cell':r['cell'],'group':r['group'],
             'scope':r['scope'],'split':r['split'],
             'input_sha256':sha(_canonical([r['scope'],r['text']]))}
            for r in samples]
    fm = {'schema':'hepta.offline-frozen-features.v1',
          'simulated_encoder':True,'contains_labels':False,
          'shape':[128,width], 'rows':rows,
          'binding': {'dataset_sha256':sha(dataset),'manifest_sha256':sha(manifest)},
          'file_sha256':sha(bytes_tensor),'file_bytes':len(bytes_tensor),
          'tensor_sha256':sha(_canonical(['torch.float32',[128,width]])+
                              bytes(tensor.untyped_storage()))}
    if corrupt == 'feature_digest':
        fm['file_sha256']='0'*64
    if corrupt == 'source_row':
        fm['rows'][0]['input_sha256']='0'*64
    if corrupt == 'model_revision':
        manifest = _canonical({'model':{'model_id':model,'revision':'wrong'},
                               'dataset':{'sha256':sha(dataset)}})
    fmraw = _canonical(fm)
    report = _canonical({'frozen_features': {'manifest_sha256':sha(fmraw),
                          'shape':[128,width],'simulated_encoder':True}})
    if corrupt == 'wrong_report':
        report = _canonical({'frozen_features': {'manifest_sha256':'a'*64,
                            'shape':[128,width],'simulated_encoder':True}})
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr(f'{prefix}/manifest.json',manifest)
        archive.writestr(f'{prefix}/dataset.jsonl',dataset)
        archive.writestr(f'{prefix}/execution/frozen-features/manifest.json',fmraw)
        archive.writestr(f'{prefix}/execution/frozen-features/features.safetensors',bytes_tensor)
        archive.writestr(f'{prefix}/execution/report.json',report)
    return sha(path.read_bytes())


def test_synthetic_import_and_trained_checkpoint_parity_only(tmp_path):
    archive=tmp_path/'study.zip'
    digest=make_archive(archive)
    with pytest.raises(ValueError, match='requires exactly observed physical ZIP'):
        read_public_physical_features(archive,digest,arm='mmbert')
    features,rows,receipt=read_public_physical_features(
        archive,digest,arm='mmbert',allow_synthetic=True)
    assert features.shape == (128,384)
    assert not receipt['physical_source_verified_locally']
    result=run_pooled_trained_readback(archive,digest,tmp_path/'results',
              arm='mmbert',steps=2,seeds=(7,),allow_synthetic=True)
    assert result['production_admission']=='BLOCKED'
    assert result['token_query_efficacy_tested'] is False
    assert result['genuine_prospective_future_window'] is False
    assert result['source']['physical_source_verified_locally'] is False
    assert result['control_kind']=='random_initialization_not_deployed_no_change'
    assert len(result['results'][0]['cells'])==2
    assert result['results'][0]['all_32_retrospective_holdout_packed_parity_verified']
    assert result['results'][0]['heldout_maximum_packed_difference'] < 1e-5
    assert len(list((tmp_path/'results').rglob('head.safetensors')))==2
    with pytest.raises(ValueError,match='fresh create-only'):
        run_pooled_trained_readback(archive,digest,tmp_path/'results',
                 arm='mmbert',steps=1,seeds=(7,),allow_synthetic=True)


@pytest.mark.parametrize('corrupt,match',[
    ('feature_digest','physical pretrained tensor bytes mismatch'),
    ('source_row','complete bound retrospective source row'),
    ('model_revision','model revision mismatch'),
    ('wrong_report','unbound or synthetic feature provenance'),
])
def test_corrupt_model_dataset_feature_witness_denied(tmp_path,corrupt,match):
    archive=tmp_path/'corrupt.zip'
    digest=make_archive(archive,corrupt=corrupt)
    with pytest.raises(ValueError,match=match):
        read_public_physical_features(archive,digest,arm='mmbert',allow_synthetic=True)


def test_archive_hash_tamper_and_negative_controls(tmp_path):
    archive=tmp_path/'real.zip'
    original=make_archive(archive)
    with pytest.raises(ValueError,match='historical public artifact ZIP SHA256'):
        read_public_physical_features(archive,'0'*64,arm='mmbert',allow_synthetic=True)
    with pytest.raises(ValueError,match='registered physical arm'):
        read_public_physical_features(archive,original,arm='unknown',allow_synthetic=True)
    with pytest.raises(ValueError,match='bounded fixed training schedule'):
        run_pooled_trained_readback(archive,original,tmp_path/'none',
                                   arm='mmbert',seeds=(7,7),allow_synthetic=True)
    assert not (tmp_path/'none').exists()
