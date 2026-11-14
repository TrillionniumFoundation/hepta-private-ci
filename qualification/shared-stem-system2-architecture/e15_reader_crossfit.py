"""E15: original-model MultiRC four-passage LOPO cheap Cell Head learning.

True original human training labels are material-owner inputs and must not be
exposed for the held passage. Pretrained logits are frozen ORIGINAL source.
No FBSDE solves, no new Reader model calls, no Model/FinalUse authority.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from math import exp, isfinite
from pathlib import Path
from time import process_time_ns
from e14_multirc_route import (ARMS, ARCHIVE_SHA, OBS_ID, SLATE, PANEL,
                               read_prelabel, positive, write_once, strict_json)

SCHEMA = 'hepta.e15.multirc-gated-crossfit-research.v1'
TRAIN_SCHEMA = 'hepta.e15.owner-training-only-passage-fold.v1'
PRED_SCHEMA = 'hepta.e15.label-separated-trained-cell-head.v1'
STEPS = 48
LR = 0.5
L2 = 0.001
EPS = 0.001  # existing original Reader descriptive threshold, not tuned
FAMILY = ('conditioned','mean_pool_query_fused','no_evidence','no_query')
PARAMS = {'learned_linear_5':5, 'learned_gated_3':3}


def digest(obj) -> str:
    from json import dumps
    return sha256(dumps(obj, sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest()


def groups(obs) -> list[str]:
    source = sorted({r['source_group'] for r in obs['rows']})
    if len(source)!=4 or len(obs['rows'])!=33:
        raise ValueError('original four-passage/33-candidate census required')
    return source


def sigmoid(z:float) -> float:
    if not isfinite(z) or abs(z)>10000:
        raise ValueError('invalid numeric')
    return 1/(1+exp(-z)) if z>=0 else exp(z)/(1+exp(z))


def observations(obs):
    """Compute features from frozen original logits, not truth labels.

    Question-centering uses only unlabeled candidates in the SAME question.
    No passage/train label can be inferred through normalization metadata.
    """
    qmeans={}
    for i,r in enumerate(obs['rows']):
        key=(r['source_group'],r['question_slot'])
        logits=tuple(obs['predictions'][arm][i]['logits'][1]-obs['predictions'][arm][i]['logits'][0] for arm in FAMILY)
        if any(type(t) not in (float,int) or not isfinite(t) or abs(t)>100 for t in logits):
            raise ValueError('untrusted Reader logits')
        qmeans.setdefault(key,[]).append(logits)
    if len(qmeans)!=8 or any(not 2<=len(x)<=8 for x in qmeans.values()):
        raise ValueError('nonoriginal complete question slate')
    means={key:tuple(sum(x[j] for x in rows)/len(rows) for j in range(4))
           for key,rows in qmeans.items()}
    records=[]
    for i,r in enumerate(obs['rows']):
        key=(r['source_group'],r['question_slot'])
        logits=tuple(float(obs['predictions'][arm][i]['logits'][1]-obs['predictions'][arm][i]['logits'][0]) for arm in FAMILY)
        p=tuple(sigmoid(v) for v in logits)
        raw=(1.0,)+logits
        gate=(1.0,logits[1]-means[key][1], logits[2]-means[key][2])
        records.append(dict(task_id=r['task_id'], source_group=r['source_group'],
                            question_slot=r['question_slot'], candidate_id=r['candidate_id'],
                            raw=raw, gate=gate, probs=p))
    return records


def answer_signal_gate(obs) -> dict:
    """Pre-outcome diagnostic only; cannot positively authorize System 2.

    The original 0.001 is the frozen V1 *descriptive* tolerance. Small
    within-question variance does NOT mathematically prove zero information,
    but cannot establish adequate calibrated Reader semantic support.
    """
    records=observations(obs)
    spans={}
    for row in records:
        key=(row['source_group'],row['question_slot'])
        spans.setdefault(key,[]).append(row['probs'][0])
    if len(spans)!=8:
        raise ValueError('complete original question panels required')
    changes={key:max(v)-min(v) for key,v in spans.items()}
    return dict(schema='hepta.e15.reader-answer-signal-diagnostic.v1',
                authority='DENY_ALL',conditioned_near_invariant_count=sum(v<=EPS for v in changes.values()),
                conditioned_exact_tie_count=sum(v==0 for v in changes.values()),
                complete_question_count=8,
                system2_full_fbsde_admitted=False,
                uncalibrated_variance_does_not_prove_semantic_reasoning=True,
                mathematical_global_fbsde_check_not_attempted=True)


def training_input(obs, original_labels:dict[str,int], fold:int) -> dict:
    """Material owner ONLY: held labels excluded from serialized train file."""
    group=groups(obs)
    if type(fold) is not int or not 0<=fold<4 or type(original_labels) is not dict:
        raise ValueError('bad material-owner fold')
    if set(original_labels)!={r['task_id'] for r in obs['rows']} or any(type(v) is not int or v not in (0,1) for v in original_labels.values()):
        raise ValueError('incomplete original human target identity')
    train=[dict(task_id=r['task_id'],label=original_labels[r['task_id']])
           for r in obs['rows'] if r['source_group']!=group[fold]]
    if len(train) not in (23,24,25,27) or any(r['task_id'] in
            {v['task_id'] for v in obs['rows'] if v['source_group']==group[fold]} for r in train):
        raise ValueError('held labels included in fold')
    return dict(schema=TRAIN_SCHEMA, authority='DENY_ALL', fold=fold,
                held_group=group[fold], original_observation_id=OBS_ID,
                source_archive_sha256=ARCHIVE_SHA, slate_id=SLATE,
                original_validation_human_label_source_sha256='5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada',
                training_label_rows=train, held_labels_exposed=False,
                future_observation_window=False, production_accepted=False)


def verify_train(obs, t):
    if (type(t) is not dict or set(t)!={'schema','authority','fold','held_group','original_observation_id',
            'source_archive_sha256','slate_id','original_validation_human_label_source_sha256',
            'training_label_rows','held_labels_exposed','future_observation_window','production_accepted'}
            or t['schema']!=TRAIN_SCHEMA or t['authority']!='DENY_ALL'
            or t['original_observation_id']!=OBS_ID or t['source_archive_sha256']!=ARCHIVE_SHA
            or t['slate_id']!=SLATE or t['original_validation_human_label_source_sha256']!='5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada' or t['held_labels_exposed'] is not False
            or t['future_observation_window'] is not False or t['production_accepted'] is not False
            or type(t['fold']) is not int or not 0<=t['fold']<4):
        raise ValueError('ineligible training-only material')
    group=groups(obs)
    if t['held_group']!=group[t['fold']]:
        raise ValueError('held group mismatch')
    train=t['training_label_rows']
    allowed=[r['task_id'] for r in obs['rows'] if r['source_group']!=t['held_group']]
    if (type(train) is not list or len(train)!=len(allowed)
            or [r.get('task_id') for r in train if type(r) is dict]!=allowed
            or any(type(r) is not dict or set(r)!={'task_id','label'}
                   or type(r['label']) is not int or r['label'] not in (0,1) for r in train)):
        raise ValueError('training label count/order or held boundary differs')
    return {r['task_id']:r['label'] for r in train}


def fit(features:list[dict], labels:dict[str,int], method:str):
    if method not in PARAMS or type(labels) is not dict:
        raise ValueError('unknown trained Head')
    feature='raw' if method=='learned_linear_5' else 'gate'
    weight=[0.0]*PARAMS[method]
    rows=[(r,labels[r['task_id']]) for r in features if r['task_id'] in labels]
    if not 20<=len(rows)<=30 or any(y not in (0,1) for _,y in rows):
        raise ValueError('invalid human training coverage')
    start=process_time_ns()
    for _ in range(STEPS):
        grad=[0.0]*len(weight)
        for row, target in rows:
            x=row[feature]
            z=sum(a*b for a,b in zip(weight,x,strict=True))
            if method=='learned_linear_5':
                p=sigmoid(z)
                part=2*(p-target)*p*(1-p)
            else:
                gate=sigmoid(z)
                p=(1-gate)*row['probs'][0]+gate*row['probs'][1]
                part=2*(p-target)*(row['probs'][1]-row['probs'][0])*gate*(1-gate)
            for j,v in enumerate(x):grad[j]+=part*v
        for j in range(len(weight)):
            weight[j]-=LR*(grad[j]/len(rows)+(L2*weight[j] if j else 0.0))
        if any(not isfinite(w) or abs(w)>1000 for w in weight):
            raise ValueError('numeric training failure')
    cpu=process_time_ns()-start
    if cpu<=0:
        raise ValueError('missing actual training work')
    return weight,cpu


def predict(r,weights,method):
    x=r['raw' if method=='learned_linear_5' else 'gate']
    z=sum(w*v for w,v in zip(weights,x,strict=True))
    if method=='learned_linear_5':return sigmoid(z)
    gate=sigmoid(z)
    return (1-gate)*r['probs'][0]+gate*r['probs'][1]


def train_one(obs, t) -> dict:
    labels=verify_train(obs,t)
    data=observations(obs)
    held=[r for r in data if r['source_group']==t['held_group']]
    if not 3<=len(held)<=10:
        raise ValueError('missing held candidate slate')
    fitted={};meter={};predictions=[]
    for method in PARAMS:
        weights,cpu=fit(data,labels,method)
        fitted[method]=weights
        start=process_time_ns()
        prob=[predict(r,weights,method) for r in held]
        infer=process_time_ns()-start
        if infer<=0 or any(not 0<p<1 for p in prob):
            raise ValueError('unsupported numerical Head prediction')
        meter[method]=dict(train_cpu_ns=cpu,held_cpu_ns=infer,
                           physical_parameter_count=len(weights),train_steps=STEPS)
    for r in held:
        predictions.append(dict(task_id=r['task_id'], source_group=r['source_group'],
                                question_slot=r['question_slot'],candidate_id=r['candidate_id'],
                                probs={method:predict(r,fitted[method],method) for method in PARAMS}))
    return dict(schema=PRED_SCHEMA,authority='DENY_ALL',original_archive_sha256=ARCHIVE_SHA,
                original_observation_id=OBS_ID,fold=t['fold'],held_group=t['held_group'],
                train_only_label_input_sha256=digest(t), train_only_group_count=3,
                held_original_human_labels_accessed=False,training_profile='48-full-batch-SGD-0.5-Brier-L2-0.001',
                new_pretrained_forwards=0,original_reader_weights_unchanged=True,
                full_training_cost_included=False, # original pretrained training/load not rerun
                methods=list(PARAMS),weights=fitted,meters=meter,predictions=predictions,
                production_accepted=False,causal_improvement_established=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    cmd=ap.add_subparsers(dest='mode',required=True)
    prepare=cmd.add_parser('material')
    for arg in ('archive','validation-parquet','output'):
        prepare.add_argument('--'+arg,required=True)
    prepare.add_argument('--fold',type=int,required=True)
    train=cmd.add_parser('train')
    for arg in ('archive','train-only-material','output'):
        train.add_argument('--'+arg,required=True)
    args=ap.parse_args()
    obs=read_prelabel(args.archive)
    if args.mode=='material':
        from e14_multirc_score import original_labels, read_validation
        original=original_labels(read_validation(args.validation_parquet),obs['rows'])
        t=training_input(obs,original,args.fold)
        h=write_once(args.output,t)
    else:
        t=strict_json(Path(args.train_only_material).read_bytes())
        h=write_once(args.output,train_one(obs,t))
    print(f'{h} DENY_ALL')

if __name__=='__main__':main()
