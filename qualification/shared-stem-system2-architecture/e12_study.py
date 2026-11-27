"""E12 synthetic finite nonlinear FBSDE: source-sealed evaluation and re-audit.

All times are actual local process observations; no pretrained/Reader/model
calls, real-world effects, independent owner signatures, or capability claims.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
from time import process_time_ns, perf_counter_ns

from e12_nonlinear_cert import Law, State, Trace, Solve, operator, solve
from e12_independent_audit import audit, reference

SCHEMA = 'hepta.e12.nonlinear-stochastic-certified-study.v1'
PROFILES = tuple((d,a) for d in (1,2,3) for a in ('0','1/3'))
REPEATS=6


def read_strict(path: str, size_limit: int=1_000_000) -> tuple[dict,str]:
    raw=Path(path).read_bytes()
    if not 0<len(raw)<=size_limit:
        raise ValueError('missing or excessive independent source')
    def obj(pairs):
        result={}
        for k,v in pairs:
            if k in result:
                raise ValueError('duplicate JSON key')
            result[k]=v
        return result
    out=json.loads(raw,object_pairs_hook=obj,
                   parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite input')))
    return out,sha256(raw).hexdigest()


def write_once(path: str, output: dict) -> str:
    data=(json.dumps(output,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with open(path,'xb') as f:
        f.write(data)
    return sha256(data).hexdigest()


def one_pass(law: Law):
    n=2**law.depth-1
    zero=(F(0),)*n
    y=operator(law,zero)
    # ONE direct map is the correct exact solution only when a=0.
    # Evaluate the exact residual in a separate operator call; this
    # certification work must not be hidden in the one-pass cost.
    return y


def measure(f):
    cpu=process_time_ns()
    wall=perf_counter_ns()
    value=f()
    c,w=process_time_ns()-cpu,perf_counter_ns()-wall
    if c<=0 or w<=0:
        raise ValueError('missing actual CPU or wall measure')
    return value,c,w


def execute(output: str) -> str:
    rows=[]
    for d,a in PROFILES:
        law=Law(depth=d,a=a)
        cpu_direct=[]; cpu_cert=[];wall_direct=[];wall_cert=[]
        solver_result=None
        for _ in range(REPEATS):
            y,c,w=measure(lambda: one_pass(law))
            cpu_direct.append(c);wall_direct.append(w)
            solved,c,w=measure(lambda: solve(law))
            cpu_cert.append(c);wall_cert.append(w)
            if solver_result is not None and solved.trace!=solver_result.trace:
                raise ValueError('nondeterministic exact rational tree')
            solver_result=solved
            if audit(law,solved).certified is not True:
                raise ValueError('independent source certificate rejected')
        if solver_result is None:
            raise ValueError("no physical certified solver invocation")
        zero=(F(0),)*(2**law.depth-1)
        before=operator(law,zero)
        second=operator(law,before)
        p=law.values()
        resid=max(abs(x-z) for x,z in zip(before,second))
        err=resid/(1-p['q'])
        rows.append({
            'profile': asdict(law),
            'certificate': asdict(solver_result),
            'cheap_single_map': {
                'root_y': str(before[0]),
                'residual': str(resid),
                'root_error_bound': str(err),
                'certified_at_same_tolerance': err<=F(1,10000),
                'globally_exact_when_no_coupling': a=='0',
                'computation_is_a_different_budget_from_certification': True,
            },
            'cpu_single_map_ns': cpu_direct,
            'wall_single_map_ns': wall_direct,
            'cpu_certified_ns': cpu_cert,
            'wall_certified_ns': wall_cert,
        })
    return write_once(output,{
        'schema':SCHEMA,'authority':'DENY_ALL',
        'complete_registered_profiles':True,
        'repeat_count':REPEATS,
        'real_pretrained_encoder_forwards':0,
        'independent_natural_task_outcomes':False,
        'full_lifecycle_cost_or_target_host_attested':False,
        'continuous_time_fbsde_proven':False,
        'cost_adjusted_online_reasoning_gain':False,
        'production_accepted':False,
        'rows':rows,
    })


def _decode_cert(data: dict) -> Solve:
    from dataclasses import fields
    if type(data) is not dict or set(data)!={f.name for f in fields(Solve)}:
        raise ValueError('incomplete/unexpected certificate keys')
    trace=data['trace']
    if type(trace) is not dict or set(trace)!={'states','z'}:
        raise ValueError('invalid trace')
    if type(trace['states']) is not list or type(trace['z']) is not list:
        raise ValueError('untyped trace vectors')
    states=[]
    for item in trace['states']:
        if type(item) is not dict or set(item)!={'x','y'}:
            raise ValueError('bad state entry')
        states.append(State(**item))
    out=dict(data)
    out['trace']=Trace(tuple(states),tuple(trace['z']))
    return Solve(**out)


def review(source_path: str, expected_sha: str, output: str) -> str:
    data,sha=read_strict(source_path)
    if type(expected_sha) is not str or expected_sha!=sha:
        raise ValueError('changed source bytes after sealing')
    if (type(data) is not dict or set(data)!={
        'schema','authority','complete_registered_profiles','repeat_count',
        'real_pretrained_encoder_forwards','independent_natural_task_outcomes',
        'full_lifecycle_cost_or_target_host_attested','continuous_time_fbsde_proven',
        'cost_adjusted_online_reasoning_gain','production_accepted','rows'
    } or data['schema']!=SCHEMA or data['authority']!='DENY_ALL' or
        data['complete_registered_profiles'] is not True or
        type(data['repeat_count']) is not int or data['repeat_count']!=REPEATS or
        type(data['real_pretrained_encoder_forwards']) is not int or
        data['real_pretrained_encoder_forwards']!=0 or
        any(data[k] is not False for k in (
            'independent_natural_task_outcomes','full_lifecycle_cost_or_target_host_attested',
            'continuous_time_fbsde_proven','cost_adjusted_online_reasoning_gain',
            'production_accepted')) or type(data['rows']) is not list or len(data['rows'])!=len(PROFILES)):
        raise ValueError('unqualified or incomplete input research evidence')
    decisions=[]
    for row,(depth,a) in zip(data['rows'],PROFILES):
        if type(row) is not dict or set(row)!={
            'profile','certificate','cheap_single_map',
            'cpu_single_map_ns','wall_single_map_ns','cpu_certified_ns','wall_certified_ns',
        }:
            raise ValueError('wrong study row schema')
        law=Law(depth=depth,a=a)
        if row['profile']!=asdict(law):
            raise ValueError('research panel/profile drift')
        cert=_decode_cert(row['certificate'])
        judgement=audit(law,cert)
        if not judgement.certified:
            raise ValueError('independent whole path re-audit failed')
        # Same mathematical law, independently recompute the cheap source-only
        # one-map candidate and its global residual via prefix dictionary.
        z=(F(0),)*(2**depth-1)
        _xs,_us,first=reference(law,z)
        _xs,_us,again=reference(law,first)
        bound=max(abs(v-w) for v,w in zip(first,again))/(1-law.values()['q'])
        cheap={
            'root_y':str(first[0]),
            'residual':str(max(abs(v-w) for v,w in zip(first,again))),
            'root_error_bound':str(bound),
            'certified_at_same_tolerance':bound<=F(1,10000),
            'globally_exact_when_no_coupling':a=='0',
            'computation_is_a_different_budget_from_certification':True,
        }
        if row['cheap_single_map']!=cheap:
            raise ValueError('misrepresented cheap baseline or uncertified advantage')
        for key in ('cpu_single_map_ns','wall_single_map_ns','cpu_certified_ns','wall_certified_ns'):
            values=row[key]
            if type(values) is not list or len(values)!=REPEATS or any(
                type(v) is not int or not 0<v<10**12 for v in values
            ):
                raise ValueError('missing/forged shape of reported physical effort')
        decisions.append({
            'depth':depth,'coupling':a,
            'certificate_verified_on_entire_public_tree':True,
            'independent_iteration_replay':True,
            'root_y':cert.trace.states[0].y,
            'discrete_error_bound':cert.fixed_point_error_bound,
            'certified_solver_evaluations':cert.evaluations,
            'single_map_certified':cheap['certified_at_same_tolerance'],
            'same_registered_law':True,
            'natural_semantic_gain_proven':False,
        })
    return write_once(output,{
        'schema':'hepta.e12.independent-nonlinear-review.v1',
        'source_sha256':sha,
        'authority':'DENY_ALL',
        'registered_cases':len(PROFILES),
        'all_discrete_certificates_and_complete_trees_verified':True,
        'costs_are_self_observed_not_independently_attested':True,
        'continuous_or_neural_fbsde_proven':False,
        'natural_language_reasoning_gain':False,
        'production_accepted':False,
        'decisions':decisions,
    })


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('execute');a.add_argument('--output',required=True)
    b=sub.add_parser('audit');b.add_argument('--source',required=True)
    b.add_argument('--sha256',required=True);b.add_argument('--output',required=True)
    args=ap.parse_args()
    sha=execute(args.output) if args.mode=='execute' else review(args.source,args.sha256,args.output)
    print(json.dumps({'mode':args.mode,'sha256':sha,'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':
    main()
