"""Known-law headroom on the retained JAC task; no fitting or new samples.

The point computation reuses the source DP. A separate outward-rounded rational
interval DP encloses real exp/log using finite series with explicit remainders.
Its model interprets source floats as exact binary rationals and normalizes each
row exactly. This is a certificate for that declared finite artifact model.
"""
import argparse
from dataclasses import asdict
from fractions import Fraction as F
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import statistics

from ..ndu_jac.core import evaluate, optimal_policy
from ..ndu_jac.finite_study import build_problem

SCALE = 1 << 80
EXP_TERMS = 40
LOG_TERMS = 80


def rounded(lo, hi):
    if lo > hi:
        raise ArithmeticError('Reversed interval')
    return F(lo.numerator*SCALE//lo.denominator, SCALE), F(-((-hi.numerator*SCALE)//hi.denominator), SCALE)


def add(x, y):
    return rounded(x[0]+y[0], x[1]+y[1])


def scale(x, c):
    a,b=x[0]*c,x[1]*c
    return rounded(min(a,b),max(a,b))


def multiply(x, y):
    candidates=[a*b for a in x for b in y]
    return rounded(min(candidates),max(candidates))


@lru_cache(None)
def exp_point(x):
    if abs(x)>8:
        raise ValueError('Series certificate is restricted to |argument| <= 8')
    if x<0:
        lo,hi=exp_point(-x)
        return rounded(1/hi,1/lo)
    term=total=(F(1),F(1))
    for k in range(1,EXP_TERMS+1):
        term=scale(term,x/k)
        total=add(total,term)
    next_term=scale(term,x/(EXP_TERMS+1))
    # Later positive term ratios are bounded by x/(N+2) < 1.
    tail=next_term[1]/(1-x/(EXP_TERMS+2))
    return rounded(total[0],total[1]+tail)


def exp_interval(x):
    return exp_point(x[0])[0],exp_point(x[1])[1]


@lru_cache(None)
def log_point(x):
    if x<=0:
        raise ValueError('Logarithm requires positive mass')
    z=(x-1)/(x+1)
    sign=1 if z>=0 else -1
    z=abs(z)
    zi=rounded(z,z)
    square=multiply(zi,zi)
    if square[1]>=1:
        raise ArithmeticError('Atanh remainder bound lacks a positive denominator')
    power,total=zi,(F(0),F(0))
    for k in range(LOG_TERMS):
        total=add(total,scale(power,F(1,2*k+1)))
        power=multiply(power,square)
    # log(x)=2 sum z^(2k+1)/(2k+1), with the sign restored below.
    tail=2*power[1]/((2*LOG_TERMS+1)*(1-square[1]))
    positive=rounded(2*total[0],2*total[1]+tail)
    return scale(positive,F(sign))


def log_interval(x):
    return log_point(x[0])[0],log_point(x[1])[1]


def interval_values(nodes, root, eta, rho, policy=None):
    """Independent recursive interval solver; policy=None optimizes all rows."""
    eta,rho=F(eta),F(rho)
    cache,active={},set()
    def visit(s):
        if s in cache:return cache[s]
        if s in active:raise ValueError('Cycle in finite known support')
        active.add(s)
        rows=nodes[s]
        if policy is not None:
            if set(policy[s])!=set(rows) or any(p not in (0,1) for p in policy[s].values()) or sum(policy[s].values())!=1:
                raise ValueError('Headroom baseline must be the stored deterministic actor extraction')
            rows={a:law for a,law in rows.items() if policy[s][a]==1}
        qs=[]
        for law in rows.values():
            total_p=sum((F(o.probability) for o in law),F(0))
            moment=(F(0),F(0))
            for o in law:
                immediate=F(o.reward)-F(o.cost)-F(o.adjustment_cost)
                branch=(immediate,immediate)
                if o.next_state is not None:
                    discount=exp_point(-rho*F(o.duration))
                    branch=add(branch,multiply(discount,visit(o.next_state)))
                moment=add(moment,scale(exp_interval(scale(branch,-eta)),F(o.probability)/total_p))
            qs.append(scale(log_interval(moment),-1/eta))
        result=(max(q[0] for q in qs),max(q[1] for q in qs))
        active.remove(s);cache[s]=result
        return result
    return visit(root)


def enclosure(x):
    return {'lower':str(x[0]),'upper':str(x[1]),'lower_float':float(x[0]),
            'upper_float':float(x[1]),'width_float':float(x[1]-x[0])}


def run(evidence, corrected_result):
    accepted_bytes=corrected_result.read_bytes()
    accepted=json.loads(accepted_bytes)
    protocol=accepted['protocol']
    input_bytes=evidence.read_bytes()
    if hashlib.sha256(input_bytes).hexdigest()!=protocol['source_evidence_sha256']:
        raise ValueError('Historical evidence identity changed')
    banks=json.loads(input_bytes)['rows']
    nodes,root,_=build_problem()
    eta,rho=protocol['eta'],protocol['rho']
    fee=F(str(protocol['fee']))
    optimum=optimal_policy(nodes,root,eta,rho)
    oracle_interval=interval_values(nodes,root,eta,rho)
    rows=[]
    for bank in banks:
        baseline=bank['policies']['vanilla_argmax']
        value=evaluate(nodes,root,baseline,eta,rho)['value']
        baseline_interval=interval_values(nodes,root,eta,rho,baseline)
        headroom=(max(F(0),oracle_interval[0]-baseline_interval[1]),
                  max(F(0),oracle_interval[1]-baseline_interval[0]))
        if abs(value-float(sum(baseline_interval)/2))>1e-12:
            raise ArithmeticError('Source-point and independent real-law calculations disagree')
        if headroom[1]>=fee:
            raise ArithmeticError('The diagnostic did not establish the requested fee ceiling')
        rows.append({'seed':bank['seed'],'split':bank['split'],'bank_sha256':bank['bank_sha256'],
            'baseline_value':value,'known_law_optimum':optimum['value'],
            'point_headroom':optimum['value']-value,'baseline_interval':enclosure(baseline_interval),
            'headroom_interval':enclosure(headroom),'paid_gain_upper':str(headroom[1]-fee),
            'paid_gain_upper_float':float(headroom[1]-fee),'fee_exceeds_headroom':True})
    sum_upper=sum((F(r['headroom_interval']['upper']) for r in rows),F(0))
    max_upper=max(F(r['headroom_interval']['upper']) for r in rows)
    if abs(optimum['value']-float(sum(oracle_interval)/2))>1e-12:
        raise ArithmeticError('Known-law point and interval optimum disagree')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),
        Path(__file__).with_name('confidence.py'),Path(__file__).parents[1]/'ndu_jac/core.py',
        Path(__file__).parents[1]/'ndu_jac/finite_study.py']}
    for name in ('core.py','finite_study.py','confidence.py'):
        if hashes[name]!=accepted['source_sha256'][name]:
            raise ValueError('Known-law source differs from corrected evidence identity')
    return {'schema':'ndu-jac.retained-task-known-law-headroom.v1','source_sha256':hashes,
        'historical_evidence_sha256':hashlib.sha256(input_bytes).hexdigest(),
        'corrected_result_sha256':hashlib.sha256(accepted_bytes).hexdigest(),
        'model_sha256':hashlib.sha256(json.dumps({'root':root,'eta':eta,'rho':rho,
            'nodes':{s:{a:[asdict(o) for o in law] for a,law in row.items()} for s,row in nodes.items()}},
            sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'state_count':len(nodes),'state_action_count':sum(map(len,nodes.values())),
        'new_samples':0,'new_fits':0,'new_model_calls':0,'fee_fraction':str(fee),
        'fee_scope':'Exactly the existing one-episode .01 synthetic audit-charge convention; no changed amortization or currency claim.',
        'interval_model':'Finite source float metadata interpreted as exact binary rationals, row probabilities normalized exactly, real exp/log enclosed by rational series with explicit tails and dyadic outward rounding.',
        'interval_parameters':{'dyadic_bits':80,'exp_terms':EXP_TERMS,'log_terms':LOG_TERMS},
        'known_law_optimum':optimum['value'],'known_law_optimum_interval':enclosure(oracle_interval),
        'baseline_mean':statistics.mean(r['baseline_value'] for r in rows),
        'point_headroom_max':max(r['point_headroom'] for r in rows),
        'point_headroom_mean':statistics.mean(r['point_headroom'] for r in rows),
        'point_headroom_sum':sum(r['point_headroom'] for r in rows),
        'point_optimum_equal_bank_count':sum(r['point_headroom']==0 for r in rows),
        'positive_point_headroom_seeds':[r['seed'] for r in rows if r['point_headroom']>0],
        'max_headroom_upper':str(max_upper),'max_headroom_upper_float':float(max_upper),
        'mean_headroom_upper':str(sum_upper/len(rows)),'mean_headroom_upper_float':float(sum_upper/len(rows)),
        'sum_headroom_upper':str(sum_upper),'sum_headroom_upper_float':float(sum_upper),
        'max_paid_gain_upper_float':float(max_upper-fee),
        'mean_paid_gain_upper_float':float(sum_upper/len(rows)-fee),
        'all_banks_have_negative_paid_oracle_ceiling':all(r['fee_exceeds_headroom'] for r in rows),
        'even_one_shared_fee_exceeds_20_episode_total_headroom':sum_upper<fee,
        'total_gain_upper_with_one_shared_fee':str(sum_upper-fee),
        'total_gain_upper_with_one_shared_fee_float':float(sum_upper-fee),
        'rows':rows,'conclusion':'The old task and .01 per-update tariff have no positive headroom even for known-law optimal policies. Better confidence precision alone cannot pass this frozen gate. This is not a general impossibility claim and not a new RL advantage.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--corrected-result',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Refuse to overwrite a headroom receipt')
    result=run(args.evidence,args.corrected_result)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','source_sha256')},indent=2))
