"""Read-only, independent event-calendar DP audit of the resource task.

The reference below does not call resource_env.transition, legal_actions,
next_deadlines, exogenous, or Scenario.events. It keeps actual per-item renewal
deadlines and independently enumerates feasible actions at the next event.
"""
from functools import lru_cache
import argparse
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import resource_env as re


def independent_optimum(s):
    @lru_cache(None)
    def solve(deadlines,budget,shock_pending,refill_pending):
        event=min([s.horizon]+[d for d in deadlines if math.isfinite(d)]+
                  ([s.shock_time] if shock_pending else [])+
                  ([s.refill_time] if refill_pending else []))
        budget_after=budget
        if shock_pending and abs(event-s.shock_time)<1e-8:
            budget_after=max(0,budget_after-s.shock_amount)
            shock_pending=False
        if refill_pending and abs(event-s.refill_time)<1e-8:
            budget_after+=s.refill_amount
            refill_pending=False
        if event>=s.horizon-1e-8:
            return sum(s.values[i] for i,d in enumerate(deadlines) if math.isfinite(d))
        due=[i for i,d in enumerate(deadlines) if abs(d-event)<1e-8]
        best=-math.inf
        for actions in product((0,1,2),repeat=len(due)):
            cost=sum(a!=0 for a in actions)
            if cost>budget_after:
                continue
            nxt=list(deadlines);instant=0.
            for i,action in zip(due,actions):
                if action==0:
                    nxt[i]=math.inf
                elif action==1:
                    nxt[i]=event+s.renewal_period
                else:
                    nxt[i]=math.inf
                    instant+=s.values[i]*math.exp(-s.early_penalty*(s.horizon-event))
            best=max(best,instant+solve(tuple(nxt),budget_after-cost,shock_pending,refill_pending))
        return best
    value=solve(tuple(s.deadlines),s.budget,True,True)
    return value,solve.cache_info().currsize


def audit():
    rng=np.random.default_rng(61417)
    cases=[re.make_scenario(rng,split=split) for split in ('test','future') for _ in range(40)]
    cases += [re.Scenario(values=(1.4,1.2,.7,.5),deadlines=deadlines,budget=budget,
                  shock_amount=shock,refill_amount=refill)
              for deadlines in [(1.,1.,3.,3.),(2.,2.,2.,2.),(5.,5.,5.,5.)]
              for budget,shock,refill in [(0,0,0),(0,2,2),(4,2,1)]]
    differences=[];states=0
    for s in cases:
        oracle=re.Oracle(s).value(0,15,s.budget)
        independent,count=independent_optimum(s)
        states+=count
        error=abs(oracle-independent)
        if error>1e-10:
            raise AssertionError({'scenario':s,'oracle':oracle,'independent':independent})
        differences.append(error)
    source=Path(re.__file__).read_bytes()
    result={'scope':'Read-only independent mathematical/ledger audit of the synthetic resource task.',
        'resource_source_sha256':hashlib.sha256(source).hexdigest(),
        'scenario_count':len(cases),'independent_states_evaluated':states,
        'maximum_oracle_absolute_error':max(differences),'all_oracle_values_matched':True,
        'independent_method':'Actual per-item deadline tuples plus exhaustive feasible choices; no reuse of the environment transition, legal_actions, next_deadlines, events, or exogenous helpers.',
        'review_findings':['The task defines only maturity-time drop/renew/emit actions, not arbitrary pre-deadline intervention.',
            'Initial item values and the exogenous budget schedule are visible at time zero; this is announced-shock memory/planning, not unforeseen-shock forecasting.',
            'The same feasibility mask enforces the budget constraint for all models; zero overdrafts are an environment guarantee.',
            'The initial rollout API exposed oracle q-values to policy callbacks; root was asked to isolate learned callbacks from the oracle.',
            'Root was asked to assert utility never exceeds the oracle instead of letting max(regret,0) hide violations.']}
    out=Path(__file__).resolve().parent/'results/resource_independent_audit.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


def audit_interface_fix():
    """Verify only the requested policy/oracle isolation and guard fix."""
    path=Path(__file__).resolve().parent/'results/resource_independent_audit.json'
    result=json.loads(path.read_text())
    s=re.Scenario(values=(1.4,1.2,.7,.5),deadlines=(1.,1.,3.,3.),budget=4,
                  shock_amount=2,refill_amount=1)
    callback_calls=[]
    def policy(history,dt,valid):
        assert history.shape[1]==22 and valid.shape==(81,)
        callback_calls.append({'history_rows':len(history),'input_columns':history.shape[1]})
        return int(np.flatnonzero(valid)[-1])
    original_q=re.Oracle.q_values
    def denied_q(*args,**kwargs):
        raise AssertionError('Ordinary rollout attempted to access oracle Q values')
    re.Oracle.q_values=denied_q
    try:
        ordinary=re.rollout(s,policy)
    finally:
        re.Oracle.q_values=original_q
    oracle=re.rollout(s,use_oracle=True)
    assert ordinary['utility']<=oracle['utility']+1e-10
    invalid_modes=0
    for call in [lambda:re.rollout(s),lambda:re.rollout(s,policy,use_oracle=True)]:
        try:
            call()
        except ValueError:
            invalid_modes+=1
    assert invalid_modes==2 and callback_calls
    original_oracle=re.Oracle
    class UnderreportingOracle(original_oracle):
        def __init__(self,scenario):
            super().__init__(scenario)
            self.value=lambda *args:0.0
    re.Oracle=UnderreportingOracle
    guard=False
    try:
        re.rollout(s,policy)
    except AssertionError as error:
        assert 'exceeds its exact oracle' in str(error)
        guard=True
    finally:
        re.Oracle=original_oracle
    assert guard
    result['interface_fix_review']={
        'status':'passed','current_source_sha256':hashlib.sha256(Path(re.__file__).read_bytes()).hexdigest(),
        'ordinary_policy_arguments':['history_22_features','elapsed_intervals','legal_actions'],
        'ordinary_rollout_with_q_values_disabled':'passed',
        'explicit_oracle_mode':'passed','invalid_mode_combinations_rejected':invalid_modes,
        'injected_underreported_oracle_triggers_guard':guard,
        'scope':'Only the callback-isolation/over-oracle guard change was rechecked; the preceding 89-scenario independent DP proof was not unnecessarily repeated.'}
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['interface_fix_review'],indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-interface-only',action='store_true')
    args=parser.parse_args()
    if args.check_interface_only:
        audit_interface_fix()
    else:
        audit()
