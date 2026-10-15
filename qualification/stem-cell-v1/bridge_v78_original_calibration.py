"""V7.8: real archived Granite-Reader logits, real MultiRC labels, tiny calibration controls.

An intentionally cheap, honest NEGATIVE CONTROL for gated 1,700-parameter Cell
claims. This does not execute the Granite Encoder or refit the BridgeReader.
Scores were already observed in historical V4/V6 experiments; group-held-out
folds in that exposed panel are not prospective validation or product gates.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import random
import stat
import time
import zipfile

import torch
from torch.nn import functional as F

V6_SHA = '197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a'
SEEDS = (41,47,53)
ARMS = ('frozen','always_positive','fit_threshold','two_scalar_calibrator')
SCHEMA = 'hepta.bridge.v78.original-natural-exposed-source-folds.shadow.v1'
UPDATES = 240
FOLDS = 4
TRAINABLE_SCALARS = 2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(obj):
    return sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,
       allow_nan=False).encode('utf-8')).hexdigest()


def original_bytes(path):
    p=Path(path)
    require(not p.is_symlink(), 'original evidence must not be symlinked')
    fd=os.open(p,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size==20_928_479,
                'exact original V6 evidence size required')
        data=f.read(before.st_size+1)
        after=os.fstat(f.fileno())
    require(len(data)==before.st_size and
            (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) and
            sha256(data).hexdigest()==V6_SHA,'original V6 artifact bytes replaced')
    return data


def case_id(r):
    return json.dumps([r[k] for k in ('source_split','paragraph_id','question_id','answer_id')],separators=(',',':'))


def read_original(path):
    """Admit only frozen natural TRAIN-source internal tune and old V6 warmup logits."""
    with zipfile.ZipFile(io.BytesIO(original_bytes(path))) as z:
        source=json.loads(z.read('reader-v5-independent-audit/natural-cases.json'))
        require(set(source)=={'train','tune'} and len(source['train'])==3909 and len(source['tune'])==827,
                'exact historical real MultiRC source roster required')
        rows=source['tune']
        ids=[case_id(r) for r in rows]
        require(len(ids)==len(set(ids))==827 and all(r['source_split']=='train' for r in rows),
                'original 827 internal TRAIN-source labels required')
        groups=sorted(set(r['source_hash'] for r in rows))
        require(len(groups)==16 and len({(r['paragraph_id'],r['question_id']) for r in rows})==194,
                'complete original 16-source 194-question panel required')
        require(set(r['source_hash'] for r in rows).isdisjoint(r['source_hash'] for r in source['train']),
                'separate original TRAIN vs internal-tune source clusters required')
        data={}
        for seed in SEEDS:
            key=f'reader-v6-bridge/seed-{seed}/bridge/warmup-natural-internal.json'
            value=json.loads(z.read(key))
            p=value['probabilities']
            require(value['case_ids']==ids and value['scope']==
                    'old_training_source_internal_tune_not_fresh' and
                    value['threshold_selected'] is False and
                    len(p)==827 and all(type(q) in (int,float) and math.isfinite(q)
                        and 0<=q<=1 for q in p),'genuine historical original logits/probs required')
            data[seed]=tuple(float(q) for q in p)
        return rows,groups,data


def group_folds(groups):
    """Frozen group assignment shared over all seeds; exactly four groups per fold."""
    require(type(groups) in (list,tuple) and len(groups)==16 and len(set(groups))==16,
            'exactly 16 unique source units required')
    g=list(sorted(groups))
    rng=random.Random('hepta-v78-natural-internal-exposed-source-groups-20261015')
    rng.shuffle(g)
    return {source:i%FOLDS for i,source in enumerate(g)}


def scores(labels, predictions, rows):
    """Independently reconstruct official-like candidate F1a and per-question EM."""
    require(len(labels)==len(predictions)==len(rows)>0 and
            all(type(x) is int and x in (0,1) for x in labels+predictions),
            'aligned binary predictions only')
    tp=sum(y==p==1 for y,p in zip(labels,predictions))
    npos=sum(labels)+sum(predictions)
    questions={}
    for y,p,r in zip(labels,predictions,rows):
        key=(r['source_split'],r['paragraph_id'],r['question_id'])
        questions.setdefault(key,[]).append(y==p)
    return dict(candidates=len(labels),questions=len(questions),
                source_groups=len({r['source_hash'] for r in rows}),
                f1_a=2*tp/npos if npos else 0.,
                exact_match=sum(all(v) for v in questions.values())/len(questions),
                accuracy=sum(y==p for y,p in zip(labels,predictions))/len(labels))


def choose_train_threshold(p, labels):
    require(len(p)==len(labels)>0,'nonempty train only threshold data required')
    candidates=[]
    for threshold in (i/20 for i in range(1,20)):
        pred=[int(v>threshold) for v in p]
        tp=sum(a==b==1 for a,b in zip(labels,pred))
        div=sum(labels)+sum(pred)
        f1=2*tp/div if div else 0
        candidates.append((f1,-abs(threshold-.5),-threshold,threshold))
    return max(candidates)[-1]


def logits(p):
    # Read-only historical probabilities; finite, bounded clipping is disclosed.
    tensor=torch.tensor(p,dtype=torch.float32)
    return torch.logit(tensor.clamp(1e-6,1-1e-6))


def fit_scalar_calibrator(train_p,train_y,*,seed):
    """Real PyTorch autograd/Adam on authentic TRAIN-source historical labels."""
    x=logits(train_p)
    y=torch.tensor(train_y,dtype=torch.float32)
    require(len(train_p)==len(train_y)>0 and torch.isfinite(x).all(),
            'finite nonempty authentic train scores required')
    scale=torch.nn.Parameter(torch.zeros((),dtype=torch.float32))  # exp=1
    bias=torch.nn.Parameter(torch.zeros((),dtype=torch.float32))
    optimizer=torch.optim.Adam([scale,bias],lr=.025,foreach=False)
    began=time.process_time_ns()
    for _ in range(UPDATES):
        optimizer.zero_grad(set_to_none=True)
        z=scale.exp()*x+bias
        loss=F.binary_cross_entropy_with_logits(z,y)
        require(bool(torch.isfinite(loss)),'calibrator loss must be finite')
        loss.backward()
        optimizer.step()
    require(bool(torch.isfinite(scale)) and bool(torch.isfinite(bias)),
            'finite scalar output required')
    return dict(log_scale=float(scale.detach()),bias=float(bias.detach()),
                train_ce=float(loss.detach()),cpu_ns=time.process_time_ns()-began,
                optimizer_updates=UPDATES,trainable_parameters=TRAINABLE_SCALARS)


def calibrated(p,params):
    x=logits(p)
    with torch.no_grad():
        pred=torch.sigmoid(math.exp(params['log_scale'])*x+params['bias'])
    return pred.tolist()


def run(original, *, updates=UPDATES):
    require(type(updates) is int and updates==UPDATES,'frozen equal update campaign required')
    torch.set_num_threads(1)
    started=time.process_time_ns()
    rows,groups,original_p=read_original(original)
    assignment=group_folds(groups)
    targets=[r['label'] for r in rows]
    require(all(type(x) is int and x in (0,1) for x in targets),'public natural labels must be binary')
    all_records={}
    for seed in SEEDS:
        p=original_p[seed]
        folds=[]
        oof={arm:[None]*len(rows) for arm in ARMS}
        for f in range(FOLDS):
            tr=[i for i,row in enumerate(rows) if assignment[row['source_hash']]!=f]
            te=[i for i,row in enumerate(rows) if assignment[row['source_hash']]==f]
            require(len(tr)+len(te)==827 and set(tr).isdisjoint(te) and
                    {rows[i]['source_hash'] for i in tr}.isdisjoint(rows[i]['source_hash'] for i in te),
                    'source-group train/holdout leakage')
            trainp=[p[i] for i in tr];trainy=[targets[i] for i in tr]
            t=choose_train_threshold(trainp,trainy)
            trained=fit_scalar_calibrator(trainp,trainy,seed=seed*100+f)
            probs=calibrated([p[i] for i in te],trained)
            selections={
                'frozen':[int(p[i]>.5) for i in te],
                'always_positive':[1 for _ in te],
                'fit_threshold':[int(p[i]>t) for i in te],
                'two_scalar_calibrator':[int(q>.5) for q in probs]
            }
            for arm in ARMS:
                for i,decision in zip(te,selections[arm]):
                    require(oof[arm][i] is None,'duplicate heldout source observation')
                    oof[arm][i]=decision
            folds.append(dict(fold=f,train_cases=len(tr),heldout_cases=len(te),
                train_source_groups=12,heldout_source_groups=4,threshold=t,
                calibrator=dict(trained),train_source_set_sha256=digest(sorted({rows[i]['source_hash'] for i in tr})),
                heldout_source_set_sha256=digest(sorted({rows[i]['source_hash'] for i in te}))))
        require(all(all(type(x) is int for x in decisions) for decisions in oof.values()),
                'complete deterministic source-disjoint out-of-fold census')
        arm_scores={arm:scores(targets,preds,rows) for arm,preds in oof.items()}
        all_records[str(seed)] = dict(folds=folds,arm_metrics=arm_scores,
            oof_prediction_sha256={a:digest(oof[a]) for a in ARMS},
            original_probabilities_sha256=digest(p),
            frozen_original_old_bridge_weights_unchanged=True,
            real_natural_multirc_original_labels_used=True,
            new_granite_forward_calls=0,new_v6_reader_training_updates=0,
            source_disjoint_future_task_verified=False)
    return dict(schema=SCHEMA,status='EXPOSED_SOURCE_CALIBRATION_ONLY',
        original_V6_zip_sha256=V6_SHA,old_natural_tune_source_groups=16,
        original_natural_train_source_groups=64,heldout_group_is_only_already_exposed_training_source=True,
        cases=827,questions=194,source_group_fold_assignment_sha256=digest(assignment),
        seeds=list(SEEDS),arms=list(ARMS),folds=FOLDS,
        steps_per_calibrator=UPDATES,trainable_scalars_per_model=TRAINABLE_SCALARS,
        actual_calibration_fits=3*FOLDS,
        measures=all_records,process_cpu_ns=time.process_time_ns()-started,
        historical_pretrained_logits_used=True,historical_pretrained_Granite_features_not_available=True,
        old_binding_original_weight_update_count=0,
        old_binding_old_route_rerun_verified=False,
        learned_new_1700_head_real_token_task_verified=False,
        future_independent_multirc_verified=False,prospective_old_retention_verified=False,
        original_train_source_panel_exposed_in_v4=True,
        repeated_seeds_are_not_independent_source_groups=True,
        production_authorized=False,cell_split_production_authorized=False,
        native_ndu_admitted=False,model_selected=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-v6-zip',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    require(not args.output.exists() and not args.output.is_symlink(),
            'write-once original exposed-source result required')
    value=run(args.original_v6_zip)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
        stream.flush();os.fsync(stream.fileno())
    print(json.dumps(dict(status=value['status'],fitted=value['actual_calibration_fits'],
                          semantic_future_benchmark=False),sort_keys=True))

if __name__=='__main__':main()
