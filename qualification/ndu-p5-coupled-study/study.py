"""Preregister, execute, independently replay the same discrete coupled FBSDE law.

Research-only. These are mathematical reference/speed observations, not
continuous-time FBSDE qualification, language reasoning or system authorization.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from coupled_binary import Profile, Unsupported, defects, direct_uncontrolled, mapping, solve
from independent_reference import direct_map, newton

SCHEMA='hepta.ndu.p5.discrete-coupled-study.v1'
PRESET={'a':(0.,.25,.6,.85,1.1),'steps':(3,4,5,6),'x0':(-.6,0.,.7)}
SCRIPTS=('coupled_binary.py','independent_reference.py','study.py')


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=True).encode()


def h(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def code_sha():
    here=Path(__file__).resolve().parent
    return {s:hashlib.sha256((here/s).read_bytes()).hexdigest() for s in SCRIPTS}


def profiles():
    return [asdict(Profile(steps=k,a=a,x0=x)) for a in PRESET['a']
            for k in PRESET['steps'] for x in PRESET['x0']]


def prepare():
    return {'schema':SCHEMA,'kind':'protocol','source_sha256':code_sha(),
            'comparison':'picard vs dense independent Newton vs cheaper uncoupled direct BSDE',
            'loss':'original whole-tree FBSDE fixed-point residual, sigma cross moments and Z driver',
            'fixed_operating_law':'symmetric bounded independent binary increments; exact enumeration',
            'same_random_law':True,'seed':None,'profiles':profiles(),
            'no_prehorizon_future_labels':True,'pretrained_model_execution':False,
            'continuous_time_error_certified':False,'authority':'DENY_ALL',
            'production_accepted':False}


def require(b,msg):
    if not b: raise ValueError(msg)


def verify_plan(plan):
    require(type(plan) is dict and plan==prepare(), 'plan/source changed after freezing')
    require(len(plan['profiles'])==60 and len({h(p) for p in plan['profiles']})==60, 'profile inventory')


def execute(plan):
    verify_plan(plan)
    rows=[]
    for profile in plan['profiles']:
        p=Profile(**profile)
        if p.q>=.95:
            try: solve(p)
            except Unsupported as exc:
                rows.append({'profile_sha256':h(profile),'status':'unsupported',
                             'reason':str(exc),'picard':None,'newton':None,
                             'direct':None,'wrong_reset':None})
                continue
            raise AssertionError('inadmissible global profile was solved')
        candidate=solve(p)
        ref=newton(p) if p.steps<=5 else None
        direct=direct_uncontrolled(p) if p.a==0 else None
        wrong=solve(p,reset_depth=max(1,p.steps//2))
        require(candidate['accepted_global_discrete'], 'accepted candidate lacks full residual')
        require(not wrong['accepted_global_discrete'], 'wrong continuation returned as global')
        rows.append({'profile_sha256':h(profile),'status':'completed',
                     'reason':None,'picard':candidate,'newton':ref,
                     'direct':direct,'wrong_reset':wrong})
    return {'schema':SCHEMA,'kind':'sealed_computations','protocol_sha256':h(plan),
            'code_sha256':code_sha(),'complete_predeclared_attempts':len(rows),
            'rows':rows,'pretrained_model_execution':False,
            'observed_CPU_means_model_free':True,'production_accepted':False,
            'authority':'DENY_ALL'}


def validate_measurement(row):
    for v in (row['picard'],row['newton'],row['direct'],row['wrong_reset']):
        if v is None: continue
        require(type(v.get('cpu_ns')) is int and v['cpu_ns']>0 and
                type(v.get('wall_ns')) is int and v['wall_ns']>0,
                'missing actual CPU or wall measurement')


def match_float(a,b,tol=2e-8):
    require(type(a) in (float,int) and type(b) in (float,int) and
            math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tol, 'numeric replay mismatch')


def audit(plan,measure):
    verify_plan(plan)
    require(type(measure) is dict and set(measure)=={
        'schema','kind','protocol_sha256','code_sha256','complete_predeclared_attempts',
        'rows','pretrained_model_execution','observed_CPU_means_model_free','production_accepted','authority'}, 'unexpected result schema')
    require(measure['schema']==SCHEMA and measure['kind']=='sealed_computations'
            and measure['protocol_sha256']==h(plan) and measure['code_sha256']==code_sha()
            and measure['complete_predeclared_attempts']==60
            and measure['pretrained_model_execution'] is False
            and measure['production_accepted'] is False and measure['authority']=='DENY_ALL'
            and measure['observed_CPU_means_model_free'] is True,
            'unbound or overclaimed result')
    rows=measure['rows']
    require(type(rows) is list and len(rows)==60, 'failed attempts removed')
    counts=Counter()
    picard_calls=0; matched_picard_calls=0; newton_calls=0; direct_calls=0
    deltas=[]; jumps=[]; max_z=0.; max_b=0.
    for p_raw,row in zip(plan['profiles'],rows):
        require(type(row) is dict and set(row)=={
            'profile_sha256','status','reason','picard','newton','direct','wrong_reset'}
            and row['profile_sha256']==h(p_raw), 'profile slot moved')
        p=Profile(**p_raw)
        if p.q>=.95:
            require(row['status']=='unsupported' and row['reason']==
                    'global discrete contraction margin not supported'
                    and all(row[k] is None for k in ('picard','newton','direct','wrong_reset')),
                    'failed regularity admission disguised as successful')
            counts['unsupported']+=1
            continue
        require(row['status']=='completed' and row['reason'] is None, 'unreported attempt failure')
        validate_measurement(row)
        got=row['picard'];wrong=row['wrong_reset']
        require(got['reset_control'] is False and got['accepted_global_discrete'] is True
                and got['production_accepted'] is False and got['authority']=='DENY_ALL',
                'false global solution or authority')
        require(wrong['reset_control'] is True and wrong['accepted_global_discrete'] is False,
                'wrong terminal reset promoted')
        require(got['profile']==p_raw and wrong['profile']==p_raw, 'profile drift')
        # Operator counts are deterministic under this frozen solver; numerical
        # recomputation is a stronger guard than trusting a self-reported count.
        replay=solve(p)
        require(got['calls']==replay['calls'] and
                max(abs(v-w) for v,w in zip(got['y'],replay['y']))<=1e-10,
                'deterministic Picard work/output differs from saved receipt')
        wrong_reference=solve(p,reset_depth=max(1,p.steps//2))
        require(wrong['calls']==wrong_reference['calls'] and
                max(abs(v-w) for v,w in zip(wrong['y'],wrong_reference['y']))<=1e-10,
                'wrong-reset negative control changed')
        probe=defects(p,got['y'])
        for key in ('full_fixed_point_residual','local_bsde_residual',
                    'z_sigma_equals_b_residual','terminal_residual','nominal_Y_error_bound'):
            match_float(probe[key],got['defects'][key],1e-11)
        require(probe['nominal_Y_error_bound']<=1.00001e-9 and
                probe['local_bsde_residual']<=2e-9, 'candidate out of registered tolerance')
        max_z=max(max_z,probe['z_sigma_equals_b_residual']);max_b=max(max_b,probe['nominal_Y_error_bound'])
        independent=direct_map(p,got['y'])
        require(max(abs(v-w) for v,w in zip(got['y'],independent))<1e-8,
                'independent information-state recursion disagrees')
        wrong_replayed=defects(p,wrong['y'])
        match_float(wrong_replayed['full_fixed_point_residual'],wrong['defects']['full_fixed_point_residual'],1e-11)
        require(wrong_replayed['terminal_residual']<1e-12,'not a valid wrong-leaf control')
        # Nonzero x0 and nonzero beta should show an observable reset failure.
        if p.x0 != 0:
            require(wrong_replayed['full_fixed_point_residual']>1e-5,
                    'malformed negative reset control')
        jumps.append(wrong_replayed['full_fixed_point_residual'])
        if p.steps<=5:
            n=row['newton']
            require(n is not None and n['authority']=='DENY_ALL'
                    and n['production_accepted'] is False and
                    n['independent_implementation'] is True and
                    n['roundoff_enclosed'] is False, 'independent Newton result missing')
            numerical_replay=newton(p)
            require(n['operator_calls']==numerical_replay['operator_calls'] and
                    max(abs(v-w) for v,w in zip(n['y'],numerical_replay['y']))<=1e-10,
                    'Newton reference or operation count changed')
            rn=direct_map(p,n['y'])
            require(max(abs(u-v) for u,v in zip(n['y'],rn))/(1-p.q)<=1.00001e-9,
                    'Newton residual recheck failed')
            deltas.append(max(abs(u-v) for u,v in zip(n['y'],got['y'])))
            newton_calls+=n['operator_calls']
            matched_picard_calls+=got['calls']
        else:
            require(row['newton'] is None,'unsafe unbounded dense Newton')
        if p.a==0:
            d=row['direct']
            require(d is not None and d['calls']==1 and d['production_accepted'] is False,
                    'cheap uncoupled baseline missing')
            verify_d=defects(p,d['y'])
            require(verify_d['full_fixed_point_residual']<=1e-12 and
                    max(abs(x-y) for x,y in zip(d['y'],got['y']))<=1e-12,
                    'BSDE cheap algebra violates same law')
            direct_calls+=d['calls']
        else:
            require(row['direct'] is None,'cheap baseline applied to coupled state')
        picard_calls+=got['calls']
        counts['completed']+=1
    require(counts==Counter({'completed':48,'unsupported':12}), 'unexpected complete sweep')
    return {'schema':SCHEMA,'kind':'independent_local_replay',
            'protocol_sha256':h(plan),'sealed_measurement_sha256':h(measure),
            'total_predeclared_profiles':60,'executed_admitted_profiles':48,
            'unsupported_global_regular_domain':12,
            'full_negative_reset_controls_checked':48,
            'independent_newton_comparisons':len(deltas),
            'max_root_difference_newton_picard':max(deltas),
            'max_wrong_reset_global_residual':max(jumps),
            'max_conditional_Z_sigma_minus_B':max_z,
            'max_nominal_discrete_picard_Y_error_bound':max_b,
            'total_picard_operator_calls':picard_calls,
            'matched_picard_operator_calls_on_newton_subset':matched_picard_calls,
            'total_independent_newton_operator_calls':newton_calls,
            'total_cheaper_direct_uncontrolled_operator_calls':direct_calls,
            'numerical_discrete_qualification_only':True,
            'continuous_time_FBSDE_qualification':False,
            'natural_task_reasoning_gain':False,
            'independent_external_observer_signed':False,
            'physical_CPU_times_independently_verified':False,
            'p5_accepted':False,'production_accepted':False,'authority':'DENY_ALL'}


def create_only(path,obj):
    with Path(path).open('xb') as f:
        f.write(canonical(obj)+b'\n')


def load(path):
    return json.loads(Path(path).read_text())


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    sub=cli.add_subparsers(dest='mode',required=True)
    for action in ('plan','execute','audit'):
        cmd=sub.add_parser(action)
        if action=='plan':cmd.add_argument('--output',required=True)
        if action=='execute':cmd.add_argument('--protocol',required=True);cmd.add_argument('--output',required=True)
        if action=='audit':cmd.add_argument('--protocol',required=True);cmd.add_argument('--sealed',required=True);cmd.add_argument('--output',required=True)
    args=cli.parse_args()
    if args.mode=='plan': out=prepare()
    elif args.mode=='execute':out=execute(load(args.protocol))
    else:out=audit(load(args.protocol),load(args.sealed))
    create_only(args.output,out)
    print(json.dumps({'file':args.output,'sha256':hashlib.sha256(Path(args.output).read_bytes()).hexdigest(),
                      'production_accepted':False,'authority':'DENY_ALL'},sort_keys=True))
if __name__=='__main__':main()
