"""Audit conditional counterfactuals without reusing the Bellman recursion."""

from dataclasses import asdict, replace
from itertools import product
import json
from pathlib import Path

import numpy as np

from oracle import Oracle
from run import configurations
from task import ACTIONS, World, execute, initial, legal, rollout


def conditional_worlds(config, state):
    n = len(config.packets)
    rows = []
    total = 0
    for truth, votes, failures in product((0,1), product((0,1),repeat=n), product((False,True),repeat=n)):
        mass = config.prior if truth else 1-config.prior
        consistent = True
        for i,(vote,fail,p) in enumerate(zip(votes,failures,config.packets)):
            mass *= (p.reliability if vote==truth else 1-p.reliability)
            mass *= (p.failure_probability if fail else 1-p.failure_probability)
            if i < len(state.history):
                bit = state.history[i]
                consistent &= (fail if bit=="x" else not fail and vote==int(bit))
        if mass and consistent:
            rows.append((World(truth,votes,failures),mass))
            total += mass
    return [(w,p/total) for w,p in rows]


def audit():
    configs = configurations(5001, 12)
    records = []
    guards = []
    for c in configs:
        teacher = Oracle(c)
        teacher.q(initial(c))
        states = sorted(teacher.states.values(),key=lambda s:s.key)
        # Deterministic dispersed sample includes revealed histories and recovery.
        take = np.unique(np.linspace(0,len(states)-1,min(12,len(states))).astype(int))
        for index in take:
            s = states[index]
            worlds = conditional_worlds(c,s)
            q = teacher.q(s)
            for a in legal(c,s):
                actual = sum(mass*rollout(c,w,teacher.policy,start=s,forced_first=a)["utility"]
                             for w,mass in worlds)
                error=abs(actual-q[ACTIONS.index(a)])
                records.append({"state":s.key,"action":a,"conditional_worlds":len(worlds),
                                "enumerated_utility":actual,"teacher_q":q[ACTIONS.index(a)],"abs_error":error})
                assert error < 2e-12
        class UnreadableWorld:
            def __getattribute__(self, name):
                raise AssertionError("private world was inspected before a READ")
        for a in ("STOP","WAIT"):
            nxt,receipt=execute(c,initial(c),UnreadableWorld(),a)
            guards.append(receipt)
        exhausted=replace(c,budget=0)
        nxt,receipt=execute(exhausted,initial(exhausted),UnreadableWorld(),"READ")
        assert receipt["actual"]=="STOP" and not receipt["read_attempted"]
        assert abs(nxt.paid_cost-c.invalid_cost-c.stop_cost)<1e-15
        guards.append(receipt)
    # Cost sweep is a task-value boundary, not a smooth-pasting assumption.
    base=configs[0]
    boundary=[]
    for cost in np.linspace(0,.30,61):
        c=replace(base,prior=.5,read_cost=float(cost),refractory_ticks=0)
        teacher=Oracle(c)
        s=initial(c)
        q=teacher.q(s)
        boundary.append({"read_cost":cost,"read_advantage":q[0]-max(q[1:]),
                         "optimal_action":teacher.policy(c,s),"initial_value":max(q)})
    report={"schema":"hepta.r10.conditional-audit.v1","counterfactuals":records,
            "max_abs_error":max(x["abs_error"] for x in records),
            "private_access_guard_cases":len(guards),"guard_receipts":guards,
            "cost_sweep_config":replace(base,prior=.5,refractory_ticks=0).to_dict(),"cost_sweep":boundary,
            "scope":"finite conditional evidence task; independent latent-world summation; not native execution"}
    path=Path(__file__).parent/"evidence/conditional_audit.json"
    path.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"conditional_action_values":len(records),"max_abs_error":report["max_abs_error"],
                      "private_access_guards":len(guards)}))


if __name__=="__main__":
    audit()
