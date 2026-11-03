"""Exact finite Bellman counterexample to a resource/mean-maturity-only boundary.

This is a newly and explicitly specified small control problem, not the training
task, not a continuous Brownian QVI solver, and not a fitted model benchmark.
It has physical resource accounting, two fixed-maturity obligations, evidence
states, optional early emissions, resets and a one-tick refractory period.
"""
from __future__ import annotations

from dataclasses import dataclass,asdict
from functools import lru_cache
import itertools
import json
import math
from pathlib import Path
import numpy as np
from scipy.linalg import expm

OUT=Path(__file__).resolve().parent/"results"


@dataclass(frozen=True)
class Specification:
    dt:float=.5
    horizon_ticks:int=8
    evidence:tuple=(0.,.5,1.,1.5,2.,2.5)
    upward_rate:float=4.0
    downward_rate:float=.35
    values:tuple=(1.0,1.0)
    initial_budget:int=2
    renewal_ticks:int=4
    renewal_resource_cost:int=1
    emission_resource_cost:int=1
    emission_utility_cost:float=.15
    refractory_ticks:int=1
    discount_rate:float=.1
    shock_tick:int=3
    shock_amount:int=2
    refill_tick:int=5
    refill_amount:int=1


class FiniteControlProblem:
    """State=(tick,evidence_index,budget_before_events,(deadlines),refractory).

    Deadlines are absolute ticks, -1 means removed. At each decision tick:
      exogenous shock/refill -> due renew/drop + optional single emit -> evolve.
    A real emission spends one resource, pays v_i*(Y-.15), removes item i,
    resets Y to0 and starts one tick of refractory. During refractory evidence
    is held at0, but resource events and maturity obligations still evolve.
    Renewal costs one resource and extends that item's due date by four ticks.
    At terminal left limit, every remaining item pays v_i*Y, with no new action.
    """
    def __init__(self,spec=Specification()):
        self.spec=spec
        n=len(spec.evidence)
        q=np.zeros((n,n))
        for j in range(n):
            if j+1<n:q[j,j+1]=spec.upward_rate
            if j>0:q[j,j-1]=spec.downward_rate
        q-=np.diag(q.sum(1))
        self.p=expm(q*spec.dt)
        self.beta=math.exp(-spec.discount_rate*spec.dt)

        @lru_cache(None)
        def value(state):
            if state[0]==spec.horizon_ticks:
                return self.terminal(state)
            return max(reward+self.beta*sum(prob*value(after) for prob,after in successors)
                       for _,reward,successors in self.transitions(state))
        self.value=value

    def exogenous(self,t,budget):
        s=self.spec
        if t==s.shock_tick:budget=max(budget-s.shock_amount,0)
        if t==s.refill_tick:budget+=s.refill_amount
        return budget

    def terminal(self,state):
        t,e,b,dead,r=state
        return self.spec.evidence[e]*sum(self.spec.values[j] for j,d in enumerate(dead) if d>=t)

    def transitions(self,state):
        t,e,before,dead,r=state;s=self.spec
        if t>=s.horizon_ticks:return []
        budget=self.exogenous(t,before)
        live=[j for j,d in enumerate(dead) if d>=t]
        due={j for j in live if dead[j]==t}
        emits=[-1]+(live if r==0 else [])
        out=[]
        for emit in emits:
            renewable=sorted(due-{emit})
            for indicators in itertools.product((0,1),repeat=len(renewable)):
                renew=tuple(j for j,keep in zip(renewable,indicators) if keep)
                cost=s.renewal_resource_cost*len(renew)+s.emission_resource_cost*(emit>=0)
                if cost>budget:continue
                updated=list(dead)
                for j in due:
                    updated[j]=dead[j]+s.renewal_ticks if j in renew else -1
                reward=0.
                next_e=e;next_r=r
                if emit>=0:
                    updated[emit]=-1
                    reward=s.values[emit]*(s.evidence[e]-s.emission_utility_cost)
                    next_e=0;next_r=s.refractory_ticks
                updated=tuple(updated)
                if next_r>0:
                    successors=[(1.,(t+1,0,budget-cost,updated,next_r-1))]
                else:
                    successors=[(float(prob),(t+1,ee,budget-cost,updated,0))
                                for ee,prob in enumerate(self.p[next_e]) if prob>0]
                out.append(((emit,renew),float(reward),successors))
        return out

    def q_values(self,state):
        return {action:reward+self.beta*sum(prob*self.value(after) for prob,after in successors)
                for action,reward,successors in self.transitions(state)}

    def optimal(self,state):
        q=self.q_values(state);best=max(q.values())
        return [action for action,value in q.items() if abs(value-best)<1e-10]

    def forward_policy_value(self,initial):
        """Independent forward distribution accumulation for the selected policy."""
        distribution={initial:1.}
        total=0.;spent=0.;removed=0.;added=0.
        expected_terminal_budget=0.;negative_mass=0.
        for t in range(self.spec.horizon_ticks+1):
            following={}
            for state,mass in distribution.items():
                _,_,before,_,_=state
                after_exo=self.exogenous(t,before)
                if t==self.spec.shock_tick:removed+=mass*(before-after_exo)
                if t==self.spec.refill_tick:added+=mass*(after_exo-before)
                if t==self.spec.horizon_ticks:
                    total+=self.beta**t*mass*self.terminal(state)
                    expected_terminal_budget+=mass*after_exo
                    continue
                selected=self.optimal(state)[0]
                action,reward,successors=next(row for row in self.transitions(state) if row[0]==selected)
                cost=after_exo-successors[0][1][2]
                spent+=mass*cost
                total+=self.beta**t*mass*reward
                for probability,following_state in successors:
                    if following_state[2]<0:negative_mass+=mass*probability
                    following[following_state]=following.get(following_state,0.)+mass*probability
            distribution=following
        residual=expected_terminal_budget-(initial[2]+added-removed-spent)
        return {"discounted_return":total,"expected_spent":spent,
                "expected_shock_removed":removed,"expected_refill_added":added,
                "expected_terminal_budget":expected_terminal_budget,
                "budget_conservation_residual":residual,"overdraft_probability":negative_mass}


def action_json(action):
    emit,renew=action
    return {"emit_item":None if emit<0 else emit,"renew_items":list(renew)}


def main():
    problem=FiniteControlProblem()
    spec=problem.spec
    profiles={"A":(2,6),"B":(4,4)}
    rows=[];counterexamples=[]
    for budget in (1,2,3):
        for e,y in enumerate(spec.evidence):
            states={name:(0,e,budget,dead,0) for name,dead in profiles.items()}
            qs={name:problem.q_values(state) for name,state in states.items()}
            optimal={name:problem.optimal(state) for name,state in states.items()}
            assert set(qs["A"])==set(qs["B"])
            common_actions=set(qs["A"])
            informed=.5*(max(qs["A"].values())+max(qs["B"].values()))
            best_collapsed=max(.5*(qs["A"][action]+qs["B"][action]) for action in common_actions)
            gap=informed-best_collapsed
            must_emit={name:all(action[0]>=0 for action in actions) for name,actions in optimal.items()}
            must_wait={name:all(action[0]<0 for action in actions) for name,actions in optimal.items()}
            row={"evidence":y,"budget":budget,"values":list(spec.values),
                "total_memory_value":sum(spec.values),"memory_count":2,"mean_deadline":2.,
                "profiles":{name:{"deadlines":[d*spec.dt for d in profiles[name]],
                    "value":problem.value(states[name]),"optimal_actions":[action_json(a) for a in optimal[name]],
                    "must_emit":must_emit[name],"must_wait":must_wait[name],
                    "q_values":[{"action":action_json(action),"value":value} for action,value in qs[name].items()]}
                    for name in profiles},
                "first_action_collapsed_information_regret_lower_bound":gap}
            rows.append(row)
            if (must_emit["A"] and must_wait["B"]) or (must_emit["B"] and must_wait["A"]):
                for name,state in states.items():
                    check=problem.forward_policy_value(state)
                    assert abs(check["discounted_return"]-problem.value(state))<1e-11
                    assert abs(check["budget_conservation_residual"])<1e-11
                    assert check["overdraft_probability"]==0
                    row["profiles"][name]["forward_policy_validation"]=check
                counterexamples.append(row)
    assert counterexamples,"Specified finite control problem did not yield a strict counterexample"
    assert all(row["first_action_collapsed_information_regret_lower_bound"]>1e-8 for row in counterexamples)
    report={"schema":"rrsnn.full-control-finite-bellman.v1","specification":asdict(spec),
        "evidence_transition_matrix":problem.p.tolist(),
        "states_evaluated":problem.value.cache_info().currsize,
        "initial_state_scan":"Every6 evidence states x budgets1,2,3; fixed specification, no model fitting.",
        "initial_state_rows":rows,"strict_emit_vs_wait_counterexamples":counterexamples,
        "conclusion":"At identical evidence, budget, retained values, item count and mean maturity, A/B require opposite first emission decisions. A policy seeing only those collapsed variables cannot be optimal in both.",
        "regret_bound":"For equal prior probability on A/B, let Q_A and Q_B allow all future controls to use full state. The gap (maxQ_A+maxQ_B)/2 - max_a(Q_A(a)+Q_B(a))/2 lower-bounds loss from a shared first action, including randomized first actions.",
        "limits":["Exact dynamic programming for the fully specified finite evidence chain and decision clock; not an analytic solution of the continuous QVI.",
                  "A/B is a constructed mathematical counterexample, not held-out model performance evidence.",
                  "The two deadlines are1 and3 versus2 and2; no other initial variable differs.",
                  "Known shock/refill and refractory time continue to evolve after an emission, which prevents scalar stationary renewal reduction.",
                  "All task rewards, costs, clock and reset choices are explicit; another task may have another optimal boundary."]}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"full_control_bellman.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"states":report["states_evaluated"],"strict_cases":len(counterexamples),
        "first_case":counterexamples[0]},indent=2),flush=True)


if __name__=="__main__":
    main()
