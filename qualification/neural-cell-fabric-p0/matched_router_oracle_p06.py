"""Independently authored NumPy arithmetic audit of P0.6's real CPU SGD.

This verification executes only on redacted TRAIN + held FEATURES; never opens
original publisher held labels. It is an independent implementation of
multiclass SGD, route selection and predictions, not a certified theorem, model
provenance signature, or external source-of-gold independence.
"""
from __future__ import annotations
import hashlib
import math
import random

import numpy as np

DIM=384
CLASSES=4
STEPS=512
RATE=.05
DECAY=.0001
SEEDS=(101,211,307)


def route_hash(case_id):
    h=hashlib.sha256(b"hepta.p06.independent-fixed-route.v1\x00" + case_id.encode('utf-8')).digest()
    return h[0] % 2


def softmax(values):
    values=values-np.max(values)
    probs=np.exp(values)
    return probs/np.sum(probs)


def initial(seed):
    engine=random.Random(seed)
    source=[[(engine.random()-.5)*.02 for _ in range(DIM+1)] for _ in range(2*CLASSES)]
    return np.asarray(source,dtype=np.float64).reshape(2,CLASSES,DIM+1)


def independent_fit(redacted,seed,arm):
    weights=initial(seed)[:1].copy() if arm=="shared_one" else initial(seed)
    train=redacted['train']
    features=[np.r_[np.asarray(row['features'],dtype=np.float64),1.] for row in train]
    numbers=list(range(len(train)))
    engine=random.Random(seed+77)
    schedule=[]
    while len(schedule)<STEPS:
        cohort=numbers[:]
        engine.shuffle(cohort)
        schedule.extend(cohort)
    for step,index in enumerate(schedule[:STEPS]):
        row=train[index]
        cell=row['cell']
        x=features[index]
        if arm=='shared_one':
            active=0
            logits=np.einsum('ij,j->i',weights[0],x)
        elif arm=='shared_twin':
            active=step % 2
            logits=.5*(np.einsum('ij,j->i',weights[0],x)+np.einsum('ij,j->i',weights[1],x))
        elif arm=='random_route':
            active=route_hash(row['id'])
            logits=np.einsum('ij,j->i',weights[active],x)
        else:
            active=cell
            logits=np.einsum('ij,j->i',weights[active],x)
        probs=softmax(logits)
        probs[int(row['target'])]-=1.
        factor=.5 if arm=='shared_twin' else 1.
        derivative=np.multiply.outer(probs,x)*factor+DECAY*weights[active]
        weights[active]=weights[active]-RATE*derivative
    return weights


def independent_prob(weights,row,arm):
    x=np.r_[np.asarray(row['features'],dtype=np.float64),1.]
    cell=row['cell']
    if arm=='shared_one':scores=np.einsum('ij,j->i',weights[0],x)
    elif arm=='shared_twin':scores=.5*(np.einsum('ij,j->i',weights[0],x)+np.einsum('ij,j->i',weights[1],x))
    elif arm=='random_route':scores=np.einsum('ij,j->i',weights[route_hash(row['id'])],x)
    elif arm=='split_zero':
        x[:-1]=0.
        scores=np.einsum('ij,j->i',weights[cell],x)
    elif arm=='split_swap':scores=np.einsum('ij,j->i',weights[1-cell],x)
    else:scores=np.einsum('ij,j->i',weights[cell],x)
    return softmax(scores)


def audit_math(redacted,result)->dict:
    """Recompute all 3*4 original trained weights and per-case predictions."""
    original_models=('split','random_route','shared_twin','shared_one')
    if len(redacted['train'])!=64 or len(redacted['holdout'])!=32:raise ValueError("wrong source group census")
    maximum_error=0.
    compared_rows=0
    weight_checks=0
    exact_digest_matches=0
    if tuple(row.get("seed") for row in result["trials"])!=SEEDS:raise ValueError("missing or duplicated seed")
    for trial in result['trials']:
        seed=trial['seed']
        if seed not in SEEDS:raise ValueError("unexpected training seed")
        oracle={}
        for arm in original_models:
            weights=independent_fit(redacted,seed,arm)
            signed=hashlib.sha256(b'hepta.p06.head-weights.v1\x00'+weights.tobytes()).hexdigest()
            report=trial['training'][arm]
            if (report['actually_allocated_weight_tensor_shape']!=list(weights.shape)
                    or report['actually_allocated_weight_tensor_bytes']!=weights.nbytes
                    or report['resident_parameter_scalars']!=weights.size):
                raise ValueError("declared resident parameter allocation contradicts independent tensor")
            if signed==report['weights_sha256']:
                exact_digest_matches+=1
            # This independently authored implementation uses einsum order;
            # FP64 probabilities, rather than bytes, must be validated below.
            weight_checks+=1
            oracle[arm]=weights
        predictions={(r['arm'],r['id']):r['probabilities'] for r in trial['predictions']}
        for row in redacted['holdout']:
            for arm in (*original_models,'split_zero','split_swap','frozen'):
                src= 'split' if arm in ('split_zero','split_swap') else arm
                weights=initial(seed) if arm=='frozen' else oracle[src]
                pred=independent_prob(weights,row,arm if arm!='frozen' else 'split')
                actual=predictions[(arm,row['id'])]
                err=max(abs(float(a)-float(b)) for a,b in zip(pred,actual,strict=True))
                maximum_error=max(maximum_error,err)
                if err>2e-11:raise ValueError(f'original SGD/model prediction mismatch: {arm} {row["id"]} {err}')
                compared_rows+=1
    if maximum_error>=2e-11:raise ValueError("independent numerical tolerance exceeded")
    return {'status':'independent_fp64_arithmetic_replay_pass',
            'seeds':len(SEEDS),'trained_head_sets_recomputed':weight_checks,
            'exact_checkpoint_sha_match_count':exact_digest_matches,
            'numerical_check_not_exact_byte_equality':True,
            'independent_trained_head_prediction_rows_replayed':compared_rows,
            'max_model_prediction_abs_error':maximum_error,
            'source_families':1,'real_pretrained_encoder_new_forward_calls':0,
            'authority':'DENY_ALL','disposition':'HOLD_NO_GO'}
