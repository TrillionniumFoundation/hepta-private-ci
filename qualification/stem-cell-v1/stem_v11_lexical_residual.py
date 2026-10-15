"""Research V11: train-only lexical-anchored residual atop original frozen MiniLM.

Ranks 829 ORIGINAL heldout LoCoMo questions without publisher labels; an entirely
separate score process reads original publisher weak labels AFTER answer/source seal.
No new encoder forward, model promotion, independent semantic answer or final use.
"""
from __future__ import annotations
import argparse
import os
import hashlib
import json
import math
from pathlib import Path
import resource
import time


from stem_v9_original_continual import (HELD, NEW, OLD, SCHEMA as V9_SCHEMA,
    lexical_bm25, weak_gold, file_sha)

SCHEMA = 'hepta.stem.v11.original-minilm-lexical-residual.shadow.v1'
PINS = {
    'source-only.json':'1cb2d1d7194137cdea48ef8a13e8002c6612a9c98a1ffa71e28e7263c61bf84c',
    'train-only-labels.json':'bdaf2c7a829f26cb147cdfa60c76ef09d23d448f6548d488030843077b5a0ee0',
    'original-predictions.json':'df05ec7906d58834cf7856a0dce4dc77f6b639c0a7c910c88d49cb191f1cd01c',
}
WEIGHTS = '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
SEEDS=(41,47,53)
TOP=3
CANDIDATES=16
STEPS=300


def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def stable_dump(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'

def sealed_create(path:Path,value):
    with path.open('xb') as file:
        file.write(stable_dump(value))
        file.flush()
        os.fsync(file.fileno())


def read_pinned(root:Path,name:str):
    p=root/name
    if not p.is_file() or p.is_symlink() or file_sha(p)!=PINS[name]:
        raise ValueError('missing or changed ORIGINAL V9 research material: '+name)
    return json.loads(p.read_bytes())


def load_original(root:Path):
    import torch
    import numpy as np
    src=read_pinned(root,'source-only.json')
    labels=read_pinned(root,'train-only-labels.json')
    original=read_pinned(root,'original-predictions.json')
    pre=json.loads((root/'precommit.json').read_bytes())
    if (src.get('schema')!=V9_SCHEMA+'.source-only'
        or src.get('source_contains_publisher_gold') is not False
        or labels.get('schema')!=V9_SCHEMA+'.train-only-gold'
        or labels.get('heldout_labels_present') is not False
        or original.get('heldout_publisher_gold_not_read') is not True
        or pre.get('weights_sha256')!=WEIGHTS or pre.get('heldout_gold_admitted') is not False
        or pre.get('source_sha256')!=PINS['source-only.json']
        or pre.get('train_sha256')!=PINS['train-only-labels.json']
        or pre.get('families_heldout')!=list(HELD)
        or pre.get('families_old')!=list(OLD)
        or pre.get('families_new')!=list(NEW)):
        raise ValueError('V9 original source/train/precommit lineage changed')
    p=root/'private-vectors.npy'
    if not p.is_file() or p.is_symlink() or p.stat().st_size>15_000_000:raise ValueError('invalid original private features')
    values=np.load(p,allow_pickle=False)
    if values.dtype!=np.float32 or values.shape!=(7868,384) or not np.isfinite(values).all():
        raise ValueError('original material tensor shape or values wrong')
    records=[]
    for fam in sorted(src['families']):
        a=src['families'][fam]
        records.extend(fam+'/'+d['id'] for d in a['passages'])
        records.extend(q['id'] for q in a['questions'])
    if len(records)!=7868 or len(set(records))!=len(records):raise ValueError('original feature index identity changed')
    receipt_path=root/'physical-receipt.json'
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError('missing genuine original encoder/Head receipt')
    v9_receipt=json.loads(receipt_path.read_bytes())
    if (v9_receipt.get('private_feature_matrix_sha256')!=sha(values.tobytes())
        or v9_receipt.get('original_model_sha256')!=WEIGHTS
        or v9_receipt.get('actual_original_encoder_forward_batches')!=492
        or v9_receipt.get('source_sha256')!=PINS['source-only.json']):
        raise ValueError('original physically loaded feature provenance mismatch')
    if (pre['source_sha256']!=PINS['source-only.json']
        or set(original.get('rankings',{}))!={q['id'] for fam in HELD for q in src['families'][fam]['questions']}):
        raise ValueError('missing original heldout inventory')
    return src,labels,original,dict(zip(records,torch.from_numpy(values.copy()).unbind(0),strict=True)),sha(values.tobytes())


def rank_features(question,docs,q_vec,matrix):
    """Complete-source retrieval first, then bounded union; no labels used."""
    import torch
    bm=lexical_bm25(question,docs)
    dense=(matrix@q_vec).tolist()
    if any(not math.isfinite(x) for x in bm+dense):raise ValueError('nonfinite original features')
    n=len(docs)
    order_b=sorted(range(n),key=lambda i:(-bm[i],docs[i]['id']))
    order_d=sorted(range(n),key=lambda i:(-dense[i],docs[i]['id']))
    rank_b={i:k for k,i in enumerate(order_b)}
    rank_d={i:k for k,i in enumerate(order_d)}
    idx=sorted(set(order_b[:CANDIDATES]+order_d[:CANDIDATES]))
    # A candidate never sees publisher labels; rank features depend only on input.
    denom_b=max(max(bm),1e-9)
    features=torch.tensor([[1/(1+rank_b[i]),1/(1+rank_d[i]),
                            bm[i]/denom_b,dense[i]] for i in idx],dtype=torch.float32)
    return idx,features,order_b,order_d,rank_b,rank_d


def make_roster(src,train,vecs,families,*,heldout=False):
    import torch
    cases=[]
    for fam in families:
        a=src['families'][fam]
        docs=a['passages']
        mat=torch.stack([vecs[fam+'/'+doc['id']] for doc in docs]); ids=[d['id'] for d in docs]
        for question in a['questions']:
            qid=question['id']; idx,x,order_b,order_d,rb,rd=rank_features(question['text'],docs,vecs[qid],mat)
            if heldout:
                positives=None
            else:
                positives=set(train['labels'][qid]);
            cases.append((fam,qid,ids,idx,x,order_b,order_d,rb,rd,positives))
    return cases


class Residual:
    """31 trainable parameters; explicit BM25 rank anchor, bounded +/-0.4 residual."""
    def __init__(self,seed):
        import torch
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.layer1=torch.nn.Linear(4,5)
            self.layer2=torch.nn.Linear(5,1)
            torch.nn.init.zeros_(self.layer2.weight)
            torch.nn.init.zeros_(self.layer2.bias)
        self.params=list(self.layer1.parameters())+list(self.layer2.parameters())
        if sum(p.numel() for p in self.params)!=31:
            raise ValueError('residual Head tensor count changed')
    def __call__(self,x):
        import torch
        return x[:,0]+0.4*torch.tanh(self.layer2(torch.tanh(self.layer1(x))).squeeze(-1))
    def head_sha(self):
        import torch
        return sha(b''.join(p.detach().cpu().float().contiguous().numpy().tobytes() for p in self.params))


def train_residual(cases,seed):
    import torch
    relevant=[];omitted=0
    for fam,qid,ids,idx,x,ob,od,rb,rd,gold in cases:
        if not gold:continue
        pos=torch.tensor([ids[i] in gold for i in idx],dtype=torch.bool)
        if not pos.any():omitted+=1;continue
        relevant.append((x,pos))
    if len(relevant)<200:raise ValueError('not enough original TRAIN-only annotated candidates')
    model=Residual(seed)
    opt=torch.optim.Adam(model.params,lr=0.005,foreach=False)
    rng=torch.Generator().manual_seed(seed ^ 0xAA42)
    t0=time.process_time()
    losses=[]
    for step in range(STEPS):
        pick=int(torch.randint(len(relevant),(1,),generator=rng))
        x,pos=relevant[pick]
        s=model(x)
        loss=torch.logsumexp(s,0)-torch.logsumexp(s[pos],0)
        if not torch.isfinite(loss):raise ValueError('nonfinite original training loss')
        opt.zero_grad(set_to_none=True);loss.backward();opt.step()
        if step in (0,STEPS-1):losses.append(float(loss.detach()))
    return model,dict(seed=seed,physical_updates=STEPS,case_exposures=STEPS,
                      train_label_available=len(relevant),train_candidate_missing=omitted,
                      parameters=31,head_sha256=model.head_sha(),
                      first_last_loss=losses,training_cpu_seconds=time.process_time()-t0)


def choose(case,model):
    import torch
    fam,qid,ids,idx,x,order_b,order_d,rb,rd,_=case
    with torch.inference_mode():
        pred=model(x).tolist()
    order=sorted(range(len(idx)),key=lambda j:(-pred[j],ids[idx[j]]))
    head=[ids[idx[j]] for j in order[:TOP]]
    original=[ids[i] for i in order_b[:TOP]]
    if len(set(head))!=3 or len(set(original))!=3:raise ValueError('invalid Top3')
    safe2=original[:2]+[next(s for s in head+[ids[i] for i in order_b] if s not in original[:2])]
    return head,safe2


def rank(root:Path,out:Path):
    import torch
    full_cpu_start=time.process_time()
    if out.exists() or out.is_symlink():raise FileExistsError('V11 results create-only')
    torch.set_num_threads(1)
    src,train,original,vecs,vec_sha=load_original(root)
    old=make_roster(src,train,vecs,OLD+NEW)
    test=make_roster(src,train,vecs,HELD,heldout=True)
    if len(test)!=829:raise ValueError('full original heldout denominator changed')
    plan={'schema':SCHEMA+'.precommit','v9_original_sha256':PINS,
          'vector_float_sha256':vec_sha,'candidate_bm25':CANDIDATES,
          'candidate_dense':CANDIDATES,'top_k':3,'seeds':list(SEEDS),
          'original_train_only_labels':True,'heldout_labels_read':False,
          'training_steps_per_seed':STEPS,'future_calendar_windows':0,
          'reader_calls':0,'production_authorized':False}
    out.mkdir(parents=True)
    sealed_create(out/'plan.json',plan)  # pre-attempt, before ANY optimizer updates
    result={'schema':SCHEMA+'.sealed-predictions','plan_sha256':sha(stable_dump(plan)),
            'original_v9_predictions_sha256':PINS['original-predictions.json'],
            'labels_read_before_seal':False,'production_authorized':False,'predictions':{}}
    start=time.process_time();physical=[]
    for seed in SEEDS:
        model,train_receipt=train_residual(old,seed)
        physical.append(train_receipt)
        for case in test:
            qid=case[1];head,safe2=choose(case,model)
            row=result['predictions'].setdefault(qid,{})
            row[f'seed{seed}/residual']=head
            row[f'seed{seed}/safe_two']=safe2
    for case in test:
        qid=case[1];row=result['predictions'][qid]
        baseline=original['rankings'][qid]['bm25_full']
        if baseline!=[case[2][j] for j in case[5][:3]]:raise ValueError('BM25 exact original lineage mismatch')
        row['bm25_full']=baseline
        row['dense_full']=original['rankings'][qid]['dense_full']
    receipt={'schema':SCHEMA+'.physical-train-receipt','plan_sha256':result['plan_sha256'],
             'prediction_sha256':sha(stable_dump(result)),'original_encoder_batch_forwards_reused':492,
             'new_encoder_batch_forwards':0,'new_model_weights_loaded':False,
             'private_original_feature_sha256':vec_sha,'physical_31param_heads':physical,
             'process_cpu_seconds_after_feature_roster':time.process_time()-start,
             'full_run_process_cpu_seconds_excluding_original_V9_encoder':time.process_time()-full_cpu_start,
             'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
             'original_labels_for_heldout_opened':False,'independent_semantic_review':False,
             'equal_total_compute':False,'production_authorized':False}
    sealed_create(out/'predictions.json',result)
    sealed_create(out/'physical.json',receipt)
    print(json.dumps({'cases':len(test),'head_updates':len(SEEDS)*STEPS,'original_features_reused':True,'prediction_sha256':receipt['prediction_sha256']}))


def score(root:Path,original_root:Path,out:Path):
    if not out.is_dir():raise ValueError('missing complete original V11 rank seal')
    plan,pr,receipt=(json.loads((out/name).read_bytes()) for name in ('plan.json','predictions.json','physical.json'))
    src=read_pinned(root,'source-only.json')
    original=read_pinned(root,'original-predictions.json')
    if (plan.get('schema')!=SCHEMA+'.precommit' or plan.get('v9_original_sha256')!=PINS
        or plan.get('heldout_labels_read') is not False
        or pr.get('schema')!=SCHEMA+'.sealed-predictions'
        or pr.get('plan_sha256')!=sha(stable_dump(plan))
        or pr.get('labels_read_before_seal') is not False
        or receipt.get('prediction_sha256')!=sha(stable_dump(pr))
        or receipt.get('original_labels_for_heldout_opened') is not False
        or receipt.get('production_authorized') is not False):
        raise ValueError('original V11 pre-seal/source/model evidence altered')
    qid_to_fam={q['id']:fam for fam in HELD for q in src['families'][fam]['questions']}
    if set(pr.get('predictions',{}))!=set(qid_to_fam):raise ValueError('incomplete original heldout census')
    arms={'bm25_full','dense_full'}|{f'seed{seed}/{mode}' for seed in SEEDS for mode in ('residual','safe_two')}
    for qid,row in pr['predictions'].items():
        if set(row)!=arms:raise ValueError('unexpected or missing V11 arm')
        valid={doc['id'] for doc in src['families'][qid_to_fam[qid]]['passages']}
        for arm,rank in row.items():
            if not isinstance(rank,list) or len(rank)!=TOP or len(set(rank))!=TOP or not set(rank)<=valid:
                raise ValueError('invalid delivered source identifier')
        baseline=row['bm25_full']
        for seed in SEEDS:
            if row[f'seed{seed}/safe_two'][:2]!=baseline[:2]:
                raise ValueError('the baseline two-source preservation contract changed')
        if row['bm25_full']!=original['rankings'][qid]['bm25_full']:
            raise ValueError('tampered original BM25 control')
    if file_sha(original_root/'locomo.json')!='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4':
        raise ValueError('changed original publisher source')
    held=weak_gold(json.loads((original_root/'locomo.json').read_bytes()),src)
    totals={};family_counts={};unknown={}
    for arm in sorted(arms):
        totals[arm]=0;family_counts[arm]={}
        for fam in HELD:
            items=[q['id'] for q in src['families'][fam]['questions']]
            hits=0;unknowns=0
            for qid in items:
                ref=held[qid]
                if ref is None:unknowns+=1;continue
                if set(pr['predictions'][qid][arm])&ref:hits+=1
            totals[arm]+=hits;family_counts[arm][fam]={'n':len(items),'hits':hits,'unknown':unknowns}
    if totals['bm25_full']!=372 or totals['dense_full']!=223:raise ValueError('baseline historical negative changed')
    data={'schema':SCHEMA+'.postseal-historical-weak-score','plan_sha256':pr['plan_sha256'],
          'prediction_sha256':sha(stable_dump(pr)),'physical_receipt_sha256':sha(stable_dump(receipt)),
          'heldout_questions':829,'independent_source_families':4,
          'per_arm_weak_hit3':totals,'family_counts':family_counts,
          'task_success_semantic_correctness':None,'future_calendar_windows':0,
          'full_lifecycle_cost_matched':False,
          'selection_winner_verified':False,'production_authorized':False}
    target=out/'score.json'
    with target.open('x') as f:
        f.write(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n')
        f.flush();os.fsync(f.fileno())
    print(json.dumps({'weak_hits':totals,'selection_winner_verified':False}))


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=('rank','score'))
    p.add_argument('--v9-root',type=Path,required=True)
    p.add_argument('--original-root',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.operation=='rank':rank(a.v9_root,a.output)
    elif a.original_root is None:raise ValueError('scoring requires original-only label owner')
    else:score(a.v9_root,a.original_root,a.output)

if __name__=='__main__':main()
