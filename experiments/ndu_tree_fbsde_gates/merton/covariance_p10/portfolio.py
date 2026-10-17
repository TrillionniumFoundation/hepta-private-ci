"""P10 exact finite covariance-aware cognitive-portfolio research candidate.

A *descriptive* finite paired-TRAIN empirical mean/covariance surrogate, not a
neural FBSDE, a Merton theorem, a physically executable token quota, or a
certified causal/production optimizer.  No held labels enter policy selection.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from fractions import Fraction as F
from pathlib import Path

SCHEMA = 'hepta.ndu-merton.p10.paired-covariance-shadow.v1'
POSTURE = 'RESEARCH_ONLY_DENY_ALL'
ACTIONS = ('direct','reason','verify')
ALTS = ('reason','verify')
N = 16
TARIFF = F(1,2048)
GAMMAS = {'neutral': F(0), 'diagonal': F(2), 'covariance': F(2),
          'ordinary_same_profile': F(2), 'direct': F(2)}
PINNED = {
    'train-public.json':'580d078fc173fd9e3d7c35bca0a8eec874586f2a53b7a901838ff3362a92d3ab',
    'held-public.json':'9b6da146af00c54c607277cfccd452e9bc2e04a912638c1954f2f9452c6ddc55',
    'held-private-labels.json':'4e126e349252fe8bb04506006d32e2c89db8677058881ac4b718ca6863c02202',
    'completed-original.json':'666f95832f8338d8c44e012bdf85a0c08b811ad250df7bfa037e8ba0e0017c15',
    'frozen-plan.json':'0b7fd6635a802d643d48d8174301d8cbfe1ebbb83c588c7a37e4353dd9f88245',
    'original-starts-and-dones.jsonl':'5fde8256c696cab3b73e480279f7a6243ea1f3afb858ea4f22abfcbebbcf0862',
    'hepta-p5-sanitized-review.json':'45d5ac14634250763249e884adbb17762804d90dc444a153a746538ba5df6c26',
}


def canonical(x:object)->bytes:
    return json.dumps(x,sort_keys=True,separators=(',', ':'),ensure_ascii=True,
                      allow_nan=False).encode('utf-8')


def sha(raw:bytes)->str:
    return hashlib.sha256(raw).hexdigest()


def digest(x:object)->str:
    return sha(canonical(x))


def fraction(x:F)->str:
    return str(x)


def reject_dupes(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('duplicate JSON key')
        result[k]=v
    return result


def parse(raw:bytes):
    return json.loads(raw.decode('utf-8'),object_pairs_hook=reject_dupes,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def evidence_paths(root:Path)->dict[str,Path]:
    return {
        'train-public.json':root/'public'/'train-public.json',
        'held-public.json':root/'public'/'held-public.json',
        'held-private-labels.json':root/'gold'/'held-private-labels.json',
        'completed-original.json':root/'original'/'completed-original.json',
        'frozen-plan.json':root/'original'/'frozen-plan.json',
        'original-starts-and-dones.jsonl':root/'original'/'original-starts-and-dones.jsonl',
        'hepta-p5-sanitized-review.json':root/'review'/'hepta-p5-sanitized-review.json',
    }


def verified_read(root:Path,*,include_gold:bool=False)->dict:
    """Exactly pinned original P5 source; reuses no unstated replacement rows.

    Independent P7 raw/journal audit remains a mandatory separate CI step.
    """
    result={}
    for name,path in evidence_paths(root).items():
        if name=='held-private-labels.json' and not include_gold:continue
        if not path.is_file() or path.is_symlink() or path.stat().st_size>3_000_000:
            raise ValueError('missing, symlinked or oversized original evidence: '+name)
        raw=path.read_bytes()
        if sha(raw)!=PINNED[name]:raise ValueError('pinned original evidence changed: '+name)
        result[name]=parse(raw) if not name.endswith('.jsonl') else raw
    return result


def strict_int(x,lo,hi):
    if type(x) is not int or not lo<=x<=hi:raise ValueError('invalid integer evidence')
    return x


def original_train_pairs(train:dict,completed:dict)->list[dict]:
    if train.get('schema')!='hepta.ndu-merton.p5.class-balanced-agnews-source.v1.train':
        raise ValueError('unexpected exact source family')
    rows=train.get('rows')
    if type(rows) is not list or len(rows)!=N:raise ValueError('16 actual TRAIN source rows required')
    known={}
    for row in rows:
        if type(row)!=dict or set(row)!= {'task_id','text','text_sha256','bucket','group','label'}:
            raise ValueError('invalid original train row')
        key=row['task_id'];strict_int(row['label'],0,3)
        if key in known or type(key) is not str:raise ValueError('duplicate TRAIN task')
        if sha(row['text'].encode())!=row['text_sha256']:
            raise ValueError('altered publisher text')
        known[key]=row
    if {k:sum(x['label']==k for x in rows) for k in range(4)}!={k:4 for k in range(4)}:
        raise ValueError('original publisher label balance unsupported')
    trace=completed.get('original_train_trace')
    if type(trace)!=list or len(trace)!=N*len(ACTIONS):raise ValueError('incomplete original paid TRAIN')
    paired={k:{} for k in known}
    for item in trace:
        if type(item)!=dict or item.get('policy')!='train' or item.get('source_kind')!='original_physical':
            raise ValueError('not original paid Qwen TRAIN')
        name,act=item.get('task_id'),item.get('action')
        if name not in paired or act not in ACTIONS or act in paired[name]:
            raise ValueError('invalid paired original action coverage')
        pred=item.get('predicted_class')
        if pred is not None:strict_int(pred,0,3)
        tokens=(strict_int(item.get('input_tokens'),1,1024)
                +strict_int(item.get('output_tokens'),1,256))
        if item.get('thinking_mode')!=(act=='reason'):
            raise ValueError('thinking mode drift')
        paired[name][act]={'correct':int(pred==known[name]['label']),
                           'tokens':tokens,'source_id':name}
    if any(set(v)!=set(ACTIONS) for v in paired.values()):
        raise ValueError('missing paired original action')
    return [{'id':name,'label':known[name]['label'],'bucket':known[name]['bucket'],
             'actions':paired[name]} for name in sorted(paired)]


def moments(pairs:list[dict])->dict:
    """Two-dimensional *unconditional sample* excess utility covariance.

    U_alt - U_direct = observed paired task correctness increment minus
    original full model token cost difference / 2048.  A full paid slate is a
    prerequisite; these are not independently randomized/source-family samples.
    """
    if type(pairs)!=list or len(pairs)!=N:
        raise ValueError('16 paired real or independently constructed TRAIN rows required')
    gains=[]
    ids=set()
    for case in pairs:
        if set(case)!={'id','label','bucket','actions'} or case['id'] in ids:
            raise ValueError('duplicate or malformed paired case')
        ids.add(case['id'])
        if set(case['actions'])!=set(ACTIONS):raise ValueError('unpaired comparison')
        base=case['actions']['direct']
        current=[]
        for act in ALTS:
            alternative=case['actions'][act]
            for row in (base,alternative):
                strict_int(row['correct'],0,1)
                strict_int(row['tokens'],1,2000)
            current.append(F(alternative['correct']-base['correct'])
                -TARIFF*(alternative['tokens']-base['tokens']))
        gains.append(tuple(current))
    mu=tuple(sum((a[i] for a in gains),F(0))/N for i in range(2))
    cov=tuple(tuple(sum(((a[i]-mu[i])*(a[j]-mu[j]) for a in gains),F(0))/(N-1)
                     for j in range(2)) for i in range(2))
    determinant=cov[0][0]*cov[1][1]-cov[0][1]*cov[1][0]
    if any(cov[i][i]<0 for i in range(2)) or determinant<0:
        raise ValueError('invalid sample covariance')
    return {'n':N,'mu':mu,'cov':cov,'det':determinant,
            'paired_gain_vectors':tuple(gains)}


def conditional_regression_sample(pairs:list[dict],stat:dict)->tuple[F,F]|None:
    """Unconditional empirical OLS identity Z Sigma=B, NOT a BSDE Z estimate.

    The response is observed original direct correctness. A singular sample
    covariance is unavailable; no fake pseudoinverse/floored eigenvalue.
    """
    c=stat['cov'];d=stat['det']
    if d<=0:return None
    mean_y=sum((F(x['actions']['direct']['correct']) for x in pairs),F(0))/N
    b=tuple(sum(((F(x['actions']['direct']['correct'])-mean_y)
           *(g[i]-stat['mu'][i]) for x,g in zip(pairs,stat['paired_gain_vectors'])),F(0))/(N-1)
           for i in (0,1))
    z0=(b[0]*c[1][1]-b[1]*c[1][0])/d
    z1=(b[1]*c[0][0]-b[0]*c[0][1])/d
    if z0*c[0][0]+z1*c[1][0]!=b[0] or z0*c[0][1]+z1*c[1][1]!=b[1]:
        raise ValueError('empirical covariance regression residual')
    return z0,z1


def objective(a:int,b:int,stat:dict,profile:str)->F:
    strict_int(a,0,N);strict_int(b,0,N)
    if a+b>N:raise ValueError('portfolio overweight')
    if profile not in GAMMAS:raise ValueError('unknown registered risk profile')
    if profile=='direct' and (a or b):raise ValueError('invalid no-change exposure')
    w=(F(a,N),F(b,N))
    covariance=stat['cov']
    risk=sum((w[i]*w[j]*covariance[i][j]
              for i in range(2) for j in range(2)
              if profile!='diagonal' or i==j),F(0))
    gain=sum((w[i]*stat['mu'][i] for i in range(2)),F(0))
    return gain-F(GAMMAS[profile],2)*risk


def choose(stat:dict,profile:str)->tuple[int,int,F]:
    if profile=='direct':return 0,0,F(0)
    best=(0,0,objective(0,0,stat,profile))
    for a in range(N+1):
        for b in range(N+1-a):
            val=objective(a,b,stat,profile)
            # When indifferent choose fewer changed queries and prefer verify.
            if (val,-a-b,-a)>(best[2],-best[0]-best[1],-best[0]):
                best=(a,b,val)
    return best


def frozen_plan(pairs:list[dict],held_public:dict)->dict:
    rows=held_public.get('rows')
    if (held_public.get('schema')!='hepta.ndu-merton.p5.class-balanced-agnews-source.v1.held-public'
          or type(rows)!=list or len(rows)!=N):
        raise ValueError('original held label-blind source required')
    public=[];ids=set()
    for row in rows:
        if type(row)!=dict or set(row)!={'task_id','group','bucket','text','text_sha256'}:
            raise ValueError('held labels or unexpected fields presented to planner')
        if row['task_id'] in ids or type(row['task_id'])!=str:
            raise ValueError('repeated held public task')
        ids.add(row['task_id'])
        if sha(row['text'].encode())!=row['text_sha256']:
            raise ValueError('corrupted held public text')
        public.append(row['task_id'])
    public.sort()
    stats=moments(pairs)
    policies={}
    for arm in GAMMAS:
        n_reason,n_verify,value=choose(stats,arm)
        decisions={tid:('reason' if i<n_reason else 'verify'
                           if i<n_reason+n_verify else 'direct')
                   for i,tid in enumerate(public)}
        policies[arm]={'reason_count':n_reason,'verify_count':n_verify,
                       'shadow_value':str(value),'actions':decisions}
    if policies['covariance']['actions']!=policies['ordinary_same_profile']['actions']:
        raise ValueError('matched-objective ordinary optimizer parity failed')
    reg=conditional_regression_sample(pairs,stats)
    payload={'schema':SCHEMA+'.frozen-plan','posture':POSTURE,
             'origin_run_id':39000773484,'source_sha':
                'ded66a28c186a8963c7781df3f091968758791e3',
             'train_input_digest':digest(pairs),'held_public_digest':digest(held_public),
             'train_size':N,'paired_actions':list(ACTIONS),'gamma':{k:str(v) for k,v in GAMMAS.items()},
             'moment_mu':[str(x) for x in stats['mu']],
             'moment_covariance':[[str(x) for x in row] for row in stats['cov']],
             'covariance_determinant':str(stats['det']),
             'empirical_ols_z_not_bsde': None if reg is None else [str(x) for x in reg],
             'policies':policies,'held_labels_seen':False,
             'no_claims':['no_online_compute_saving','no_independent_future_sources',
                'no_NDU_algorithmic_lift_over_matched_profile','no_neural_FBSDE',
                'no_untested_counterfactual_scores']}
    payload['seal_sha256']=digest(payload)
    return payload


def no_overwrite(path:Path,payload:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as file:
        file.write(json.dumps(payload,sort_keys=True,indent=2,ensure_ascii=True)+'\n')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    evidence=verified_read(args.evidence,include_gold=False)
    pairs=original_train_pairs(evidence['train-public.json'],evidence['completed-original.json'])
    plan=frozen_plan(pairs,evidence['held-public.json'])
    no_overwrite(args.output,plan)
    print(json.dumps({'posture':POSTURE,'origin_run_id':plan['origin_run_id'],
       'train_pairs':N,'moment_mu':plan['moment_mu'],
       'moment_covariance':plan['moment_covariance'],
       'plan_seal':plan['seal_sha256'],'held_labels_seen':False},sort_keys=True))

if __name__=='__main__':main()
