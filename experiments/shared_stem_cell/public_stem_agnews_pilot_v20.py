"""Pinned two-pretrained-Encoder / equal-Cell-Head AG News pilot (research only).

- PREPARE downloads only two SHA-256-pinned Parquet datasets, seals the same
  train/test cohorts, and separates heldout input text from heldout targets.
- FIT-PREDICT accepts train labels and heldout SOURCE ONLY; it uses the real
  byte-verified LocalEncoder, a frozen encoder and identical tiny Head budgets.
- EVALUATE is a separate process that alone accepts heldout labels. It reports
  observational pilot metrics, NOT independent time-sealed future utility or
  a real deployed no_change baseline; winner and production are ALWAYS null.

No checkpoint is used as an input to any other untrusted model code. No unsafe
pickle files, fallback checkpoints, remote code or hidden label read in fit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import sys
import tempfile
import time
from collections import Counter

VERSION = 'hepta.stem-real-heldout-agnews.v20'
RESULT = 'hepta.stem-real-heldout-head-arm.v20'
EVALUATION = 'hepta.stem-real-heldout-readout.v20'
DATA_REPO = 'szhuggingface/ag_news'
DATA_REVISION = '98c532231d96ae10e176a909192ecac548949288'
DATA_FILES = {
    'train': ('data/train_1_1.5k-00000-of-00001.parquet',
              'cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5', 249883),
    'heldout': ('data/test-00000-of-00001.parquet',
                '2237e86474314bae6c611718e5bd16a42b4e8dfae53bb4a84abdae1bc1c5d3ee', 1229957),
}
N_CLASSES = 4
TRAIN_PER_CLASS = 32
HELDOUT_PER_CLASS = 16
SEED = 7347
WIDTH = 384
STATE = 64
RANK = 8
STEPS = 64
BATCH = 32
LR = 0.01
CANDIDATES = ('granite-97m-r2', 'mmbert-small')
MAX_TEXT_BYTES = 4096


class PilotError(ValueError):
    pass


def require(flag, msg):
    if not flag:
        raise PilotError(msg)


def canon(obj):
    return (json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,
                       allow_nan=False)+'\n').encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest_file(path: Path, *, maximum=8*1024*1024):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=maximum,
            'missing, linked or unbounded source')
    h=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block);size+=len(block)
            require(size<=maximum,'unbounded source read')
    return h.hexdigest(),size


def strict_json(path:Path, maximum=128*1024):
    digest_file(path,maximum=maximum)
    def unique(pairs):
        out={}
        for k,v in pairs:
            require(k not in out,'duplicate JSON field')
            out[k]=v
        return out
    x=json.loads(path.read_bytes(),object_pairs_hook=unique,
                 parse_constant=lambda x:(_ for _ in ()).throw(PilotError('nonfinite JSON')))
    require(type(x) is dict and path.read_bytes()==canon(x),'noncanonical JSON document')
    return x


def read_rows(path:Path, expected_sha:str, *, limit:int, fields:set[str]):
    actual,_=digest_file(path,maximum=2*1024*1024)
    require(actual==expected_sha,'frozen row file digest drift')
    lines=path.read_bytes().splitlines(keepends=True)
    require(0<len(lines)<=limit,'invalid frozen row count')
    result=[];ids=[]
    for line in lines:
        row=json.loads(line)
        require(type(row) is dict and set(row)==fields and line==canon(row),
                'noncanonical source row or unexpected label')
        ident=row['case_id']
        require(type(ident) is str and len(ident)==23,'invalid case identity')
        ids.append(ident)
        if 'text' in row:
            require(type(row['text']) is str and 1<=len(row['text'].encode())<=MAX_TEXT_BYTES,
                    'unbounded text')
        if 'label' in row:
            require(type(row['label']) is int and 0<=row['label']<N_CLASSES,
                    'invalid class label')
        result.append(row)
    require(ids==sorted(set(ids)),'duplicate or unordered case IDs')
    return result


def select_balanced(rows:list, *, phase:str, per_class:int, used:set[str]|None=None):
    require(phase in ('train','heldout') and 1<=per_class<=64,'invalid phase/sample size')
    used=set() if used is None else set(used)
    buckets={j:[] for j in range(N_CLASSES)}
    for row in rows:
        require(type(row) is dict and set(row)=={'text','label'},'unsupported dataset schema')
        text,label=row['text'],row['label']
        require(type(text) is str and 1<=len(text.encode('utf8'))<=MAX_TEXT_BYTES,
                'empty or oversized dataset text')
        require(type(label) is int and 0<=label<N_CLASSES,'invalid dataset class')
        identity=sha(text.encode('utf8'))
        if identity in used: continue
        # Duplicate texts cannot appear twice, even under different labels.
        buckets[label].append((sha(canon([SEED,phase,identity])),identity,text,label))
    chosen=[]
    for label in range(N_CLASSES):
        occupied=set()
        for order,ident,text,y in sorted(buckets[label]):
            if ident in occupied or ident in used:continue
            chosen.append((ident,text,y));occupied.add(ident);used.add(ident)
            if len(occupied)>=per_class:break
        require(len(occupied)==per_class,'too few nonduplicate examples per class')
    return sorted(chosen,key=lambda x:x[0]),used


def to_cohorts(train_raw:list,heldout_raw:list):
    train,seen=select_balanced(train_raw,phase='train',per_class=TRAIN_PER_CLASS)
    test,_=select_balanced(heldout_raw,phase='heldout',per_class=HELDOUT_PER_CLASS,used=seen)
    train_rows=[dict(case_id='tr-'+key[:20],text=text,label=label)
                for key,text,label in train]
    test_sources=[dict(case_id='te-'+key[:20],text=text) for key,text,_ in test]
    test_targets=[dict(case_id='te-'+key[:20],label=label) for key,_,label in test]
    require({r['text'] for r in train_rows}.isdisjoint({r['text'] for r in test_sources}),
            'train/heldout text leakage')
    require(len(train_rows)==128 and len(test_sources)==64,'matched sample count')
    return train_rows,test_sources,test_targets


def jsonl(rows):
    return b''.join(canon(x) for x in rows)


def make_plan(train_rows, test_sources,test_targets,files):
    for phase in ('train','heldout'):
        require(set(files[phase])=={'sha256','bytes'},'incomplete dataset file fingerprint')
    return dict(schema=VERSION,source=DATA_REPO,revision=DATA_REVISION,
                original_files=files,train_sha256=sha(jsonl(train_rows)),
                heldout_source_sha256=sha(jsonl(test_sources)),
                heldout_targets_sha256=sha(jsonl(test_targets)),
                train_count=len(train_rows),heldout_count=len(test_sources),
                classes=N_CLASSES,feature_width=WIDTH,state_dim=STATE,
                rank=RANK,seed=SEED,steps=STEPS,batch=BATCH,lr=LR,
                candidates=list(CANDIDATES),
                dataset_temporal_future=False,independent_no_change_verified=False,
                production_accepted=False,authority='DENY_ALL')


def checked_plan(plan:dict):
    require(type(plan) is dict and set(plan)=={
        'schema','source','revision','original_files','train_sha256','heldout_source_sha256',
        'heldout_targets_sha256','train_count','heldout_count','classes','feature_width',
        'state_dim','rank','seed','steps','batch','lr','candidates','dataset_temporal_future',
        'independent_no_change_verified','production_accepted','authority'},'unexpected plan fields')
    require(plan['schema']==VERSION and plan['source']==DATA_REPO
            and plan['revision']==DATA_REVISION and plan['classes']==N_CLASSES
            and plan['train_count']==TRAIN_PER_CLASS*N_CLASSES
            and plan['heldout_count']==HELDOUT_PER_CLASS*N_CLASSES
            and plan['feature_width']==WIDTH and plan['state_dim']==STATE
            and plan['rank']==RANK and plan['seed']==SEED and plan['steps']==STEPS
            and plan['batch']==BATCH and plan['lr']==LR
            and plan['candidates']==list(CANDIDATES),'experiment budget drift')
    require(plan['dataset_temporal_future'] is False
            and plan['independent_no_change_verified'] is False
            and plan['production_accepted'] is False and plan['authority']=='DENY_ALL',
            'cannot claim independent utility or production')
    for key in ('train_sha256','heldout_source_sha256','heldout_targets_sha256'):
        value=plan[key]
        require(type(value) is str and len(value)==64
                and all(s in '0123456789abcdef' for s in value),'invalid exact source digest')
    for p,(name,expected,size) in DATA_FILES.items():
        observed=plan['original_files'].get(p)
        require(type(observed) is dict and observed=={'sha256':expected,'bytes':size},
                'unreviewed original dataset material')
    return plan


def output_dir(path:Path, raw:dict[str,bytes]):
    require(not path.exists() and not path.is_symlink() and path.parent.is_dir()
            and not path.parent.is_symlink(),'new output directory required')
    with tempfile.TemporaryDirectory(prefix='.stem-v20-',dir=path.parent) as tmp:
        stage=Path(tmp)
        for name,payload in raw.items():
            require('/' not in name and name not in ('.','..'),'invalid output path')
            with (stage/name).open('xb') as f:
                f.write(payload);f.flush();os.fsync(f.fileno())
        os.rename(stage,path)
        d=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(d)
        finally:os.close(d)


def stage_verified_hub_file(downloaded:Path, stage:Path, expected_sha:str, expected_size:int):
    """Convert a Hub cache symlink into bounded, verified regular material.

    hf_hub_download may legitimately return a symlink to a cache blob; rejecting
    it before following its bytes would reject the official dataset despite its
    preregistered SHA. Never trust path identity: verify the *copied bytes*.
    """
    require(isinstance(downloaded,Path) and downloaded.is_file()
            and stage.parent.is_dir() and not stage.exists()
            and 0<expected_size<=8*1024*1024, 'unavailable pinned Hub cache material')
    length=0;digest=hashlib.sha256()
    with downloaded.open('rb') as source,stage.open('xb') as target:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            length+=len(chunk)
            require(length<=expected_size,'dataset copy exceeds preregistered size')
            digest.update(chunk)
            target.write(chunk)
        target.flush();os.fsync(target.fileno())
    require(length==expected_size and digest.hexdigest()==expected_sha,
            'downloaded Parquet source differs from immutable SHA256')
    require(digest_file(stage)==(expected_sha,expected_size),
            'staged Parquet bytes differ from download')
    return stage


def prepare(out:Path):
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    reports={}; cohorts={}
    for phase,(filename,expected,size) in DATA_FILES.items():
        downloaded=Path(hf_hub_download(repo_id=DATA_REPO,repo_type='dataset',
                       filename=filename,revision=DATA_REVISION,token=False))
        # HF's own cache may expose an immutable blob through a symlink.
        # Stage a regular, newly-created copy and check *actual bytes* first.
        with tempfile.TemporaryDirectory(prefix='.agnews-v20-',dir=out.parent) as work:
            local=stage_verified_hub_file(downloaded,Path(work)/Path(filename).name,
                                          expected,size)
            table=pq.read_table(local,columns=['text','label'])
            raw=table.to_pylist()
        actual,count=expected,size
        require((phase=='train' and len(raw)==1500) or
                (phase=='heldout' and len(raw)==7600),'dataset cohort cardinality drift')
        reports[phase]={'sha256':actual,'bytes':count}
        cohorts[phase]=raw
    train,sources,targets=to_cohorts(cohorts['train'],cohorts['heldout'])
    plan=checked_plan(make_plan(train,sources,targets,reports))
    output_dir(out,{'plan.json':canon(plan),'train.jsonl':jsonl(train),
                    'heldout-source.jsonl':jsonl(sources),
                    'heldout-targets.jsonl':jsonl(targets)})
    return plan


def profile_binding(profile:dict, summary:dict, candidate:str):
    from public_stem_material_v8 import CATALOG,PINNED_RELEASES
    require(candidate in CANDIDATES,'unregistered model candidate')
    spec=CATALOG[candidate]
    require(type(profile) is dict and profile.get('candidate')==candidate
            and profile.get('expected_width')==WIDTH
            and profile.get('pooling')==spec['pooling']
            and profile.get('normalization')==spec['normalization'],
            'native model feature policy changed')
    m=profile.get('snapshot')
    require(type(m) is dict and m.get('kind')==spec['kind']
            and m.get('revision')==PINNED_RELEASES[candidate]
            and type(m.get('files')) is dict,'public model source drift')
    require(type(summary) is dict and summary.get('schema')=='hepta.public-stem-material-pair-handoff.v10'
            and summary.get('research_pair_self_consistent') is True
            and summary.get('two_material_directories_rehashed') is True
            and summary.get('no_change_baseline_executed') is False
            and summary.get('production_accepted') is False
            and summary.get('authority')=='DENY_ALL','missing nonauthorizing pair gate')
    pins=summary.get('candidate_profiles',{}).get(candidate)
    require(type(pins) is dict and pins.get('profile_sha256')==sha(canon(profile)),
            'profile not bound to actual paired physical model')
    return m


def head_train(features, labels, *, seed:int,shuffle_labels:bool):
    import torch
    from torch.nn import functional as F
    from multimodal_head import StateGatedCellHead
    require(isinstance(features,torch.Tensor) and features.ndim==2
            and features.shape[1]==WIDTH and features.dtype==torch.float32
            and torch.isfinite(features).all().item(), 'invalid frozen features')
    require(type(labels) is list and len(labels)==len(features)
            and all(type(y) is int and 0<=y<N_CLASSES for y in labels),
            'invalid training targets')
    torch.manual_seed(seed)
    model=StateGatedCellHead(WIDTH,STATE,RANK,N_CLASSES)
    opt=torch.optim.AdamW(model.parameters(),lr=LR,weight_decay=0.0)
    targets=list(labels)
    if shuffle_labels:
        random.Random(seed+1234).shuffle(targets)
        require(targets!=labels,'shuffled label control did not change target order')
    targets=torch.tensor(targets,dtype=torch.long)
    state=torch.zeros((len(features),STATE),dtype=torch.float32)
    gen=torch.Generator(device='cpu').manual_seed(seed+73)
    for _ in range(STEPS):
        idx=torch.randperm(len(features),generator=gen)[:BATCH]
        logits=model(features[idx],state[idx]);loss=F.cross_entropy(logits,targets[idx])
        require(bool(torch.isfinite(loss).item()),'nonfinite Head learning loss')
        opt.zero_grad(set_to_none=True);loss.backward();opt.step()
    model.eval()
    return model,float(loss.detach().item())


def encode_rows(encoder, rows, native, *, batch=8):
    import torch
    spec=native
    collected=[]
    for start in range(0,len(rows),batch):
        batch_rows=rows[start:start+batch]
        value=encoder.encode([x['text'] for x in batch_rows],pooling=spec['pooling'])
        require(type(value) is torch.Tensor and tuple(value.shape)==(len(batch_rows),WIDTH)
                and value.dtype==torch.float32 and torch.isfinite(value).all().item(),
                'nonphysical or mismatched frozen Encoder feature')
        if spec['normalization']=='unit_l2':
            norm=torch.linalg.vector_norm(value,dim=1,keepdim=True)
            require(bool(torch.isfinite(norm).all().item()) and bool((norm>0).all().item()),
                    'missing native L2 normalization')
            value=value/norm
        collected.append(value.detach().clone())
    return torch.cat(collected,dim=0).contiguous()


def fit_predict(plan:dict, train:list,heldout:list,profile:dict,summary:dict,
                model_root:Path,candidate:str):
    import torch
    import psutil
    from safetensors.torch import save as safetensors_save
    from execution import LocalEncoder
    from public_stem_material_v8 import CATALOG
    checked_plan(plan)
    snapshot=profile_binding(profile,summary,candidate)
    require(len(train)==plan['train_count'] and len(heldout)==plan['heldout_count'],
            'unmatched experiment cohorts')
    started=time.perf_counter_ns();cpu_start=time.process_time_ns()
    torch.set_num_threads(2)
    encoder=LocalEncoder(model_root,snapshot,maximum_tokens=profile['maximum_tokens'])
    native=CATALOG[candidate]
    x=encode_rows(encoder,train,native);y=encode_rows(encoder,heldout,native)
    observed_forward_calls=encoder.forward_calls
    expected=(len(train)+len(heldout)+7)//8
    require(observed_forward_calls==expected,'physical forward count differs from budget')
    encoder.close()
    del encoder
    m,loss=head_train(x,[r['label'] for r in train],seed=plan['seed'],shuffle_labels=False)
    shuffle,shuf_loss=head_train(x,[r['label'] for r in train],seed=plan['seed'],shuffle_labels=True)
    with torch.no_grad():
        state=torch.zeros((len(y),STATE))
        probabilities=m(y,state).softmax(-1).tolist()
        negative=shuffle(y,state).softmax(-1).tolist()
    for collection in (probabilities,negative):
        require(len(collection)==len(heldout) and all(len(p)==N_CLASSES
                and all(math.isfinite(v) and 0<=v<=1 for v in p)
                and abs(math.fsum(p)-1)<1e-5 for p in collection),
                'nonnormalized or missing heldout prediction')
    def head_bytes(model):
        return safetensors_save({k:v.detach().cpu().contiguous()
                                 for k,v in model.state_dict().items()})
    head,shuf_head=head_bytes(m),head_bytes(shuffle)
    nparams=m.parameter_count(); require(nparams==shuffle.parameter_count(),'unmatched Head capacity')
    proc=psutil.Process()
    obs={'wall_ns':time.perf_counter_ns()-started,
         'cpu_ns':time.process_time_ns()-cpu_start,
         'process_rss_after_bytes':proc.memory_info().rss,
         'process_lifetime_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
         'model_forwards':observed_forward_calls,
         'head_steps_per_arm':STEPS,
         'trained_head_parameters':nparams,
         'energy_joules':None,
         'resource_receipt_independently_attested':False}
    predictions=[{'case_id':r['case_id'],'probabilities':p} for r,p in zip(heldout,probabilities)]
    negative_predictions=[{'case_id':r['case_id'],'probabilities':p} for r,p in zip(heldout,negative)]
    result={'schema':RESULT,'candidate':candidate,
            'train_sha256':plan['train_sha256'],
            'heldout_source_sha256':plan['heldout_source_sha256'],
            'plan_sha256':sha(canon(plan)),
            'model_profile_sha256':sha(canon(profile)),
            'model_snapshot_sha256':sha(canon(snapshot)),
            'head_sha256':sha(head),'shuffled_head_sha256':sha(shuf_head),
            'head_parameters':nparams,'steps':STEPS,'seed':SEED,
            'train_loss_last_step':loss,'shuffled_train_loss_last_step':shuf_loss,
            'execution':obs,'predictions':predictions,
            'shuffled_predictions':negative_predictions,
            'holdout_targets_seen_by_producer':False,
            'deployed_no_change_verified':False,
            'production_accepted':False,'authority':'DENY_ALL'}
    return result,head,shuf_head


def _score(values,truth):
    require(len(values)==len(truth) and len(values)>0,'incomplete heldout prediction coverage')
    right=0;bs=0.0;ls=0.0;class_totals=[0]*N_CLASSES;class_hits=[0]*N_CLASSES
    bins=[[] for _ in range(10)]
    for p,y in zip(values,truth):
        require(type(p) is list and len(p)==N_CLASSES
                and all(type(x) in (int,float) and math.isfinite(x) and 0<=x<=1 for x in p)
                and abs(math.fsum(p)-1)<1e-5,'invalid heldout probability vector')
        pred=max(range(N_CLASSES),key=lambda k:(p[k],-k))
        correct=int(pred==y)
        right+=correct;class_totals[y]+=1;class_hits[y]+=correct
        bs+=math.fsum((p[k]-int(y==k))**2 for k in range(N_CLASSES))
        ls+=-math.log(max(1e-12,p[y]))
        conf=max(p);bins[min(9,int(conf*10))].append((conf,correct))
    n=len(truth)
    ece=math.fsum(len(b)*abs(math.fsum(x[0] for x in b)/len(b)-math.fsum(x[1] for x in b)/len(b))
                  for b in bins if b)/n
    return {'cases':n,'accuracy':right/n,'multiclass_brier':bs/n,
            'log_loss':ls/n,'ece_10':ece,
            'recall_by_class':[hits/total if total else None
                               for hits,total in zip(class_hits,class_totals)]}


def evaluate(plan, targets:list, documents:dict):
    checked_plan(plan)
    require(type(documents) is dict and set(documents)==set(CANDIDATES),
            'both exact pretrained Head prediction files required')
    require(len(targets)==plan['heldout_count'],'incomplete heldout targets')
    require(sha(jsonl(targets))==plan['heldout_targets_sha256'],
            'heldout targets changed after precommitment')
    cases=[row['case_id'] for row in targets]
    require(cases==sorted(set(cases)),'heldout targets not canonical')
    labels=[row['label'] for row in targets]
    report={};snapshot_hashes=[]
    for candidate in CANDIDATES:
        r=documents[candidate]
        require(type(r) is dict and r.get('schema')==RESULT and r.get('candidate')==candidate,
                'mismatched candidate result')
        for key in ('train_sha256','heldout_source_sha256'):
            require(r.get(key)==plan[key],'training/heldout source identity drift')
        require(r.get('plan_sha256')==sha(canon(plan)) and r.get('seed')==SEED
                and r.get('steps')==STEPS
                and r.get('holdout_targets_seen_by_producer') is False
                and r.get('deployed_no_change_verified') is False
                and r.get('production_accepted') is False and r.get('authority')=='DENY_ALL',
                'model result claims untrusted effect/authority')
        require(type(r.get('head_parameters')) is int and r['head_parameters']>0
                and type(r.get('execution')) is dict
                and r['execution'].get('trained_head_parameters')==r['head_parameters']
                and type(r.get('model_snapshot_sha256')) is str
                and len(r['model_snapshot_sha256'])==64,
                'mismatched parameter budget or model identity')
        snapshot_hashes.append(r['model_snapshot_sha256'])
        for key in ('predictions','shuffled_predictions'):
            observed=r.get(key)
            require(type(observed) is list and all(type(x) is dict
                    and set(x)=={'case_id','probabilities'} for x in observed)
                    and [x['case_id'] for x in observed]==cases,
                    'mismatched or incomplete heldout prediction census')
        trained=[x['probabilities'] for x in r['predictions']]
        random_control=[x['probabilities'] for x in r['shuffled_predictions']]
        report[candidate]={'trained_head':_score(trained,labels),
                           'shuffled_label_negative_control':_score(random_control,labels),
                           'declared_resource_observation':r['execution'],
                           'profile_sha256':r['model_profile_sha256'],
                           'snapshot_sha256':r['model_snapshot_sha256']}
    require(report[CANDIDATES[0]]['declared_resource_observation']['trained_head_parameters']
            ==report[CANDIDATES[1]]['declared_resource_observation']['trained_head_parameters'],
            'Head parameter budgets differ')
    require(len(set(snapshot_hashes))==len(CANDIDATES),
            'same checkpoint may not impersonate both public model families')
    # Separate independent evaluator sees true heldout labels; the Head
    # producer never receives them. All paired statistics are EXPLORATORY.
    from public_stem_paired_uncertainty_v21 import paired_posthoc
    paired = paired_posthoc(
        targets,
        {name: documents[name]['predictions'] for name in CANDIDATES},
        plan_sha256=sha(canon(plan)),
        target_sha256=plan['heldout_targets_sha256'],
    )
    uniform=_score([[1/N_CLASSES]*N_CLASSES for _ in labels],labels)
    return {'schema':EVALUATION,'dataset':DATA_REPO,'dataset_commit':DATA_REVISION,
            'source_plan_sha256':sha(canon(plan)),
            'heldout_targets_sha256':plan['heldout_targets_sha256'],
            'candidate_reports':report,'paired_exploratory_posthoc':paired,
            'uniform_reference_not_no_change':uniform,
            'deployed_no_change_baseline_observed':False,
            'time_sealed_independent_future_utility':False,
            'selection_permitted':False,'winner':None,
            'independent_ndu_verified':False,
            'source_publisher_signature_verified':False,
            'production_accepted':False,'authority':'DENY_ALL'}


def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('prepare');p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('fit-predict')
    for name in ('plan','train','heldout-source','pair-summary','profile','model-root','out'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--candidate',choices=CANDIDATES,required=True)
    p=sub.add_parser('evaluate')
    for name in ('plan','heldout-targets','mmbert-result','granite-result','out'):
        p.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args(argv)
    try:
        if a.cmd=='prepare':
            prepare(a.out)
            print('PINNED_REAL_AG_NEWS_TRAIN_HELDOUT_SEALED_RESEARCH_ONLY')
        elif a.cmd=='fit-predict':
            plan=checked_plan(strict_json(a.plan))
            train=read_rows(a.train,plan['train_sha256'],limit=128,
                            fields={'case_id','text','label'})
            heldout=read_rows(a.heldout_source,plan['heldout_source_sha256'],limit=64,
                              fields={'case_id','text'})
            require({sha(x['text'].encode()) for x in train}.isdisjoint(
                    {sha(x['text'].encode()) for x in heldout}),
                    'train/heldout text duplicate')
            r,head,negative=fit_predict(plan,train,heldout,
                                        strict_json(a.profile),strict_json(a.pair_summary),
                                        a.model_root,a.candidate)
            output_dir(a.out,{'candidate-result.json':canon(r),
                              'head.safetensors':head,
                              'shuffled-control-head.safetensors':negative})
            print('REAL_PRETRAINED_HEAD_HELDOUT_PREDICTIONS_RESEARCH_ONLY',a.candidate)
        else:
            plan=checked_plan(strict_json(a.plan))
            labels=read_rows(a.heldout_targets,plan['heldout_targets_sha256'],
                             limit=64,fields={'case_id','label'})
            result=evaluate(plan,labels,{
                'mmbert-small':strict_json(a.mmbert_result, maximum=3*1024*1024),
                'granite-97m-r2':strict_json(a.granite_result,maximum=3*1024*1024)})
            output_dir(a.out,{'readout.json':canon(result)})
            print('ACTUAL_PUBLIC_HELDOUT_PILOT_REPORT_NO_WINNER_NO_NDU')
    except (PilotError, OSError, ValueError, KeyError, TypeError) as error:
        print(f'PUBLIC_STEM_V20_PILOT_REFUSED: {type(error).__name__}: {str(error)[:300]}',file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':raise SystemExit(cli())
