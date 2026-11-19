"""Separate-process replay: independent prefix-indexed FBSDE map and Newton spot checks.

Does not import the early-stop policy implementation. Compares root-value interval
claims against the same predeclared discrete controlled state law. All timings
are local measurements, not independently authenticated external telemetry.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
from time import process_time_ns

ROOT=Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT/'ndu-p5-coupled-study'))
from coupled_binary import Profile, solve
from independent_reference import direct_map, newton

SCHEMA='hepta.ndu.p5.costed-decision.v1'
CONFIG={'seed_a':14011,'seed_b':25817,'tasks_per_window':96,'max_calls':90,'fixed_depth':4}
FROZEN_SOURCE_SHA='e420444337d163508cd7ba8122894ffd334566b52d57073e67b94203e301eac2'


def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def sha(x):return hashlib.sha256(canonical(x)).hexdigest()
def sourcefile(path):return json.loads(Path(path).read_bytes())

def require(ok,why):
    if not ok:raise ValueError(why)


def makeprofile(case,o):
    p=Profile(steps=case['steps'],horizon=case['horizon'],a=o['a'],
             beta=case['beta'],lam=case['lam'],sigma=case['sigma'],x0=case['x0'])
    p.validate()
    return p


def replay(protocol, sealed):
    require(sha(protocol)==FROZEN_SOURCE_SHA and protocol['schema']==SCHEMA and protocol['kind']=='plan' and protocol['configuration']==CONFIG,
            'plan identity')
    require(protocol['authority']=='DENY_ALL' and protocol['synthetic_only'] is True and
            protocol['production_accepted'] is False,'plan cannot authorize')
    require(len(protocol['cases'])==192 and len({c['task_id'] for c in protocol['cases']})==192,
            'complete predeclared tasks')
    require(sealed['schema']==SCHEMA and sealed['kind']=='sealed_predictions' and
            sealed['source_sha256']==sha(protocol) and sealed['authority']=='DENY_ALL' and
            sealed['production_accepted'] is False and sealed['reference_oracle_read_before_seal'] is False,
            'sealed source identity or false oracle claim')
    require(len(sealed['entries'])==192,'incomplete sealed panel')
    rows=[];bycohort=defaultdict(list)
    for i,(c,row) in enumerate(zip(protocol['cases'],sealed['entries'])):
        require(row['task_id']==c['task_id'] and row['cohort']==c['cohort'],
                'source identity/order mismatch')
        opts=c['options']; actions=['abstain']+[o['action_id'] for o in opts]
        early=row['nominal_early'];control=row['controls']
        require(type(early['certified_nominal']) is bool and
                type(early['budget_exhausted']) is bool and
                early['certified_nominal'] != early['budget_exhausted'] and
                early['production_accepted'] is False and early['authority']=='DENY_ALL' and
                early['continuum_or_FP64_rigorous_certificate'] is False,
                'false numerical certification')
        require(set(control)=={'cheap_one_map','cheap_one_map_calls','fixed_depth',
                'fixed_depth_calls','cpu_ns'},'control inventory')
        require(control['cheap_one_map'] in actions and control['fixed_depth'] in actions and
                control['cheap_one_map_calls']==len(opts) and
                control['fixed_depth_calls']==len(opts)*CONFIG['fixed_depth'] and
                type(control['cpu_ns']) is int and control['cpu_ns']>0,
                'cheap control invalid')
        require(type(early['cpu_ns']) is int and early['cpu_ns']>0 and
                type(early['wall_ns']) is int and early['wall_ns']>0,
                'missing actually measured solver work')
        # Independently rerun cheap and fixed-depth algorithms under the SAME
        # frozen action set. Neither may invent a correct answer after seeing
        # externally recomputed full-reference decision values.
        one=[('abstain',0.0)];fixed=[('abstain',0.0)]
        for o in opts:
            p=makeprofile(c,o)
            y=[0.0]*(2**p.steps-1)
            for k in range(CONFIG['fixed_depth']):
                y=direct_map(p,y)
                if k==0:one.append((o['action_id'],y[0]-o['cost']))
            fixed.append((o['action_id'],y[0]-o['cost']))
        require(control['cheap_one_map']==max(one,key=lambda v:v[1])[0] and
                control['fixed_depth']==max(fixed,key=lambda v:v[1])[0],
                'cheap or fixed-depth baseline prediction was altered')
        entries=early['per_action']
        require(len(entries)==len(opts),'missing action bounds')
        calls=0
        for e,o in zip(entries,opts):
            p=makeprofile(c,o)
            require(e['action_id']==o['action_id'] and e['a']==o['a'] and e['cost']==o['cost'] and
                    len(e['y'])==2**p.steps-1 and all(math.isfinite(t) for t in e['y']),
                    'candidate changed or nonfinite')
            require(type(e['calls']) is int and e['calls']>=1,'fake work')
            calls+=e['calls']
            # Verify claimed work count by independently replaying every declared
            # Picard step from the frozen zero initialization, not just final y.
            independent_y=[0.0]*(2**p.steps-1)
            for _ in range(e['calls']-1):
                independent_y=direct_map(p,independent_y)
            require(max(abs(v-w) for v,w in zip(independent_y,e['y']))<=2e-11,
                    'unmatched physical operator-count claim')
            # Use independent prefix-indexed implementation, not the candidate's map.
            mapped=direct_map(p,e['y'])
            res=max(abs(v-w) for v,w in zip(e['y'],mapped))
            rad=res/(1-p.q)
            center=e['y'][0]-o['cost']
            require(abs(e['residual']-res)<5e-11 and abs(e['radius']-rad)<5e-11 and
                    abs(e['lower']-(center-rad))<5e-11 and
                    abs(e['upper']-(center+rad))<5e-11 and abs(e['contraction_q']-p.q)<1e-14,
                    'nominal backward interval is not justified by original dynamics')
        require(calls==early['work_calls'] and calls<=CONFIG['max_calls'],
                'uncounted early-stop operator calls')
        lb=[('abstain',0.)]+[(e['action_id'],e['lower']) for e in entries]
        ub=dict([('abstain',0.)]+[(e['action_id'],e['upper']) for e in entries])
        if early['certified_nominal']:
            action=early['choice'];require(action in actions,'illegal action')
            lower=dict(lb)[action]
            gap=lower-max(v for k,v in ub.items() if k!=action)
            require(gap>1e-12 and abs(gap-early['positive_gap_lower_bound'])<5e-11,
                    'unsupported global action separation')
        else:
            require(early['choice'] is None and early['positive_gap_lower_bound'] is None and
                    calls==CONFIG['max_calls'],'unreported budget exhaustion')
        # Full registered Picard solves are recomputed only after the prediction seal.
        vals={'abstain':0.};full_calls=0;full_cpu=0;check_newton=0
        for o in opts:
            p=makeprofile(c,o)
            solution=solve(p,tol=1e-10)
            require(solution['accepted_global_discrete'],'unsupported full reference')
            full_calls+=solution['calls'];full_cpu+=solution['cpu_ns']
            vals[o['action_id']]=solution['y'][0]-o['cost']
            if i%24==0:
                independently=newton(p,tol=1e-10)
                check_newton+=1
                require(abs(independently['y'][0]-solution['y'][0])<2e-9,
                        'Newton disagrees with original discrete global reference')
            e=next(t for t in entries if t['action_id']==o['action_id'])
            require(vals[o['action_id']]>=e['lower']-2e-9 and
                    vals[o['action_id']]<=e['upper']+2e-9,
                    'claimed root utility interval missed independent true solution')
        optimal=max(vals,key=vals.get);vmax=vals[optimal]
        require(opts[0]['a']==0.,'missing preregistered no-coupling control')
        uncoupled='abstain' if vals[opts[0]['action_id']]<=0.0 else opts[0]['action_id']
        # a=0 direct backward BSDE has no fixed-point feedback; one map is enough.
        direct_p=makeprofile(c,opts[0]);zero=[0.]*(2**direct_p.steps-1)
        direct_result=direct_map(direct_p,zero)[0]-opts[0]['cost']
        require(abs(direct_result-vals[opts[0]['action_id']])<2e-9,
                'cheap exact uncoupled Bellman/BSDE oracle mismatch')
        if early['certified_nominal']:
            require(early['choice']==optimal or abs(vals[early['choice']]-vmax)<2e-9,
                    'nominal certificate selected lower-utility action')
        results={'task_id':c['task_id'],'cohort':c['cohort'],
                 'optimum':optimal,'optimum_value':vmax,
                 'certified':early['certified_nominal'],'early_action':early['choice'],
                 'cheap_correct':control['cheap_one_map']==optimal,
                 'fixed_correct':control['fixed_depth']==optimal,
                 'cheap_exact_uncoupled_action':uncoupled,
                 'cheap_exact_uncoupled_regret':max(0,vmax-vals[uncoupled]),
                 'cheap_exact_uncoupled_correct':uncoupled==optimal,
                 'cheap_exact_uncoupled_operator_calls':1,
                 'cheap_regret':max(0,vmax-vals[control['cheap_one_map']]),
                 'fixed_regret':max(0,vmax-vals[control['fixed_depth']]),
                 'early_calls':calls,'full_calls':full_calls,
                 'cheap_calls':control['cheap_one_map_calls'],
                 'fixed_calls':control['fixed_depth_calls'],
                 'early_cpu_ns':early['cpu_ns'],'full_cpu_ns':full_cpu,
                 'newton_spot_checks':check_newton}
        rows.append(results);bycohort[c['cohort']].append(results)
    cohort_summary={}
    for name,v in sorted(bycohort.items()):
        require(len(v)==96,'missing independent task cohort')
        cohort_summary[name]={
            'count':len(v),'certified':sum(k['certified'] for k in v),
            'uncertified_abstentions':sum(not k['certified'] for k in v),
            'early_operator_calls':sum(k['early_calls'] for k in v),
            'full_picard_operator_calls':sum(k['full_calls'] for k in v),
            'one_map_operator_calls':sum(k['cheap_calls'] for k in v),
            'fixed_depth_operator_calls':sum(k['fixed_calls'] for k in v),
            'early_cpu_ns_self_reported':sum(k['early_cpu_ns'] for k in v),
            'full_cpu_ns_locally_measured':sum(k['full_cpu_ns'] for k in v),
            'cheap_exact_uncoupled_disagreements':sum(not k['cheap_exact_uncoupled_correct'] for k in v),
            'cheap_exact_uncoupled_operator_calls':sum(k['cheap_exact_uncoupled_operator_calls'] for k in v),
            'cheap_exact_uncoupled_total_regret':math.fsum(k['cheap_exact_uncoupled_regret'] for k in v),
            'one_map_disagreements':sum(not k['cheap_correct'] for k in v),
            'fixed_depth_disagreements':sum(not k['fixed_correct'] for k in v),
            'one_map_total_regret':math.fsum(k['cheap_regret'] for k in v),
            'fixed_depth_total_regret':math.fsum(k['fixed_regret'] for k in v),
            'independent_newton_action_spot_checks':sum(k['newton_spot_checks'] for k in v)}
    return {'schema':SCHEMA,'kind':'independent_score','source_sha256':sha(protocol),
            'sealed_prediction_sha256':sha(sealed),
            'summary':cohort_summary,'rows':rows,
            'full_discrete_model_known_in_task':True,
            'natural_world_reasoning_gain':False,
            'adaptive_policy_not_neurally_learned':True,
            'continuous_FBSDE_or_roundoff_rigorous':False,
            'physical_model_execution':False,'production_accepted':False,
            'authority':'DENY_ALL'}


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--source-sha256',required=True)
    p.add_argument('--sealed',required=True);p.add_argument('--sealed-sha256',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    for path,digest in ((a.source,a.source_sha256),(a.sealed,a.sealed_sha256)):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('source/seal file-byte mismatch')
    scored=replay(sourcefile(a.source),sourcefile(a.sealed))
    with Path(a.output).open('xb') as f:f.write(canonical(scored)+b'\n')
    print(json.dumps({'sha256':hashlib.sha256(Path(a.output).read_bytes()).hexdigest(),
                      'cohorts':scored['summary'],'production_accepted':False},sort_keys=True))

if __name__=='__main__':cli()
