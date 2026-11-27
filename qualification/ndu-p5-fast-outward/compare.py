"""Read-only two-implementation comparison on a *previously sealed* P5 tree study.

This measures and challenges outward enclosures for the SAME fixed mathematical
law. No model training, effect, source authentication, or P5 acceptance authority.
A successful result is evidence of source-bound discrete action enclosure only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from time import process_time_ns

ROOT=Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT/'ndu-p5-roundoff'))
sys.path.append(str(ROOT/'ndu-p5-decision-cert'))
sys.path.append(str(ROOT/'ndu-p5-coupled-study'))
from rigorous_tree import action_bounds, resolve, SCALE
from independent_reference import direct_map
from fast_tanh import fast_action_bounds, REDUCTIONS, TERMS
from study import verify_plan, hexdigest

SCHEMA='hepta.p5.fixed-profile-fast-outward.v1'
SOURCE_SHA='e420444337d163508cd7ba8122894ffd334566b52d57073e67b94203e301eac2'
ORIGINAL_PLAN_FILE_SHA='92c568e9694c259b64ac1f8bb1f6db9d9214dd14ca13c81ff7d1f75bbea7a607'

class ReplayError(ValueError):pass

def require(value,reason):
    if not value:raise ReplayError(reason)

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=True).encode()
def bytes_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def parse(path):
    def reject(x):raise ReplayError('non-finite JSON value: '+x)
    return json.loads(Path(path).read_text(encoding='utf-8'),parse_constant=reject)

def percentile_ms(values,p):
    require(len(values)>=100 and all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in values),'missing 100 valid latency observations')
    order=sorted(values)
    return order[max(0,math.ceil(p*len(order))-1)]

class Profile:
    def __init__(self,row,opt):
        self.steps=row['steps'];self.horizon=row['horizon'];self.a=opt['a']
        self.beta=row['beta'];self.lam=row['lam'];self.sigma=row['sigma'];self.x0=row['x0']
    @property
    def h(self):return self.horizon/self.steps


def verify_inputs(plan,sealed,prior):
    try:verify_plan(plan)
    except (ValueError,KeyError,TypeError) as exc:raise ReplayError('plan not original fixed source') from exc
    require(hexdigest(plan)==SOURCE_SHA,'changed preregistered source')
    require(type(sealed) is dict and sealed.get('kind')=='sealed_predictions' and sealed.get('schema')==plan['schema'] and
            sealed.get('source_sha256')==SOURCE_SHA and sealed.get('authority')=='DENY_ALL' and
            sealed.get('production_accepted') is False and sealed.get('reference_oracle_read_before_seal') is False and
            sealed.get('natural_reasoning_gain_claimed') is False,'invalid or privileged prediction seal')
    require(type(prior) is dict and prior.get('kind')=='independent_score' and prior.get('schema')==plan['schema'] and
            prior.get('source_sha256')==SOURCE_SHA and prior.get('sealed_prediction_sha256')==hexdigest(sealed) and
            prior.get('production_accepted') is False and prior.get('authority')=='DENY_ALL' and
            prior.get('continuous_FBSDE_or_roundoff_rigorous') is False,'invalid historical independent score')
    require(type(sealed.get('entries')) is list and len(sealed['entries'])==192 and
            type(prior.get('rows')) is list and len(prior['rows'])==192,'unqualified inventory')
    require(len({r['task_id'] for r in sealed['entries']})==192 and
            len({r['task_id'] for r in prior['rows']})==192,'duplicate task')
    return {r['task_id']:r for r in prior['rows']}


def compare(plan,sealed,prior,*,replay_work=True):
    truth=verify_inputs(plan,sealed,prior)
    elapsed={'new_ns':0,'old_ns':0,'work_replay_ns':0}
    cases=plan['cases'];observed=sealed['entries']
    groups=Counter();warnings=[];tasks=[];old_gaps=[];new_gaps=[]
    new_certified=0;old_certified=0;replay_map_calls=0
    for i,(row,record) in enumerate(zip(cases,observed)):
        require(type(row) is dict and type(record) is dict and
                record.get('task_id')==row.get('task_id') and record.get('cohort')==row.get('cohort'),
                'row order/identity drift')
        require(row['task_id'] in truth and truth[row['task_id']]['cohort']==row['cohort'],'prior score missing')
        groups[row['cohort']]+=1
        opts=row.get('options');n=record.get('nominal_early')
        require(type(opts) is list and len(opts)==3 and type(n) is dict and n.get('production_accepted') is False and
                n.get('authority')=='DENY_ALL' and n.get('continuum_or_FP64_rigorous_certificate') is False,
                'unsafe policy or options')
        require(type(n.get('per_action')) is list and len(n['per_action'])==3,'action count')
        require([o.get('action_id') for o in opts]==['control_0','control_1','control_2'],'action registration')
        new=[];old=[];total_calls=0;lap=[0,0]
        for option,obs in zip(opts,n['per_action']):
            require(type(obs) is dict and option['action_id']==obs.get('action_id') and
                    obs.get('a')==option.get('a') and obs.get('cost')==option.get('cost'),'action drift')
            count=obs.get('calls'); y=obs.get('y')
            require(type(count) is int and 1<=count<=90 and type(y) is list and
                    len(y)==(1<<row['steps'])-1 and all(type(v) in (float,int) and math.isfinite(v) for v in y),
                    'unbounded state or false work')
            total_calls+=count
            if replay_work:
                t=process_time_ns()
                try:
                    pp=Profile(row,option)
                    state=[0.0]*len(y)
                    for _ in range(count-1):state=direct_map(pp,state)
                except Exception as exc:raise ReplayError('independent work replay failed') from exc
                replay_map_calls+=count-1
                require(max(abs(v-w) for v,w in zip(state,y))<=2e-11,'reported work not replayable')
                elapsed['work_replay_ns']+=process_time_ns()-t
            # Counterbalance order by task+action, avoiding first-run systematic bias.
            implementations=('old','new') if (i+total_calls)%2==0 else ('new','old')
            values={}
            for name in implementations:
                t=process_time_ns()
                try: cert=(action_bounds if name=='old' else fast_action_bounds)(row,option,y)
                except Exception as exc:raise ReplayError(name+' interval calculation rejected source') from exc
                delta=process_time_ns()-t
                elapsed[name+'_ns']+=delta;lap[0 if name=='old' else 1]+=delta
                values[name]=cert
            a=values['old'];b=values['new']
            require(a['lower_ticks']<=b['upper_ticks'] and b['lower_ticks']<=a['upper_ticks'],
                    'independent nonlinear interval disagreement')
            require(a['q_exact_numerator']*b['q_exact_denominator']==b['q_exact_numerator']*a['q_exact_denominator'],
                    'changed contraction domain')
            new.append(b);old.append(a)
        require(total_calls==n.get('work_calls') and total_calls<=90,'reported work count forged')
        expected=truth[row['task_id']]
        require(expected['early_calls']==total_calls and expected['early_action']==n.get('choice') and
                expected['certified']==n.get('certified_nominal'),'prior score changed')
        w_old,g_old=resolve(old);w_new,g_new=resolve(new)
        if w_old is not None:old_certified+=1;old_gaps.append(g_old/SCALE)
        if w_new is not None:new_certified+=1;new_gaps.append(g_new/SCALE)
        require(w_old==w_new==expected['optimum']==n.get('choice'), 'new interval not preserving independent optimum')
        if w_new is None:warnings.append(row['task_id'])
        tasks.append(dict(task_id=row['task_id'],cohort=row['cohort'],winner=w_new,
                          old_gap=g_old/SCALE,new_gap=g_new/SCALE,
                          old_interval_cpu_ns=lap[0],new_interval_cpu_ns=lap[1],
                          original_map_calls=total_calls,
                          old_root_bounds=[(v['lower_ticks'],v['upper_ticks']) for v in old],
                          new_root_bounds=[(v['lower_ticks'],v['upper_ticks']) for v in new]))
    require(groups=={'cohort_a':96,'cohort_b':96},'changed source cohorts')
    sum_original_calls=sum(x['early_calls'] for x in prior['rows'])
    require(sum_original_calls==sum(t['original_map_calls'] for t in tasks),'lost budget receipts')
    full_cpu=sum(x['full_cpu_ns'] for x in prior['rows'])
    return dict(schema=SCHEMA,authority='DENY_ALL',production_accepted=False,
                source_sha256=SOURCE_SHA,sealed_prediction_digest=hexdigest(sealed),
                independent_prior_digest=hexdigest(prior),task_count=len(tasks),
                old_certified=old_certified,new_certified=new_certified,
                mismatch_ids=warnings,
                original_nominal_map_calls=sum_original_calls,
                work_replay_map_calls=replay_map_calls,
                counted_work_replay_cpu_ms=elapsed['work_replay_ns']/1e6,
                old_interval_cpu_ms=elapsed['old_ns']/1e6,
                new_interval_cpu_ms=elapsed['new_ns']/1e6,
                new_interval_p95_task_ms=percentile_ms([x['new_interval_cpu_ns']/1e6 for x in tasks],.95),
                old_interval_p95_task_ms=percentile_ms([x['old_interval_cpu_ns']/1e6 for x in tasks],.95),
                old_minimum_positive_gap=min(old_gaps),new_minimum_positive_gap=min(new_gaps),
                old_mathematical_method='outward 96-term positive Taylor exp(2*x)',
                new_mathematical_method=f'outward exp(2*x/64) {TERMS}-term Taylor remainder + {REDUCTIONS} interval squares',
                historical_full_picard_cpu_ms=full_cpu/1e6,
                historical_full_picard_cpu_source='prior source, not same-process benchmark',
                interval_timing_scope='interval-only CPU measured in one counterbalanced process; work replay separate',
                cost_adjusted_online_gain_established=False,
                continuous_time_fbsde_certified=False,model_execution_verified=False,
                external_outcome_verified=False,exact_binary64_coefficients_only=True,
                independent_transcendental_method_compared=True,
                independent_nontranscendental_interval_library=False,
                formal_implementation_proof=False,
                rows=tasks)


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','sealed','prior','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args()
    for item in ('plan','sealed','prior'):
        require(Path(getattr(a,item)).is_file(),'missing input '+item)
    require(bytes_sha(a.plan)==ORIGINAL_PLAN_FILE_SHA,'source plan byte hash changed')
    report=compare(parse(a.plan),parse(a.sealed),parse(a.prior))
    with Path(a.output).open('xb') as f:f.write(canonical(report)+b'\n')
    print(json.dumps({k:report[k] for k in ('task_count','old_certified','new_certified','old_interval_cpu_ms','new_interval_cpu_ms','cost_adjusted_online_gain_established','authority')},sort_keys=True))

if __name__=='__main__':cli()
