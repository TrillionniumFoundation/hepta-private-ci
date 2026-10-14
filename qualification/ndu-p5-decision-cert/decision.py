"""Cost-accounted early decision from nominal contraction bounds on a *discrete* coupled FBSDE.

This module does NOT issue a production, legal-action, safety, or global-continuum certificate.
Only compare candidate controls on one frozen objective and a registered globally
admitted finite-tree profile. FP64 bounds are not outward rounded.
"""
from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from time import process_time_ns, perf_counter_ns
import math
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ndu-p5-coupled-study'))
from coupled_binary import Profile, mapping, Unsupported


class NotCertified(ValueError):
    pass


@dataclass(frozen=True)
class Option:
    action_id: str
    a: float
    cost: float


@dataclass(frozen=True)
class Task:
    task_id: str
    x0: float
    horizon: float
    sigma: float
    beta: float
    lam: float
    steps: int
    options: tuple[Option, ...]

    def validate(self):
        if type(self.task_id) is not str or not 1 <= len(self.task_id) <= 128:
            raise NotCertified('unbound task identity')
        if not 2 <= len(self.options) <= 4 or len({v.action_id for v in self.options}) != len(self.options):
            raise NotCertified('different or duplicated action set')
        if any(type(a.action_id) is not str or not a.action_id or a.action_id=='abstain' or len(a.action_id)>64 or
               type(a.cost) not in (int,float) or not math.isfinite(a.cost) or not 0 <= a.cost <= .5
               for a in self.options):
            raise NotCertified('unsupported action cost')
        for option in self.options:
            try:
                self.profile(option).validate()
            except Unsupported as exc:
                raise NotCertified('unqualified global discrete model') from exc
        return self

    def profile(self, option):
        return Profile(steps=self.steps,horizon=self.horizon,a=option.a,
                       beta=self.beta,lam=self.lam,sigma=self.sigma,x0=self.x0)


def candidate(task, option):
    profile=task.profile(option)
    y=[0.0]*(2**profile.steps-1)
    return {'option':option,'p':profile,'y':y,'mapped':None,'calls':0}


def refresh(st):
    st['mapped']=mapping(st['p'],st['y'])
    st['calls']+=1


def entry(st):
    y=st['y'];mapped=st['mapped'];p=st['p'];o=st['option']
    residual=max(abs(v-w) for v,w in zip(y,mapped))
    radius=residual/(1-p.q)
    center=y[0]-o.cost
    return {'action_id':o.action_id,'cost':o.cost,'a':o.a,
            'y':list(y),'radius':radius,'lower':center-radius,'upper':center+radius,
            'calls':st['calls'],'contraction_q':p.q,'residual':residual}


def best_certified(entries):
    # Registered legal stop/abstain carries known value zero at no solver cost.
    all_entries=[{'action_id':'abstain','lower':0.0,'upper':0.0}]+entries
    lower_winner=max(all_entries,key=lambda x:x['lower'])
    runner_up=max(x['upper'] for x in all_entries if x['action_id']!=lower_winner['action_id'])
    if lower_winner['lower']>runner_up+1e-12:
        return lower_winner['action_id'],lower_winner['lower']-runner_up
    return None,lower_winner['lower']-runner_up


def certify(task,*,max_calls=90):
    task.validate()
    if type(max_calls) is not int or not len(task.options)<=max_calls<=200:
        raise NotCertified('invalid registered work budget')
    t0=process_time_ns();w0=perf_counter_ns()
    states=[candidate(task,opt) for opt in task.options]
    for st in states:refresh(st)
    while True:
        es=[entry(st) for st in states]
        winner,margin=best_certified(es)
        used=sum(st['calls'] for st in states)
        if winner is not None or used==max_calls:
            return {'choice':winner,'certified_nominal':winner is not None,
                    'positive_gap_lower_bound':margin if winner else None,
                    'budget_exhausted':winner is None,'work_calls':used,
                    'per_action':es,'cpu_ns':max(1,process_time_ns()-t0),
                    'wall_ns':max(1,perf_counter_ns()-w0),
                    'continuum_or_FP64_rigorous_certificate':False,
                    'production_accepted':False,'authority':'DENY_ALL'}
        # Refine only actions whose upper bound can still beat the best lower bound.
        pivot=max([{'lower':0.0}]+es,key=lambda x:x['lower'])['lower']
        viable=[i for i,e in enumerate(es) if e['upper']>=pivot-1e-12]
        if not viable:
            raise NotCertified('inconsistent candidate frontier')
        i=max(viable,key=lambda j:(es[j]['radius'],es[j]['upper'],-j))
        st=states[i]
        st['y']=st['mapped']
        refresh(st)


def cheap_and_fixed(task,*,fixed_steps=4):
    task.validate()
    if type(fixed_steps) is not int or not 1<=fixed_steps<=20:
        raise NotCertified('bounded depth required')
    from time import process_time_ns
    n=2**task.steps-1
    cpu=process_time_ns()
    one=[('abstain',0.0)];fixed=[('abstain',0.0)]
    for option in task.options:
        p=task.profile(option)
        y=[0.0]*n
        for k in range(fixed_steps):
            y=mapping(p,y)
            if k==0: one.append((option.action_id,y[0]-option.cost))
        fixed.append((option.action_id,y[0]-option.cost))
    return {'cheap_one_map':max(one,key=lambda q:q[1])[0],
            'cheap_one_map_calls':len(task.options),
            'fixed_depth':max(fixed,key=lambda q:q[1])[0],
            'fixed_depth_calls':fixed_steps*len(task.options),
            'cpu_ns':max(1,process_time_ns()-cpu)}
