"""P8: finite TRAIN-only compute-portfolio policy, no task-label access at inference.

A *discrete, bounded NDU-inspired* risk-weighted dynamic program. No neural
FBSDE, financial arbitrage theorem, model training or production authority.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache

SCHEMA = 'hepta.ndu-merton.p8.conditional-computation.v1'
POLICIES = ('direct', 'fixed_plain', 'fixed_think', 'neutral', 'ndu_discrete', 'ordinary_same_profile')
CHECKS = ('stop', 'check_plain', 'check_think')
BUDGET = 4                   # incrementally paid checker calls per 16-case policy
TARIFF = Q(1, 4096)         # fixed utility per actual full input+output token (not money)
MIN_SUPPORT = 3              # per observable bucket/status pair


def feature(baseline: dict) -> str:
    """Legal label-blind state: only a strict terminal-class parse is observable."""
    p = baseline.get('predicted_class')
    if p is None:
        return 'invalid'
    if type(p) is not int or p not in (0, 1, 2, 3):
        raise ValueError('invalid raw prediction')
    return 'valid'


def train_profile(train_rows: list[dict], calls: list[dict]) -> dict:
    """Fit successes and costs from only 3 paid TRAIN actions for each source row.

    TRAIN outcomes are allowed, held publisher labels are not passed to this API.
    Naively multiplying response marginal probabilities is prohibited: this
    policy estimates *paired actual outcomes*, not independent model outputs.
    """
    if not train_rows or len(train_rows) != 32 or len(calls) != len(train_rows)*3:
        raise ValueError('exact 32 x 3 original TRAIN call census required')
    known = {r['task_id']: r for r in train_rows}
    if len(known) != len(train_rows) or any(set(r) != {'task_id','text','text_sha256','bucket','group','label'} for r in train_rows):
        raise ValueError('incomplete TRAIN source')
    records = {}
    for row in calls:
        if row.get('phase') != 'train' or row.get('policy') != 'train' or row.get('task_id') not in known or row.get('action') not in ('direct','check_plain','check_think'):
            raise ValueError('invalid TRAIN action or task')
        k = (row['task_id'], row['action'])
        if k in records:raise ValueError('duplicate TRAIN action')
        r = row['result']
        if type(r.get('input_tokens')) is not int or type(r.get('output_tokens')) is not int or r['input_tokens'] <= 0 or r['output_tokens'] <= 0:
            raise ValueError('invalid physical TRAIN meter')
        if r.get('predicted_class') is not None and (type(r['predicted_class']) is not int or r['predicted_class'] not in range(4)):
            raise ValueError('invalid original TRAIN prediction')
        records[k] = r
    if len(records) != len(calls):raise ValueError('extra/missing TRAIN action')
    accum: dict[tuple[str,str],list] = {}
    hist: dict[str,Counter] = {'short':Counter(), 'long':Counter()}
    for row in train_rows:
        tid, bucket, group, label = row['task_id'], row['bucket'], row['group'], row['label']
        if bucket not in hist or type(group) is not str or type(label) is not int or label not in range(4):
            raise ValueError('unsupported TRAIN feature/label')
        base = records[tid,'direct']
        f = feature(base)
        hist[bucket][f] += 1
        for a in CHECKS:
            record = base if a == 'stop' else records[tid,a]
            # Strict *full* check tokens; direct is already a sunk paid action
            cost = 0 if a == 'stop' else record['input_tokens']+record['output_tokens']
            success = int(record['predicted_class'] == label)
            accum.setdefault((bucket,f),[]).append((a,success,cost,group))
    profile = {'schema':SCHEMA+'.train-profile','census':len(train_rows),'entries':{},'features':{}}
    for bucket in ('short','long'):
        count=sum(hist[bucket].values())
        if count<12:raise ValueError('insufficient TRAIN per observable difficulty')
        profile['features'][bucket] = {f:str(Q(hist[bucket][f]+1,count+2)) for f in ('valid','invalid')}
    for (bucket,f),xs in sorted(accum.items()):
        n=hist[bucket][f]
        if n<MIN_SUPPORT:continue
        p={}
        for a in CHECKS:
            arr=[(s,c,g) for action,s,c,g in xs if action==a]
            if len(arr)!=n:raise ValueError('unpaired TRAIN action evidence')
            correct=sum(s for s,c,g in arr)
            groups={g for _,_,g in arr}
            if len(groups)<2:raise ValueError('TRAIN source-group support insufficient')
            group_min=min(Q(1+sum(s for s,c,g in arr if g==group),2+sum(g==group for s,c,g in arr)) for group in groups)
            p[a]={'mean':str(Q(correct+1,n+2)),
                  'worst_group':str(group_min),
                  'mean_full_tokens':str(Q(sum(c for _,c,_ in arr),n)),
                  'n':n}
        profile['entries'][f'{bucket}/{f}']=p
    return profile


def risk_alpha(policy: str, state: str, profile: dict, remaining: int) -> Q:
    if policy in ('neutral','direct','fixed_plain','fixed_think'):
        return Q(0)
    if policy not in ('ndu_discrete','ordinary_same_profile'):
        raise ValueError('unsupported policy')
    entry=profile['entries'].get(state)
    if entry is None:return Q(0)
    prior=Q(entry['stop']['mean'])
    return min(Q(1,2),Q(1,8)+(1-prior)/4+Q(BUDGET-remaining,32))


def reward(profile:dict,state:str,action:str,policy:str,remaining:int) -> Q:
    entry=profile['entries'].get(state)
    if not entry:
        return Q(0) if action=='stop' else Q(-100)
    row=entry[action]
    alpha=risk_alpha(policy,state,profile,remaining)
    return (1-alpha)*Q(row['mean'])+alpha*Q(row['worst_group'])-TARIFF*Q(row['mean_full_tokens'])


class Controller:
    """Exact finite dynamic program for the declared empirical surrogate.

    Future baseline validity is integrated from frozen TRAIN marginals, not
    from a held label, future model answer or unreached branch. The returned
    strategy is not a claim of general/global Merton optimality.
    """
    def __init__(self, profile:dict, buckets:tuple[str,...], name:str):
        if name not in POLICIES or len(buckets)!=16 or any(b not in ('short','long') for b in buckets):
            raise ValueError('invalid policy scope or future public slate')
        if profile.get('schema')!=SCHEMA+'.train-profile' or profile.get('census')!=32:
            raise ValueError('wrong TRAIN profile')
        self.profile, self.buckets, self.name=profile,buckets,name
        self.future=lru_cache(maxsize=512)(self._future)

    def _future(self,index:int,remaining:int) -> Q:
        if index == len(self.buckets):return Q(0)
        bucket=self.buckets[index]
        out=Q(0)
        for feat in ('valid','invalid'):
            probability=Q(self.profile['features'][bucket][feat])
            state=f'{bucket}/{feat}'
            available=('stop','check_plain','check_think') if remaining else ('stop',)
            out+=probability*max(
                reward(self.profile,state,a,self.name,remaining)+self.future(index+1,remaining-(a!='stop'))
                for a in available)
        return out

    def choose(self,index:int,remaining:int,bucket:str,base:dict) -> str:
        if type(index) is not int or type(remaining) is not int or not 0<=index<16 or not 0<=remaining<=BUDGET or self.buckets[index]!=bucket:
            raise ValueError('invalid online state')
        if self.name=='direct':return 'stop'
        if self.name in ('fixed_plain','fixed_think'):
            return ('check_plain' if self.name=='fixed_plain' else 'check_think') if index<4 and remaining else 'stop'
        state=f'{bucket}/{feature(base)}'
        entry=self.profile['entries'].get(state)
        if not entry:return 'stop'  # no unsupported extrapolation on sparse state
        actions=('stop','check_plain','check_think') if remaining else ('stop',)
        values=[(reward(self.profile,state,a,self.name,remaining)+self.future(index+1,remaining-(a!='stop')),a) for a in actions]
        return max(values,key=lambda p:(p[0], -actions.index(p[1])))[1]
