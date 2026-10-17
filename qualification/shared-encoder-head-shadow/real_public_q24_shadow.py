#!/usr/bin/env python3
"""DENY_ALL: real public ModernBERT Q24 feature -> independent Cell-head shadow.

No network, model execution, heldout labels, authority, NDU acceptance or promotion.
Input: Actions 38902031341 / artifact 12068510329 (ZIP, not a synthetic fixture).
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import torch
from safetensors.torch import load

Q = 1 << 24
ROOT = 'public-q24-feature-snapshot/'
MEMBERS = {'SEALED.json', 'case-registry.json', 'feature-q24.safetensors',
           'pooled-f32.safetensors', 'train-only-pca32.safetensors'}
MODEL_REV = '8949b909ec900327062f0ebf497f51aef5e6f0c8'
DATA_REV = '57ec275d8078af65b7731c2a98be812d844a6d6b'
PINNED_ZIP_SHA256 = 'dfbef09702004bae8ce111f360584b6c9c641cc1b4475b71ef2b6d68af95a77a'
PINNED_SEAL_SHA256 = '180955ec4e74cb985851f7c1ba5ae295b91fc3b5ea2188379e8a958e557e7cc2'


def demand(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(raw):
    def pairs(entries):
        result = {}
        for k, v in entries:
            demand(k not in result, 'duplicate JSON key')
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def audited_inputs(path):
    raw = Path(path).read_bytes()
    demand(0 < len(raw) < 2_000_000, 'archive size')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        demand(set(z.namelist()) == {ROOT + f for f in MEMBERS} |
               {'public-q24-independent-verdict.json'}, 'archive inventory')
        demand(all(0 < f.file_size <= 500_000 for f in z.infolist()), 'member cap')
        blobs = {f: z.read(ROOT + f) for f in MEMBERS}
        verdict = strict_json(z.read('public-q24-independent-verdict.json'))
    seal, cases = strict_json(blobs['SEALED.json']), strict_json(blobs['case-registry.json'])
    identity = seal.get('source_identity', {})
    demand(seal.get('schema') == 'hepta.neuron.real-public-modernbert-q24-features.v1'
           and seal.get('source_class') == 'REAL_PINNED_PUBLIC_ENCODER'
           and identity.get('model_id') == 'answerdotai/ModernBERT-base'
           and identity.get('model_revision') == MODEL_REV
           and identity.get('dataset_revision') == DATA_REV
           and seal.get('physical_encoder_forward_calls_this_snapshot') == 96
           and seal.get('authority') == 'DENY_ALL'
           and seal.get('decision') == 'NO_MODEL_PROMOTION'
           and seal.get('split_counts') == {'fit': 64, 'heldout': 32}
           and seal.get('projection_fitted_on') == 'UNLABELED_FIT_FEATURES_ONLY', 'source identity')
    demand(all(seal.get(k) is False for k in (
        'production_qualification', 'ndu_eligible', 'heldout_predictions_or_labels_scored',
        'future_window_utility_verified', 'no_change_production_v1_baseline_verified',
        'source_group_or_temporal_independence_verified')), 'overstated source authority')
    demand(set(seal.get('files', {})) == MEMBERS - {'SEALED.json'}, 'unsealed files')
    for n, proof in seal['files'].items():
        demand(proof['bytes'] == len(blobs[n]) and
               proof['sha256'] == hashlib.sha256(blobs[n]).hexdigest(), 'payload mismatch')
    seal_sha = hashlib.sha256(blobs['SEALED.json']).hexdigest()
    demand(verdict.get('sealed_sha256') == seal_sha and
           verdict.get('train_only_pca32_exact') is True and
           verdict.get('heldout_labels_absent') is True and
           verdict.get('fit_heldout_overlap_count') == 0 and
           verdict.get('production_qualification') is False, 'independent verdict mismatch')
    fit, hold = cases.get('fit', []), cases.get('heldout', [])
    demand(len(fit) == 64 and len(hold) == 32 and
           all(type(x.get('label')) is int and x['label'] in range(4) for x in fit) and
           all('label' not in x for x in hold) and
           len({x['id'] for x in fit + hold}) == 96, 'case leakage/shape')
    pooled = load(blobs['pooled-f32.safetensors'])
    q24 = load(blobs['feature-q24.safetensors'])
    pca = load(blobs['train-only-pca32.safetensors'])
    for split, count in [('fit',64),('heldout',32)]:
        demand(pooled[split].shape == (count,768) and pooled[split].dtype == torch.float32
               and torch.isfinite(pooled[split]).all().item()
               and q24[split].shape == (count,32) and q24[split].dtype == torch.int64
               and (q24[split].abs() <= 8*Q).all().item(), 'feature type/shape')
    demand(pca['components'].shape == (768,32) and pca['center'].shape == (768,)
           and pca['scale'].shape == (32,), 'PCA dimensions')
    archive_sha = hashlib.sha256(raw).hexdigest()
    demand(archive_sha == PINNED_ZIP_SHA256 and seal_sha == PINNED_SEAL_SHA256,
           'not the exact pinned physical public Q24 artifact')
    return fit, pooled, q24, pca, archive_sha, seal_sha


class LinearCells(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.heads = torch.nn.ModuleList([torch.nn.Linear(32,1) for _ in range(4)])
    def forward(self, x):
        return torch.cat([h(x) for h in self.heads],1)


class GatedCells(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.heads = torch.nn.ModuleList([torch.nn.ModuleDict({
            'down':torch.nn.Linear(32,4,bias=False),
            'up':torch.nn.Linear(4,32,bias=False),
            'gate':torch.nn.Linear(32,1),
            'out':torch.nn.Linear(32,1),
        }) for _ in range(4)])
    def forward(self, x):
        logits=[]
        for h in self.heads:
            y=x+torch.sigmoid(h['gate'](x))*h['up'](h['down'](x))
            logits.append(h['out'](y))
        return torch.cat(logits,1)


def project(train, valid):
    mean=train.mean(0)
    _, singular, vectors=torch.linalg.svd(train-mean,full_matrices=False)
    demand(torch.isfinite(singular).all().item() and (singular[:32]>1e-7).all().item(),
           'fold training-only PCA rank')
    component=vectors[:32].T.contiguous()
    for i in range(32):
        k=int(torch.argmax(component[:,i].abs()))
        if component[k,i].item()<0:
            component[:,i].neg_()
    z=(train-mean)@component
    scale=z.square().mean(0).sqrt().clamp_min(1e-6)
    return (z/scale).clamp(-8,8),(((valid-mean)@component)/scale).clamp(-8,8)


def probability(model,x):
    model.eval()
    with torch.inference_mode():
        return model(x).softmax(1)


def train(model,x,y):
    model.train()
    opt=torch.optim.AdamW(model.parameters(),lr=.01,weight_decay=.01)
    for _ in range(120):
        opt.zero_grad(set_to_none=True)
        torch.nn.functional.cross_entropy(model(x),y).backward()
        opt.step()
    params=sum(p.numel() for p in model.parameters())
    optim=sum(v.numel()*v.element_size() for state in opt.state.values()
              for v in state.values() if isinstance(v,torch.Tensor))
    return {'trainable_parameters':params,'fp32_weight_payload_bytes':params*4,
            'optimizer_tensor_payload_bytes':optim,'steps':120}


def evaluate(scores,y):
    return {'accuracy':round(float((scores.argmax(1)==y).float().mean()),6),
            'nll':round(float(-scores[torch.arange(len(y)),y].clamp_min(1e-8).log().mean()),6),
            'brier':round(float(((scores-torch.nn.functional.one_hot(y,4))**2).sum(1).mean()),6)}


def run(path,seed=17):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    cases,pooled,q24,pca,zip_sha,seal_sha=audited_inputs(path)
    labels=torch.tensor([r['label'] for r in cases],dtype=torch.long)
    demand(torch.bincount(labels,minlength=4).tolist()==[16]*4,'class distribution')
    fold=np.full(64,-1,dtype=np.int64)
    rng=np.random.default_rng(seed)
    for category in range(4):
        ids=np.flatnonzero(labels.numpy()==category)
        rng.shuffle(ids)
        for k,idx in enumerate(ids): fold[idx]=k%4
    results={name:torch.zeros(64,4) for name in ('frozen_random','linear','gated_rank4')}
    costs={}
    for k in range(4):
        a=torch.tensor(np.flatnonzero(fold!=k),dtype=torch.long)
        b=torch.tensor(np.flatnonzero(fold==k),dtype=torch.long)
        xtrain,xval=project(pooled['fit'][a],pooled['fit'][b])
        torch.manual_seed(seed+k)
        linear=LinearCells()
        results['frozen_random'][b]=probability(linear,xval)
        costs['linear']=train(linear,xtrain,labels[a])
        results['linear'][b]=probability(linear,xval)
        torch.manual_seed(seed+k)
        gated=GatedCells()
        costs['gated_rank4']=train(gated,xtrain,labels[a])
        results['gated_rank4'][b]=probability(gated,xval)
    heldout_digests={}
    for name,cls in [('linear',LinearCells),('gated_rank4',GatedCells)]:
        torch.manual_seed(seed+100)
        model=cls()
        train(model,q24['fit'].float()/Q,labels)
        heldout=probability(model,q24['heldout'].float()/Q)
        demand(tuple(heldout.shape)==(32,4),'heldout prediction shape')
        heldout_digests[name]=hashlib.sha256(heldout.numpy().astype('<f4').tobytes()).hexdigest()
    replay={}
    for split in ['fit','heldout']:
        reproduced=((pooled[split]-pca['center'])@pca['components'])/pca['scale']
        drift=(torch.round(reproduced.clamp(-8,8)*Q).to(torch.int64)-q24[split]).abs()
        replay[split]={'max_q24_integer_drift':int(drift.max()),
                       'nonidentical_coordinates':int((drift!=0).sum())}
        demand(replay[split]['max_q24_integer_drift']<=128,'CPU replay out of tolerance')
    return {'schema':'hepta.real-shared-feature-cell-shadow.v1','authority':'DENY_ALL',
            'production_promotion':False,'actual_encoder_reexecuted':False,
            'source_actions_run':38902031341,'source_artifact_id':12068510329,
            'source_zip_sha256':zip_sha,'source_seal_sha256':seal_sha,
            'model_revision':MODEL_REV,'dataset_revision':DATA_REV,
            'source_attested_encoder_forwards':96,
            'training_n':64,'unscored_official_test_n':32,
            'future_window_or_ndu_verified':False,'group_independence_verified':False,
            'fold_training_size':48,'fold_validation_size':16,
            'fold_specific_pca_uses_validation_features':False,
            'model_costs':costs,'four_fold_metrics':{k:evaluate(v,labels) for k,v in results.items()},
            'heldout_unscored_prediction_sha256':heldout_digests,'q24_replay':replay,
            'pytorch_version':torch.__version__,
            'note':'Research only. Frozen random != production no-change; no official heldout label or task utility. No target-host full Encoder, independent signature, Final-use or promotion.'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    demand(not args.output.exists(),'no overwrite')
    result=run(args.snapshot)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'result':str(args.output),'metrics':result['four_fold_metrics']}))


if __name__=='__main__':
    main()
