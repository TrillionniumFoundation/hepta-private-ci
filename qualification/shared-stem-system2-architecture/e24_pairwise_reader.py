#!/usr/bin/env python3
"""Original-MultiRC frozen-Reader pairwise Head experiment; research / DENY_ALL.

Each `fit-one` worker receives ONE actual three-passage E15 train-label owner ZIP,
never the other folds' training labels or human held outcomes. One shared frozen
pretrained E21 archive supplies all answer-specific logits; no pretrained model
is rerun. Two actual 5-parameter float64 SGD alternatives (pointwise and
pairwise+pointwise) use identical training inputs/steps and deterministic init.
The four output artifacts are sealed before a separate owner-scoring process.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import time
from zipfile import ZipFile

MODEL_ZIP_SHA = '1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
OBS_ID = '7e4a0dc4ff48688b1ace0640a3290ee90011487843384a30565b65d3d240e7a5'
VAL_SHA = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
OWNER_SHA = ('cc1c13323cb8377cbd5cdfa5c806796cb85505746e8509f21432d83a1ac4fb2d',
             '8aa9f4b82a4478e9329cba5468adbea4a5a75bd9707b57358eb78a981cf0fd5e',
             'e097d3a3bd210c1b8a84736cc6c219ea2605763c5b83b2c823dd136c00dedec5',
             '8565aa2c841ad067d58e9ca04222247277de509bb4bdac38eb42e7662d13c6b2')
MODEL_KEYS = ('conditioned', 'mean_pool_query_fused', 'no_evidence')
METHODS = ('bce5', 'pairwise5')
STEPS = 80
LR = 0.1
L2 = 0.002
MAX_BYTES = 2_000_000
SCHEMA_FOLD = 'hepta.e24.actual-frozen-reader-pairwise-training-fold.v1'
SCHEMA_COMBINED = 'hepta.e24.original-label-blind-fourfold.v1'

class Denied(ValueError):
    pass

def require(ok, reason):
    if not ok: raise Denied(reason)

def digest(b): return hashlib.sha256(b).hexdigest()

def pairs_unique(pairs):
    d={}
    for k,v in pairs:
        require(k not in d, 'duplicate JSON field');d[k]=v
    return d

def parse(b):
    return json.loads(b,object_pairs_hook=pairs_unique,
        parse_constant=lambda x: (_ for _ in ()).throw(Denied('nonfinite JSON: '+x)))

def raw_zip(path,pin,member):
    p=Path(path)
    require(p.is_file() and not p.is_symlink() and 0<p.stat().st_size<=MAX_BYTES,
            'missing or unbounded zip')
    raw=p.read_bytes();require(digest(raw)==pin,'untrusted ZIP bytes')
    with ZipFile(p) as z:
        names=z.namelist()
        require(len(names)==len(set(names)) and len(names)<=90 and
                all(not x.startswith('/') and '..' not in x.split('/') for x in names) and
                member in names,'ambiguous original model ZIP')
        out=z.read(member)
        require(len(out)<1_000_000,'unbounded original member')
        return out

def logits_to_probability(m):
    require(type(m) is float and math.isfinite(m) and abs(m)<100,'invalid pretrained logit')
    return 1/(1+math.exp(-m)) if m>=0 else math.exp(m)/(1+math.exp(m))

def model(path):
    raw=raw_zip(path,MODEL_ZIP_SHA,'multirc-native-candidate-audit/audit.json')
    seal=parse(raw_zip(path,MODEL_ZIP_SHA,'multirc-native-candidate-audit/COMMITTED.json'))
    obs=parse(raw)
    require(obs.get('observation_id')==OBS_ID and seal.get('observation_sha256')==digest(raw)
            and obs.get('evaluation_labels_loaded') is False and
            obs.get('production_authorized') is False and
            obs.get('actual_candidate_count')==33 and obs.get('question_count')==8 and
            obs.get('passage_count')==4,'unqualified real original MultiRC source')
    meta=obs['rows'];preds=obs['predictions']
    require(type(meta) is list and len(meta)==33 and
            type(preds) is dict and set(MODEL_KEYS)<=set(preds),'bad original model outputs')
    records=[]
    for index,row in enumerate(meta):
        require(type(row) is dict and set(row)=={'task_id','source_group','question_slot',
                                                'candidate_id','original_v1_candidate'},
                'wrong original answer identity')
        v=[]
        for arm in MODEL_KEYS:
            r=preds[arm][index]
            require(r['task_id']==row['task_id'] and
                    r['source_group']==row['source_group'] and
                    r['question_slot']==row['question_slot'], 'pretrained logits identity mismatch')
            logits=r['logits'];require(len(logits)==2,'wrong original logit rank')
            # Retain physical pretrained margin, not a manufactured label.
            v.append(float(logits[1]-logits[0]))
            logits_to_probability(v[-1])
        records.append({**row,'margins':v})
    groups=sorted({r['source_group'] for r in records})
    ids={r['task_id'] for r in records}
    require(len(groups)==4 and len(ids)==33 and len({(r['source_group'],r['question_slot'])
            for r in records})==8 and sum(r['original_v1_candidate'] for r in records)==8,
            'incomplete original 33 answer/8 question source')
    return records,groups,digest(raw)

def training_labels(path,fold,rows,groups):
    require(type(fold) is int and 0<=fold<4, 'invalid original held fold')
    raw=raw_zip(path,OWNER_SHA[fold],f'training-fold-{fold}.json')
    owner=parse(raw)
    require(owner.get('schema')=='hepta.e15.owner-training-only-passage-fold.v1' and
            owner.get('authority')=='DENY_ALL' and owner.get('production_accepted') is False and
            owner.get('held_labels_exposed') is False and owner.get('fold')==fold and
            owner.get('held_group')==groups[fold] and
            owner.get('source_archive_sha256')==MODEL_ZIP_SHA and
            owner.get('original_observation_id')==OBS_ID and
            owner.get('original_validation_human_label_source_sha256')==VAL_SHA,
            'untrusted original three-passage human training owner')
    expected={r['task_id'] for r in rows if r['source_group']!=groups[fold]}
    data=owner.get('training_label_rows')
    require(type(data) is list and len(data)==len(expected),
            'missing original train-fold label rows')
    labels={}
    for x in data:
        require(type(x) is dict and set(x)=={'label','task_id'} and
                type(x['task_id']) is str and x['task_id'] in expected and
                x['task_id'] not in labels and type(x['label']) is int and
                x['label'] in (0,1), 'original train-only label tamper/leak')
        labels[x['task_id']]=x['label']
    require(set(labels)==expected,'missing or additional training source labels')
    return labels,digest(raw)

def question_features(rows,train_ids):
    """Five real-valued features. Center within each question without labels;
    each channel's scale is fitted ONLY on admitted training-source rows.
    """
    q=defaultdict(list)
    for r in rows: q[(r['source_group'],r['question_slot'])].append(r)
    centered={}
    for group in q.values():
        means=[sum(r['margins'][k] for r in group)/len(group) for k in range(3)]
        for r in group:
            centered[r['task_id']]=[r['margins'][k]-means[k] for k in range(3)]
    tr=[r for r in rows if r['task_id'] in train_ids]
    require(len(tr)==len(train_ids) and len(tr)>0,'train-only feature support missing')
    scales=[]
    for k in range(3):
        rms=math.sqrt(sum(centered[r['task_id']][k]**2 for r in tr)/len(tr))
        scales.append(max(rms,1e-8))
    rawmean=sum(r['margins'][1] for r in tr)/len(tr)
    rawstd=max(math.sqrt(sum((r['margins'][1]-rawmean)**2 for r in tr)/len(tr)),1e-8)
    features={}; clipped=0
    for r in rows:
        vals=[centered[r['task_id']][k]/scales[k] for k in range(3)]
        vals.append((r['margins'][1]-rawmean)/rawstd)
        clipped+=sum(abs(v)>12 for v in vals)
        features[r['task_id']]=[1.]+[max(-12.,min(12.,v)) for v in vals]
    return features,{'center_rms_train':scales,'raw_mean_train':rawmean,
                     'raw_std_train':rawstd,'input_feature_clip_count':clipped}

def sigm(z):
    return 1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))

def grad_train(rows,labels,features,method):
    require(method in METHODS,'unregistered training method')
    train=[r for r in rows if r['task_id'] in labels]
    groups=defaultdict(list)
    for r in train: groups[(r['source_group'],r['question_slot'])].append(r)
    pairs=[]
    for qrows in groups.values():
        pos=[features[r['task_id']] for r in qrows if labels[r['task_id']]==1]
        neg=[features[r['task_id']] for r in qrows if labels[r['task_id']]==0]
        for a in pos:
            for b in neg:pairs.append([x-y for x,y in zip(a,b)])
    require(len(pairs)>0 and len(groups)==6,'train-only mixed-pair source census invalid')
    w=[0.]*5
    started=time.process_time_ns()
    for _ in range(STEPS):
        gb=[0.]*5
        for r in train:
            x=features[r['task_id']];d=sigm(sum(a*b for a,b in zip(w,x)))-labels[r['task_id']]
            for j in range(5):gb[j]+=d*x[j]
        gb=[x/len(train) for x in gb]
        if method=='pairwise5':
            gp=[0.]*5
            for dif in pairs:
                d=sigm(sum(a*b for a,b in zip(w,dif)))-1.
                for j in range(5):gp[j]+=d*dif[j]
            gp=[x/len(pairs) for x in gp]
            g=[.3*b+.7*p for b,p in zip(gb,gp)]
        else:g=gb
        for j in range(5):w[j]-=LR*(g[j]+(L2*w[j] if j else 0.))
        require(all(math.isfinite(a) and abs(a)<1e6 for a in w),'nonfinite or unbounded SGD')
    used=time.process_time_ns()-started
    return w,{'train_steps':STEPS,'train_examples':len(train),
              'train_question_pairs':len(pairs), 'train_questions':len(groups),
              'train_cpu_ns':used,'trainable_parameters':5}

def fit_one(model_zip,owner_zip,fold,out):
    rows,groups,rawsha=model(model_zip)
    labels,owner_sha=training_labels(owner_zip,fold,rows,groups)
    f,stats=question_features(rows,set(labels))
    held=[r for r in rows if r['source_group']==groups[fold]]
    res={}
    for method in METHODS:
        w,meters=grad_train(rows,labels,f,method)
        res[method]={'weights':w,'meters':meters,'predictions':[
            {'task_id':r['task_id'],'probability':sigm(sum(a*b for a,b in zip(w,f[r['task_id']]))) }
            for r in held]}
    record={'schema':SCHEMA_FOLD,'authority':'DENY_ALL','production_accepted':False,
            'fold':fold,'held_group':groups[fold],'original_model_zip_sha256':MODEL_ZIP_SHA,
            'original_prelabel_member_sha256':rawsha,'train_only_owner_zip_sha256':OWNER_SHA[fold],
            'train_only_owner_member_sha256':owner_sha,'held_label_accessed':False,
            'new_pretrained_forward_calls':0,'training_updates_per_method':STEPS,
            'train_feature_profile':stats,'methods':res}
    return sealed(out,record)

def sealed(path,record):
    b=(json.dumps(record,sort_keys=True,allow_nan=False,separators=(',',':'))+'\n').encode()
    with Path(path).open('xb') as f:f.write(b)
    return digest(b)

def join(source,fold_paths,out):
    rows,groups,model_member=model(source)
    require(len(fold_paths)==4,'four original held-fold predictions required')
    folds=[];seen=set()
    for i,path in enumerate(fold_paths):
        p=Path(path);require(p.is_file() and p.stat().st_size<100000,'unbounded fold evidence')
        raw=p.read_bytes();r=parse(raw)
        require(type(r) is dict and r.get('schema')==SCHEMA_FOLD and
                r.get('authority')=='DENY_ALL' and r.get('production_accepted') is False and
                r.get('fold')==i and r.get('held_group')==groups[i] and
                r.get('original_model_zip_sha256')==MODEL_ZIP_SHA and
                r.get('original_prelabel_member_sha256')==model_member and
                r.get('held_label_accessed') is False and
                r.get('new_pretrained_forward_calls')==0 and
                set(r.get('methods',{}))==set(METHODS),'unqualified held fold')
        expected={x['task_id'] for x in rows if x['source_group']==groups[i]}
        for method in METHODS:
            prediction=r['methods'][method]['predictions']
            require(type(prediction) is list and len(prediction)==len(expected) and
                    {x['task_id'] for x in prediction}==expected and
                    all(type(x['probability']) is float and 0<x['probability']<1
                        for x in prediction),'missing/invalid true held predictions')
        require(not (seen&expected),'overlapping held source task')
        seen|=expected
        folds.append(r)
    require(seen=={x['task_id'] for x in rows},'incomplete original heldout census')
    return sealed(out,{'schema':SCHEMA_COMBINED,'authority':'DENY_ALL',
            'production_accepted':False,'model_selected':False,
            'evidence_cost_adjusted_gain_established':False,
            'held_human_labels_accessed':False,'new_pretrained_forwards':0,
            'original_model_zip_sha256':MODEL_ZIP_SHA,
            'folds':folds,'original_cases':33,'original_questions':8,'original_passages':4})

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sp=p.add_subparsers(dest='mode',required=True)
    fit=sp.add_parser('fit-one');fit.add_argument('--original',required=True)
    fit.add_argument('--owner',required=True);fit.add_argument('--fold',type=int,required=True)
    fit.add_argument('--out',required=True)
    combine=sp.add_parser('join');combine.add_argument('--original',required=True)
    for j in range(4):combine.add_argument(f'--fold-{j}',required=True)
    combine.add_argument('--out',required=True)
    a=p.parse_args()
    if a.mode=='fit-one':ans=fit_one(a.original,a.owner,a.fold,a.out)
    else:ans=join(a.original,[getattr(a,f'fold_{j}') for j in range(4)],a.out)
    print(ans)

if __name__=='__main__':main()
