#!/usr/bin/env python3
"""Physical frozen ModernBERT pooled features -> train-only 32D Q24 snapshot.

Research-only producer. Actual pretrained loading is delegated to the exact
public Encoder source commit. No target-host, owner signature, future effects,
model selection or production Final-use is conferred by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

Q = 1 << 24
SOURCE_COMMIT = '758205d3de23ccbf76649b1446c271101dc917b0'
SOURCE_MODEL_REV = '8949b909ec900327062f0ebf497f51aef5e6f0c8'
SOURCE_BANKING77_REV = '57ec275d8078af65b7731c2a98be812d844a6d6b'
CLASSES = ('card_arrival','cash_withdrawal_not_recognised','exchange_rate','lost_or_stolen_phone')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def exclusive(path: Path, raw: bytes) -> None:
    with path.open('xb') as f:
        f.write(raw)


def verify_public_rows(inputs: dict) -> tuple[list[dict],list[dict]]:
    require(type(inputs) is dict and inputs.get('schema') == 'hepta.banking77-four-intent-inputs.v1',
            'missing frozen original public input schema')
    require(inputs.get('intents') == list(CLASSES), 'public intent ordering drift')
    fit, held = inputs.get('fit'), inputs.get('heldout')
    require(type(fit) is list and type(held) is list and
            len(fit) == 64 and len(held) == 32, 'unregistered 64/32 public source split')
    ids, texts = set(), set()
    for split, rows in [('fit',fit),('heldout',held)]:
        for row in rows:
            require(type(row) is dict and set(row) == (
                {'id','text','label'} if split == 'fit' else {'id','text'}),
                'heldout labels or unexpected fields presented to feature exporter')
            ident, text = row['id'],row['text']
            require(type(ident) is str and 0 < len(ident) <= 128 and ident not in ids,
                    'duplicate/unbounded case ID')
            require(type(text) is str and 0 < len(text.encode('utf-8')) <= 4096 and
                    text.casefold().strip() not in texts, 'duplicate/empty public utterance')
            if split == 'fit':
                require(type(row['label']) is int and 0 <= row['label'] < 4,
                        'invalid fit-only label')
            ids.add(ident)
            texts.add(text.casefold().strip())
    return fit, held


def project_train_only(torch, fit_features, held_features):
    """Compute PCA basis/mean/normalizer ONLY from training features.

    Heldout is evaluated using frozen train geometry, never used for fitting,
    normalization, basis selection, tuning or class-label choice.
    """
    require(fit_features.ndim == held_features.ndim == 2 and
            fit_features.shape[0] == 64 and held_features.shape[0] == 32 and
            fit_features.shape[1] == held_features.shape[1] and
            32 <= fit_features.shape[1] <= 8192 and
            fit_features.dtype == held_features.dtype == torch.float32 and
            fit_features.device.type == held_features.device.type == 'cpu',
            'real Encoder vectors missing or invalid physical dimensions')
    require(bool(torch.isfinite(fit_features).all()) and bool(torch.isfinite(held_features).all()),
            'nonfinite frozen Encoder features')
    with torch.no_grad():
        mean = fit_features.mean(dim=0)
        centered = fit_features - mean
        _, singular, vt = torch.linalg.svd(centered, full_matrices=False)
        require(vt.shape[0] >= 32 and bool(torch.isfinite(singular).all()) and
                bool((singular[:32] > 1e-7).all()),
                'insufficient 32D train-only PCA rank')
        basis = vt[:32].contiguous()
        pivot = basis.abs().argmax(dim=1)
        for k in range(32):
            if basis[k, pivot[k]].item() < 0:
                basis[k].neg_()
        train_z = centered @ basis.T
        scale = train_z.std(dim=0, unbiased=False).clamp_min(1e-6)
        held_z = (held_features - mean) @ basis.T
        projected_fit = (train_z / scale).clamp(-8.0, 8.0)
        projected_held = (held_z / scale).clamp(-8.0, 8.0)
        integer_fit = torch.round(projected_fit * Q).to(torch.int64)
        integer_held = torch.round(projected_held * Q).to(torch.int64)
    for x in (mean,basis,scale,integer_fit,integer_held):
        require(bool(torch.isfinite(x).all()), 'projection generated nonfinite data')
    require(bool((integer_fit.abs() <= 8*Q).all() and (integer_held.abs() <= 8*Q).all()),
            'Q24 output exceeds frozen bounds')
    return {'mean':mean.contiguous(), 'basis':basis.contiguous(),
            'scale':scale.contiguous()}, integer_fit, integer_held


def replay_projection(torch, archive: bytes, source_fit, source_held):
    from safetensors.torch import load
    weights=load(archive)
    require(set(weights) == {'mean','basis','scale'}, 'reloaded physical projection tensor inventory drift')
    dim=source_fit.shape[1]
    require(weights['mean'].shape == (dim,) and weights['basis'].shape == (32,dim)
            and weights['scale'].shape == (32,) and
            all(x.dtype == torch.float32 for x in weights.values()) and
            bool((weights['scale'] > 0).all()),
            'physical projector shape/dtype/admission drift')
    def encode(x):
        return torch.round(((((x-weights['mean']) @ weights['basis'].T) /
                             weights['scale']).clamp(-8,8))*Q).to(torch.int64)
    return encode(source_fit),encode(source_held)


def produce(inputs: dict, backend, model_sha: str, output_dir: Path, *, public_inputs_id: str):
    import torch
    from safetensors.torch import save
    from real_encoder_q24_snapshot_gate import validate
    fit, held = verify_public_rows(inputs)
    require(public_inputs_id == inputs.get('input_id'), 'original public source identity not fixed')
    require(type(model_sha) is str and len(model_sha) == 64 and
            getattr(backend,'dimension',None) == 768,
            'not the frozen original 768D public Encoder')
    torch.set_num_threads(1)
    vectors=[]
    token_counts=[]
    for row in fit + held:
        request={'state':row['text'],'question':'Select the customer service intent.',
                 'options':list(CLASSES)}
        feature,length=backend.encode(request)
        require(feature.shape == (768,) and feature.dtype == torch.float32 and
                feature.device.type == 'cpu' and feature.requires_grad is False and
                bool(torch.isfinite(feature).all()) and
                type(length) is int and 1 <= length <= 256,
                'actual feature not produced by frozen 768D Encoder')
        vectors.append(feature.detach().clone())
        token_counts.append(length)
    fit_matrix=torch.stack(vectors[:64]); held_matrix=torch.stack(vectors[64:])
    weights,qfit,qheld=project_train_only(torch,fit_matrix,held_matrix)
    physical=save(weights)
    reread_fit,reread_held=replay_projection(torch,physical,fit_matrix,held_matrix)
    require(torch.equal(qfit,reread_fit) and torch.equal(qheld,reread_held),
            'physical projection bytes fail deterministic recomputation')
    registry={'fit_case_ids':[r['id'] for r in fit],
              'heldout_case_ids':[r['id'] for r in held]}
    registry_raw=canonical(registry)
    projection_sha=digest(physical)
    registry_sha=digest(registry_raw)
    rows=[]
    for split, originals, quantized in [('fit',fit,qfit),('heldout',held,qheld)]:
        for r, feature in zip(originals,quantized.tolist(),strict=True):
            rows.append({'case_id':r['id'], 'split':split,
                         'source_text_sha256':digest(r['text'].encode('utf-8')),
                         'feature_q24':feature})
    snapshot={'schema':'hepta.neuron.public-encoder-q24-feature-snapshot.v1',
              'encoder_sha256':model_sha,'projection_sha256':projection_sha,
              'registry_sha256':registry_sha,
              'projection_fit_case_ids':registry['fit_case_ids'],
              'feature_rows':rows,
              'claimed_independent_provenance':False,
              'production_qualification':False,'ndu_eligible':False}
    verdict=validate(snapshot,registry,expected_encoder=model_sha,
                     expected_projection=projection_sha,expected_registry_sha=registry_sha)
    require(verdict['all_external_case_ids_covered'] and
            verdict['projection_restricted_to_frozen_train_ids'],
            'consumer rejected frozen original public registry')
    backend.reverify()
    target=Path(output_dir)
    target.mkdir(parents=True,exist_ok=False)
    exclusive(target/'projection.safetensors', physical)
    exclusive(target/'registry.json',registry_raw)
    snapshot_raw=canonical(snapshot)
    exclusive(target/'snapshot.json',snapshot_raw)
    receipt={'schema':'hepta.neuron.actual-public-encoder-q24-producer.v1',
             'encoder_snapshot_sha256':model_sha,
             'projection_safetensors_sha256':projection_sha,
             'registry_sha256':registry_sha,'snapshot_sha256':digest(snapshot_raw),
             'original_public_input_id':public_inputs_id,
             'train_only_projection_fit_count':64,'heldout_projection_fit_count':0,
             'real_pretrained_encoder_invoked':True,
             'physical_encoder_invocations':len(vectors),
             'original_encoder_dimension':768,'output_q24_dimension':32,
             'token_counts_sha256':digest(canonical({'token_counts':token_counts})),
             'physical_output_bytes':sum(x.numel()*x.element_size() for x in [qfit,qheld]),
             'pretraining_contamination_independently_checked':False,
             'projection_owner_signature_verified':False,
             'real_future_window_verified':False,
             'original_selected_v1_no_change_verified':False,
             'production_qualification':False,'ndu_eligible':False,
             'decision':'NO_MODEL_PROMOTION'}
    exclusive(target/'producer-receipt.json',canonical(receipt))
    return receipt


def execute_from_frozen_source(args):
    source=Path(args.original_source).resolve()
    git_sha=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    require(git_sha==SOURCE_COMMIT,'untrusted original pretrained-model source commit')
    dirty=subprocess.check_output(
        ['git','-C',str(source),'status','--porcelain','--untracked-files=no'],
        text=True).strip()
    require(not dirty, 'original verified public source has modified tracked files')
    original=source/'qualification'/'stem-cell-v1'
    require(original.is_dir(),'missing original official study code')
    sys.path.insert(0,str(original))
    import banking77_material
    from public_cell_learning import validate_inputs as validate_original_public_inputs
    from matrix_materials import file_sha256,strict_json
    from hf_encoder_kernel import snapshot_digest
    from hf_complete_checkpoint import ENCODER_PROFILE
    from matrix_runtime import LocalHFEncoder
    require(banking77_material.REVISION==SOURCE_BANKING77_REV,
            'public source revision drift')
    dataset=banking77_material.acquire(Path(args.public_data))
    inputs, labels, selection=banking77_material.prepare(
        (dataset/'banking_data/train.csv').read_bytes(),
        (dataset/'banking_data/test.csv').read_bytes())
    validate_original_public_inputs(inputs)
    del labels
    probe=Path(args.encoder_probe)
    lock=strict_json(probe/'source-lock.json')
    material=strict_json(probe/'downloaded-material.json')
    require(lock['model_id']=='answerdotai/ModernBERT-base' and
            lock['upstream_revision']==SOURCE_MODEL_REV and
            material['source_lock_sha256']==file_sha256(probe/'source-lock.json'),
            'moving or incomplete public Encoder source')
    model_dir=probe/'snapshot'
    model_sha=snapshot_digest(model_dir)
    require(material['snapshot_sha256']==model_sha, 'pretrained physical file changed')
    cfg=dict(snapshot_sha256=model_sha,context_tokens=256,encoder_profile=ENCODER_PROFILE,
             upstream_revision=SOURCE_MODEL_REV,material_approval_sha256=None)
    backend=LocalHFEncoder(model_dir,cfg,{'stem':'smaller_control'})
    receipt=backend.receipt
    complete=receipt.get('complete_checkpoint',{})
    require(receipt.get('snapshot_sha256') == model_sha
            and complete.get('loading',{}).get('complete') is True
            and complete.get('materialization',{}).get('complete') is True
            and complete.get('materialization',{}).get(
                'all_state_dict_tensors_accounted') is True,
            'original pretrained full weight load/materialization not independently checked')
    __import__('torch').set_num_threads(1)
    result=produce(inputs,backend,model_sha,Path(args.output_dir),
                   public_inputs_id=inputs['input_id'])
    require(result['real_pretrained_encoder_invoked'] is True and
            result['physical_encoder_invocations']==96, 'physical run incomplete')
    return result


def main() -> int:
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--original-source',required=True,type=Path)
    a.add_argument('--encoder-probe',required=True,type=Path)
    a.add_argument('--public-data',required=True,type=Path)
    a.add_argument('--output-dir',required=True,type=Path)
    args=a.parse_args()
    try:
        execute_from_frozen_source(args)
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print('BLOCKED_PHYSICAL_PUBLIC_ENCODER_Q24: '+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
