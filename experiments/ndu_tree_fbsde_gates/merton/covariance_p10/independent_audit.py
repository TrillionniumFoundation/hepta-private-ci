"""P10 independent second-program original Qwen evidence + finite Merton audit.

Imports no P10 proposer, P5 worker or NDU solver. Reconstructs TRAIN-only
moments, all finite allocations, raw-call coverage and postseal publisher truth.
Not an independent signer, causal OPE evaluator or physically measured saving.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from fractions import Fraction as Q
from pathlib import Path

ORIGIN=39000773484
POSTURE='RESEARCH_ONLY_DENY_ALL'
SOURCE_SHA='ded66a28c186a8963c7781df3f091968758791e3'
POLICIES=('neutral','diagonal','covariance','ordinary_same_profile','direct')
RISK={'neutral':Q(0),'diagonal':Q(2),'covariance':Q(2),'ordinary_same_profile':Q(2),'direct':Q(2)}
ACTIONS=('direct','reason','verify')
N=16
TARIFF=Q(1,2048)
FIXED={
 'train-public.json':'580d078fc173fd9e3d7c35bca0a8eec874586f2a53b7a901838ff3362a92d3ab',
 'held-public.json':'9b6da146af00c54c607277cfccd452e9bc2e04a912638c1954f2f9452c6ddc55',
 'held-private-labels.json':'4e126e349252fe8bb04506006d32e2c89db8677058881ac4b718ca6863c02202',
 'completed-original.json':'666f95832f8338d8c44e012bdf85a0c08b811ad250df7bfa037e8ba0e0017c15',
 'frozen-plan.json':'0b7fd6635a802d643d48d8174301d8cbfe1ebbb83c588c7a37e4353dd9f88245',
 'original-starts-and-dones.jsonl':'5fde8256c696cab3b73e480279f7a6243ea1f3afb858ea4f22abfcbebbcf0862',
 'hepta-p5-sanitized-review.json':'45d5ac14634250763249e884adbb17762804d90dc444a153a746538ba5df6c26',
}


def _sha(raw):return hashlib.sha256(raw).hexdigest()


def _bytes(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def _digest(obj):return _sha(_bytes(obj))


def _decode(raw):
    def unique(pairs):
        doc={}
        for k,v in pairs:
            if k in doc:raise ValueError('duplicate raw JSON key')
            doc[k]=v
        return doc
    return json.loads(raw.decode(),object_pairs_hook=unique,
              parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite original JSON')))


def _source_path(root,name):
    sub='public' if name in ('train-public.json','held-public.json') else ('gold' if name=='held-private-labels.json'
        else 'review' if name=='hepta-p5-sanitized-review.json' else 'original')
    return root/sub/name


def load(root:Path,*,postseal:bool=False):
    docs={}
    for name,expected in FIXED.items():
        if name=='held-private-labels.json' and not postseal:continue
        file=_source_path(root,name)
        if not file.is_file() or file.is_symlink() or file.stat().st_size>3_000_000:
            raise ValueError('raw original missing or unsafe: '+name)
        blob=file.read_bytes()
        if _sha(blob)!=expected:raise ValueError('raw original digest changed: '+name)
        docs[name]=blob if name.endswith('.jsonl') else _decode(blob)
    return docs


def training_statistics(train,run):
    rows=train.get('rows',[])
    if len(rows)!=N or Counter(x.get('label') for x in rows)!={i:4 for i in range(4)}:
        raise ValueError('actual publisher balanced training census unavailable')
    labels={}
    for row in rows:
        if row['task_id'] in labels or _sha(row['text'].encode())!=row['text_sha256']:
            raise ValueError('actual training text or task identity invalid')
        labels[row['task_id']]=row['label']
    paid=run.get('original_train_trace')
    if not isinstance(paid,list) or len(paid)!=N*3:raise ValueError('missing physical training panel')
    paired=defaultdict(dict)
    for event in paid:
        tid,action=event.get('task_id'),event.get('action')
        if tid not in labels or action not in ACTIONS or action in paired[tid]:
            raise ValueError('missing or duplicated original TRAIN action')
        if event.get('source_kind')!='original_physical' or event.get('policy')!='train':
            raise ValueError('not an actual original model call')
        answer=event.get('predicted_class')
        if answer is not None and (type(answer) is not int or answer not in range(4)):
            raise ValueError('invalid task score source')
        i,o=event.get('input_tokens'),event.get('output_tokens')
        if type(i) is not int or type(o) is not int or i<1 or o<1 or i>1024 or o>256:
            raise ValueError('invalid token meter')
        paired[tid][action]=(int(answer==labels[tid]),i+o)
    if set(paired)!=set(labels) or any(set(row)!=set(ACTIONS) for row in paired.values()):
        raise ValueError('paired original panel incomplete')
    gains=[];chosen_ids=sorted(paired)
    for tid in chosen_ids:
        base=paired[tid]['direct']
        gains.append(tuple(Q(paired[tid][a][0]-base[0])
            -TARIFF*(paired[tid][a][1]-base[1]) for a in ('reason','verify')))
    mean=[sum((g[i] for g in gains),Q(0))/N for i in range(2)]
    second=[[sum((g[i]*g[j] for g in gains),Q(0))/N for j in range(2)]for i in range(2)]
    # Corrected unbiased sample covariance, not covariance rate or BSDE driver Sigma.
    matrix=[[Q(N,N-1)*(second[i][j]-mean[i]*mean[j]) for j in range(2)] for i in range(2)]
    determinant=matrix[0][0]*matrix[1][1]-matrix[0][1]*matrix[1][0]
    if determinant<0 or matrix[0][1]!=matrix[1][0]:raise ValueError('invalid empirical matrix')
    response=[Q(paired[tid]['direct'][0]) for tid in chosen_ids]
    base_mean=sum(response,Q(0))/N
    b=[sum(((y-base_mean)*(g[i]-mean[i]) for y,g in zip(response,gains)),Q(0))/(N-1)
        for i in range(2)]
    linear=None
    if determinant>0:
        a=(b[0]*matrix[1][1]-b[1]*matrix[1][0])/determinant
        c=(b[1]*matrix[0][0]-b[0]*matrix[0][1])/determinant
        if a*matrix[0][0]+c*matrix[1][0]!=b[0] or a*matrix[0][1]+c*matrix[1][1]!=b[1]:
            raise ValueError('nonzero empirical regression residual')
        linear=[str(a),str(c)]
    return {'ids':chosen_ids,'mu':mean,'cov':matrix,'det':determinant,'linear':linear,
            'train_payload':[
                {'id':tid,'label':labels[tid], 'bucket':next(x['bucket'] for x in rows if x['task_id']==tid),
                 'actions':{a:{'correct':paired[tid][a][0],'tokens':paired[tid][a][1],
                               'source_id':tid} for a in ACTIONS}}for tid in chosen_ids]}


def independent_optimal_counts(stats,profile):
    # Independent oracle: enumerate a Cartesian grid and skip invalid exposures.
    if profile not in POLICIES:raise ValueError('unknown profile')
    candidates=[]
    for nreason,nverify in itertools.product(range(N+1),repeat=2):
        if nreason+nverify>N or (profile=='direct' and (nreason or nverify)):continue
        w=(Q(nreason,N),Q(nverify,N))
        benefit=w[0]*stats['mu'][0]+w[1]*stats['mu'][1]
        if profile=='diagonal':
            risk=w[0]**2*stats['cov'][0][0]+w[1]**2*stats['cov'][1][1]
        else:
            risk=(w[0]**2*stats['cov'][0][0]+w[1]**2*stats['cov'][1][1]
                  +2*w[0]*w[1]*stats['cov'][0][1])
        score=benefit-RISK[profile]*risk/2
        candidates.append((score,-nreason-nverify,-nreason,nreason,nverify))
    best=max(candidates)
    return best[3],best[4],best[0]


def recheck_plan(plan:dict,train:dict,held:dict,run:dict)->dict:
    if type(plan)!=dict or plan.get('schema')!='hepta.ndu-merton.p10.paired-covariance-shadow.v1.frozen-plan' or plan.get('posture')!=POSTURE:
        raise ValueError('wrong P10 shadow result class')
    claim=plan.get('seal_sha256')
    if type(claim) is not str or _digest({k:v for k,v in plan.items() if k!='seal_sha256'})!=claim:
        raise ValueError('bad attempt seal')
    if plan.get('origin_run_id')!=ORIGIN or plan.get('source_sha')!=SOURCE_SHA or plan.get('held_labels_seen') is not False:
        raise ValueError('wrong origin/future-label authority')
    stats=training_statistics(train,run)
    if plan.get('train_input_digest')!=_digest(stats['train_payload']) or plan.get('held_public_digest')!=_digest(held):
        raise ValueError('original public/training lineage mismatch')
    if plan.get('train_size')!=N or plan.get('paired_actions')!=list(ACTIONS):
        raise ValueError('incomplete original paired-training census')
    if plan.get('gamma')!={name:str(gamma) for name,gamma in RISK.items()}:
        raise ValueError('risk parameter shifted after observation')
    if (plan.get('moment_mu')!=[str(x) for x in stats['mu']] or
          plan.get('moment_covariance')!=[[str(x) for x in row]for row in stats['cov']] or
          plan.get('covariance_determinant')!=str(stats['det']) or
          plan.get('empirical_ols_z_not_bsde')!=stats['linear']):
        raise ValueError('forged or mathematically inconsistent sample moment')
    cases=held.get('rows')
    if type(cases)!=list or len(cases)!=N or any(set(x)!={'task_id','group','bucket','text','text_sha256'} for x in cases):
        raise ValueError('leaked HELD labels in plan input')
    ordered=sorted(x['task_id'] for x in cases)
    if len(set(ordered))!=N or any(_sha(x['text'].encode())!=x['text_sha256'] for x in cases):
        raise ValueError('original held-public invalid')
    if set(plan.get('policies',{}))!=set(POLICIES):
        raise ValueError('missing/additional policy')
    for name in POLICIES:
        a,b,value=independent_optimal_counts(stats,name)
        actual=plan['policies'][name]
        schedule={tid:'reason' if i<a else 'verify' if i<a+b else 'direct'
                  for i,tid in enumerate(ordered)}
        if actual!={'reason_count':a,'verify_count':b,'shadow_value':str(value),'actions':schedule}:
            raise ValueError('P10 independent exact optimizer/selection disagreement: '+name)
    if plan['policies']['covariance']['actions']!=plan['policies']['ordinary_same_profile']['actions']:
        raise ValueError('identical NDU/ordinary objective must be identical')
    if plan.get('no_claims')!=['no_online_compute_saving','no_independent_future_sources',
                'no_NDU_algorithmic_lift_over_matched_profile','no_neural_FBSDE',
                'no_untested_counterfactual_scores']:
        raise ValueError('scientific claim boundary removed')
    return stats


def postseal(root:Path,plan:dict)->dict:
    # FIRST close an independent TRAIN-only proof and action schedule; ONLY THEN
    # open publisher gold and check physical support. Code must not self-sign.
    public=load(root,postseal=False)
    stats=recheck_plan(plan,public['train-public.json'],public['held-public.json'],public['completed-original.json'])
    original=load(root,postseal=True)
    gold=original['held-private-labels.json']
    if gold.get('schema')!='hepta.ndu-merton.p5.class-balanced-agnews-source.v1.held-private-labels' or len(gold.get('rows',[]))!=N:
        raise ValueError('unsupported independent original publisher gold')
    rows={x['task_id']:x for x in original['held-public.json']['rows']}
    truths={}
    for x in gold['rows']:
        tid=x.get('task_id')
        if tid not in rows or tid in truths or x.get('text_sha256')!=rows[tid]['text_sha256']:
            raise ValueError('publisher labels/source mismatch')
        truth=x.get('label')
        if type(truth)!=int or truth not in range(4):raise ValueError('publisher score outside registered classes')
        truths[tid]=truth
    if len(truths)!=N:raise ValueError('publisher gold incomplete')
    original_run=original['completed-original.json']
    if (original_run.get('total_generation_invocations')!=192 or
        len(original_run.get('actual_policy_trace',[]))!=112 or
        len(original_run.get('original_train_trace',[]))!=48 or
        len(original_run.get('paired_equalcap_trace',[]))!=32 or
        original['hepta-p5-sanitized-review.json'].get('original_total_execution_cpu_seconds') is None):
        raise ValueError('P5 original physical census incomplete')
    trace=defaultdict(list)
    for item in original_run['actual_policy_trace']:
        tid,action=item.get('task_id'),item.get('action')
        if tid not in truths or action not in ACTIONS or item.get('source_kind')!='original_physical':
            raise ValueError('untrusted original paid held output')
        pred=item.get('predicted_class')
        if pred is not None and (type(pred)!=int or pred not in range(4)):
            raise ValueError('malformed model class')
        i,o=item.get('input_tokens'),item.get('output_tokens')
        if type(i)!=int or type(o)!=int or i<1 or o<1:
            raise ValueError('invalid self-metered paid original task')
        trace[tid,action].append((pred,i+o))
    if len({x['task_id'] for x in original_run['actual_policy_trace']})!=N:
        raise ValueError('not all original held tasks physically attempted')
    results={}
    for name,p in plan['policies'].items():
        missing=[];observed=[]
        for tid,action in p['actions'].items():
            records=trace.get((tid,action),[])
            if not records:
                missing.append(tid)
                continue
            if len(set(records))>1:
                raise ValueError('same task+action paid original replicas disagree: '+tid)
            pred,tokens=records[0]
            observed.append((tid,int(pred==truths[tid]),tokens))
        available=len(missing)==0
        results[name]={'supported_tasks':len(observed),'unsupported_tasks':len(missing),
            'full_16_task_original_action_coverage':available,
            'total_correct_if_fully_supported':sum(x[1] for x in observed) if available else None,
            'observed_16_task_tokens_if_fully_supported':sum(x[2] for x in observed) if available else None,
            'unsupported_case_ids':missing,
            'no_actual_online_savings_claim':True}
    return {'schema':'hepta.ndu-merton.p10.independent-source-support-audit.v1',
            'status':'RESEARCH_ONLY_NO_PROSPECTIVE_NDU_OR_COST_LIFT',
            'origin_run_id':ORIGIN,'original_paid_model_calls':192,
            'original_execution_cpu_seconds_self_metered':original_run['execution_cpu_seconds'],
            'covariance_positive_definite_empirical_sample':stats['det']>0,
            'covariance_off_diagonal_nonzero':stats['cov'][0][1]!=0,
            'equal_objective_must_equal':results['covariance']==results['ordinary_same_profile'],
            'coverage':results,'p5_all_192_calls_already_paid':True,
            'no_new_model_forwards':True,'no_held_label_training':True,
            'no_independent_source_families':True,'independent_hardware_attestation':False,
            'no_NDU_superiority_or_FBSDE_wellposedness_claim':True,'authority':'DENY_ALL'}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--evidence',required=True,type=Path)
    ap.add_argument('--frozen',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args()
    plan=_decode(args.frozen.read_bytes())
    report=postseal(args.evidence,plan)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as out:
        out.write(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
