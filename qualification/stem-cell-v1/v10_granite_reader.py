"""Actual Reader SGD/forward over pinned frozen Granite tokens (research-only).

No fake/pretrained substitution: feature inventory includes the exact physical
FrozenTokenEncoder receipt and token tensor SHA. Train accepts TRAIN truth only;
blind inference gets no labels, and fresh labels live with a separate reviewer.
"""
from collections import defaultdict
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
import random
import time

import torch
from torch.nn import functional as F
from safetensors.torch import save_file, load_file

from v10_granite_features import (load, save_new, validate_public,
                                  to_public_reader_case, MODEL, REVISION)
from v9_typed_graph import digest
from bridge_reader import build_reader
from endpoint_v8 import build_endpoint

ARMS=('base','bridge','endpoint')
SEEDS=(41,47,53)
TRAIN_UPDATES=256
BATCH_GROUPS=4
DEPTH=3
LEARNING_RATE=0.001
PAIR_WEIGHT=0.5


def sha_file(path):
    with Path(path).open('rb') as f:
        return sha256(f.read()).hexdigest()


class RealTokenStore:
    def __init__(self, public, root):
        self.public=validate_public(public)
        self.root=Path(root)
        self.receipt=load(self.root/'real-encoder-receipt.json')
        self.meta=load(self.root/'metadata.json')
        if (self.receipt.get('schema')!='hepta.v10.real-granite-encoding.v1'
                or self.receipt.get('public_sha256') != digest(public)
                or self.receipt.get('model_id')!=MODEL
                or self.receipt.get('model_revision')!=REVISION
                or self.receipt.get('real_pretrained_forward_executed') is not True
                or self.receipt.get('frozen_weight_verified') is not True
                or self.receipt.get('held_labels_accessed') is not False
                or self.receipt.get('authority')!='DENY_ALL'
                or self.receipt.get('production_accepted') is not False
                or self.receipt.get('bank_metadata_sha256')!=sha_file(self.root/'metadata.json')
                or self.receipt.get('bank_file_sha256')!=sha_file(self.root/'tokens.pt')
                or self.meta.get('file_sha256')!=self.receipt['bank_file_sha256']
                or type(self.meta.get('bindings')) is not dict):
            raise ValueError('actual frozen Granite receipt or complete bank identity missing')
        self.values=torch.load(self.root/'tokens.pt',map_location='cpu',weights_only=True)
        if (type(self.values) is not dict
                or set(self.values)!=set(self.meta.get('tensor_sha256',{}))
                or set(self.values)!=set(self.meta.get('tokens',{}))):
            raise ValueError('complete public token inventory mismatch')
        for name,value in self.values.items():
            if (type(name) is not str or not isinstance(value,torch.Tensor)
                    or value.dtype!=torch.float32 or value.ndim!=2 or value.shape[-1]!=384
                    or not 1<=value.shape[0]<=1024 or not torch.isfinite(value).all()
                    or sha256(value.detach().contiguous().numpy().tobytes()).hexdigest()
                        != self.meta['tensor_sha256'][name]):
                raise ValueError('materialized model token bytes/shape invalid')
        self.index={}
        for case in public:
            encoded=to_public_reader_case(case)
            expected_id=encoded.case_id
            binding=self.meta['bindings'].get(expected_id)
            if (type(binding) is not dict
                    or binding.get('fact_texts')!=list(case['facts'])
                    or binding.get('question')!=case['question']
                    or binding.get('candidate')!=case['candidate']
                    or binding.get('source_sha256')!=encoded.source_hash
                    or binding.get('public_sha256')!=encoded.feature_source_hash
                    or binding.get('preprocess_sha256')!=self.meta.get('preprocess_sha256')):
                raise ValueError('full original public source→Encoder binding mismatch')
            if any(t not in self.values for t in (*case['facts'],case['question'],case['candidate'])):
                raise ValueError('referenced public feature value missing')
            self.index[case['case_id']]=case
        if len(self.meta['bindings'])!=len(public):
            raise ValueError('unexpected binding rows')

    def batch(self, rows):
        rows=list(rows)
        if not 1<=len(rows)<=16:
            raise ValueError('bounded batch of public rows required')
        for row in rows:
            if self.index.get(row.get('case_id')) != row:
                raise ValueError('nonadmitted or mutated source row')
        f=max(len(row['facts']) for row in rows)
        t=max(len(self.values[t]) for row in rows for t in row['facts'])
        q=max(len(self.values[row['question']]) for row in rows)
        a=max(len(self.values[row['candidate']]) for row in rows)
        if f>64 or t>1024 or q>1024 or a>1024 or len(rows)*f*t*(q+a)>64_000_000:
            raise ValueError('Reader admission bound exceeded')
        facts=torch.zeros(len(rows),f,t,384)
        question=torch.zeros(len(rows),q,384)
        candidate=torch.zeros(len(rows),a,384)
        fm=torch.zeros(len(rows),f,t,dtype=torch.bool)
        qm=torch.zeros(len(rows),q,dtype=torch.bool)
        am=torch.zeros(len(rows),a,dtype=torch.bool)
        for i,row in enumerate(rows):
            for j,txt in enumerate(row['facts']):
                feat=self.values[txt]
                facts[i,j,:len(feat)]=feat
                fm[i,j,:len(feat)]=True
            for txt,out,mask in ((row['question'],question,qm),(row['candidate'],candidate,am)):
                feat=self.values[txt]
                out[i,:len(feat)]=feat
                mask[i,:len(feat)]=True
        return (facts,question,candidate,fm,qm,am)


def new_model(seed,arm):
    if type(seed) is not int or seed not in SEEDS or arm not in ARMS:
        raise ValueError('registered seed and fixed Reader family required')
    model=build_endpoint(seed) if arm=='endpoint' else build_reader(arm,seed)
    if sum(p.numel() for p in model.parameters())!= (38466 if arm=='base' else 42562):
        raise ValueError('frozen original architecture changed')
    return model


def grouped_train(public,train_labels):
    groups=defaultdict(list)
    expected={row['case_id'] for row in public if row['case_id'].startswith('train/')}
    if (type(train_labels) is not dict or set(train_labels)!=expected or len(expected)!=288
            or any(type(v) is not int or v not in (0,1) for v in train_labels.values())):
        raise ValueError('exact TRAIN-only supervised set required; held labels forbidden')
    for row in public:
        if row['case_id'] in train_labels:
            groups[row['source_group']].append(row)
    if len(groups)!=72:
        raise ValueError('complete 72 TRAIN source groups required')
    for rows in groups.values():
        if (len(rows)!=4 or [train_labels[r['case_id']] for r in rows]!=[1,0,0,1]
                or rows[0]['facts']!=rows[1]['facts'] or rows[2]['facts']!=rows[3]['facts']):
            raise ValueError('whole opposite-world four-row groups required')
    return groups


def fit_one(store, train_labels, seed, arm, folder, *, updates=TRAIN_UPDATES):
    if type(updates) is not int or not 1<=updates<=TRAIN_UPDATES:
        raise ValueError('bounded registered SGD effort')
    groups=grouped_train(store.public,train_labels)
    keys=sorted(groups)
    rng=random.Random(f'hepta/v10/granite/fixed-batches/{seed}')
    model=new_model(seed,arm).train()
    opt=torch.optim.Adam(model.parameters(),lr=LEARNING_RATE,foreach=False)
    started_cpu,started_wall=time.process_time_ns(),time.perf_counter_ns()
    schedule=[]
    for step in range(updates):
        ids=rng.sample(keys,BATCH_GROUPS)
        batch=[row for group in ids for row in groups[group]]
        data=store.batch(batch)
        labels=torch.tensor([train_labels[row['case_id']] for row in batch],dtype=torch.long)
        opt.zero_grad(set_to_none=True)
        logits=model(*data,steps=DEPTH)
        ce=F.cross_entropy(logits,labels)
        evidence=logits[:,1]-logits[:,0]
        left=torch.tensor([k*4+offset for k in range(BATCH_GROUPS) for offset in (0,1)])
        right=left+2
        margin=((labels[left]*2-1)*(evidence[left]-evidence[right]))
        pair=F.softplus(1.-margin).mean()
        loss=ce+PAIR_WEIGHT*pair
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError('nonfinite real-token training objective')
        loss.backward()
        if any(p.grad is None or not torch.isfinite(p.grad).all() for p in model.parameters()):
            raise FloatingPointError('all reader gradients required and finite')
        opt.step()
        if any(not torch.isfinite(p).all() for p in model.parameters()):
            raise FloatingPointError('nonfinite model parameters')
        schedule.append(dict(update=step+1,groups=ids,source_sha256=digest([r['case_id'] for r in batch]),
                             ce=float(ce.detach()),pair=float(pair.detach()),total=float(loss.detach())))
    model.eval().requires_grad_(False)
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    weights=folder/'reader.safetensors'
    save_file({name:value.detach().cpu().contiguous() for name,value in model.state_dict().items()},str(weights))
    receipt=dict(schema='hepta.v10.real-granite-training.v1',seed=seed,arm=arm,
        model_parameters=sum(p.numel() for p in model.parameters()),
        actual_updates=len(schedule),batch_size=BATCH_GROUPS*4,
        total_optimizer_case_exposures=len(schedule)*16,
        source_groups=72, training_labels_sha256=digest(train_labels),
        feature_receipt_sha256=sha_file(store.root/'real-encoder-receipt.json'),
        input_public_sha256=digest(store.public),
        weights_sha256=sha_file(weights),
        optimizer='Adam_foreach_false',learning_rate=LEARNING_RATE,depth=DEPTH,
        pair_weight=PAIR_WEIGHT,
        training_cpu_ns=time.process_time_ns()-started_cpu,
        training_wall_ns=time.perf_counter_ns()-started_wall,
        actual_pretrained_forwards_in_this_step=0,
        frozen_pretrained_features_verified=isinstance(store, RealTokenStore),
        experiment_origin=('real_verified_granite' if isinstance(store, RealTokenStore)
                           else 'synthetic_mechanism_test_only'),
        held_labels_seen=False,held_predictions_scored=False,
        model_selected=False,production_accepted=False,authority='DENY_ALL')
    save_new(folder/'schedule.json',schedule)
    receipt['schedule_sha256']=sha_file(folder/'schedule.json')
    save_new(folder/'training.json',receipt)
    return receipt


def scoreblind(store, model_root,output):
    """Unscored complete predictions; no labels can be accepted as an argument."""
    started_cpu,started_wall=time.process_time_ns(),time.perf_counter_ns()
    results={}
    commitments={}
    by_depth=defaultdict(list)
    for row in store.public:
        by_depth[int(row['case_id'].split('/')[1])].append(row)
    for seed in SEEDS:
        for arm in ARMS:
            path=Path(model_root)/f'{seed}-{arm}'
            receipt=load(path/'training.json')
            if (receipt.get('seed')!=seed or receipt.get('arm')!=arm
                    or receipt.get('feature_receipt_sha256')!=sha_file(store.root/'real-encoder-receipt.json')
                    or receipt.get('actual_updates')!=TRAIN_UPDATES
                    or receipt.get('frozen_pretrained_features_verified') is not True
                    or receipt.get('experiment_origin')!='real_verified_granite'
                    or receipt.get('held_labels_seen') is not False
                    or receipt.get('authority')!='DENY_ALL'
                    or receipt.get('weights_sha256')!=sha_file(path/'reader.safetensors')):
                raise ValueError('complete matching train-only frozen candidate required')
            commitment=dict(seed=seed, arm=arm,
                weights_sha256=receipt['weights_sha256'],
                training_receipt_sha256=sha_file(path/'training.json'),
                schedule_sha256=receipt['schedule_sha256'],
                source_public_sha256=receipt['input_public_sha256'],
                feature_receipt_sha256=receipt['feature_receipt_sha256'],
                actual_updates=receipt['actual_updates'],
                experiment_origin=receipt['experiment_origin'])
            if (commitment['source_public_sha256']!=digest(store.public)
                    or receipt['schedule_sha256']!=sha_file(path/'schedule.json')):
                raise ValueError('missing original SHA-bound train source or actual step log')
            commitments[f'{seed}/{arm}']=commitment
            model=new_model(seed,arm)
            model.load_state_dict(load_file(str(path/'reader.safetensors'),device='cpu'),strict=True)
            model.eval().requires_grad_(False)
            data={}
            with torch.no_grad():
                for _, batches in by_depth.items():
                    for i in range(0,len(batches),16):
                        batch=batches[i:i+16]
                        probabilities=model(*store.batch(batch),steps=DEPTH).softmax(-1)[:,1]
                        if not bool(torch.isfinite(probabilities).all()):
                            raise ValueError('nonfinite blind model scores')
                        for row,p in zip(batch,probabilities.tolist()):
                            data[row['case_id']]=float(p)
            if len(data)!=len(store.public):
                raise ValueError('missing blind candidate scores')
            results[f'{seed}/{arm}']=data
    result=dict(schema='hepta.v10.real-granite-blind.v1',public_sha256=digest(store.public),
        feature_receipt_sha256=sha_file(store.root/'real-encoder-receipt.json'),
        arms=list(ARMS),seeds=list(SEEDS),
        probabilities=results,probabilities_sha256=digest(results),
        training_commitments=commitments,commitment_sha256=digest(commitments),
        result_records=sum(len(x) for x in results.values()),
        held_labels_used=False,pretrained_new_model_calls=0,
        actual_reader_model_forwards=len(store.public)*len(results),
        cpu_ns=time.process_time_ns()-started_cpu,
        wall_ns=time.perf_counter_ns()-started_wall,
        model_selected=False,production_accepted=False,authority='DENY_ALL')
    save_new(output,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('fit','predict'))
    for name in ('public','features','models','output'):
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--train-labels',type=Path)
    args=p.parse_args()
    torch.set_num_threads(1)
    public=validate_public(load(args.public))
    store=RealTokenStore(public,args.features)
    if args.phase=='fit':
        if args.train_labels is None:
            raise ValueError('TRAIN labels required only during fit')
        labels=load(args.train_labels)
        args.models.mkdir(parents=True,exist_ok=False)
        for seed in SEEDS:
            for arm in ARMS:
                receipt=fit_one(store,labels,seed,arm,args.models/f'{seed}-{arm}')
                print(json.dumps(dict(seed=seed,arm=arm,updates=receipt['actual_updates'])),flush=True)
    else:
        if args.train_labels is not None:
            raise ValueError('blind inference must not accept any label path')
        scoreblind(store,args.models,args.output)


if __name__=='__main__':main()
