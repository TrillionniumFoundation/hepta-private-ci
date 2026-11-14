"""An explicit finite-budget renewal task and independent dynamic-programming oracle.

Four memory obligations have known initial values and maturities. Values and the
future budget schedule are observed once at time zero. At each maturity the
policy can drop, renew for two time units, or emit an early result. Renewing and
emitting each cost one budget unit. Emission yields a discounted item value and
removes that item. Remaining live items are queried at the terminal left limit.
No model may overdraw the ledger; all share exactly the same feasible-action
mask. The oracle solves this specified synthetic task, not a neural QVI.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from functools import lru_cache
from itertools import product
from pathlib import Path
import hashlib
import json
import math
import numpy as np

FEATURES = ['value_cue_0','value_cue_1','value_cue_2','value_cue_3',
 'budget_over_6','live_fraction','mean_remaining_over_4',
 'remaining_0_over_4','remaining_1_over_4','remaining_2_over_4','remaining_3_over_4',
 'live_0','live_1','live_2','live_3','shock_amount_cue_over_3','shock_time_cue_over_4',
 'refill_amount_cue_over_2','refill_time_cue_over_4','time_over_4','initial_cue',
 'renewal_unit_cost_over_6']
ACTION_DIGITS=np.asarray(list(product(range(3), repeat=4)),dtype=np.int8)
N_ACTIONS=len(ACTION_DIGITS)
MAX_STEPS=16
EPS=1e-8

@dataclass(frozen=True)
class Scenario:
    values: tuple[float,float,float,float]
    deadlines: tuple[float,float,float,float]
    budget: int
    shock_amount: int
    refill_amount: int
    shock_time: float=1.5
    refill_time: float=2.5
    horizon: float=4.0
    renewal_period: float=2.0
    early_penalty: float=0.15
    profile: str='A'
    split: str='train'

    def events(self):
        times={0.0,self.horizon,self.shock_time,self.refill_time,1.0,2.0,3.0}
        for initial in self.deadlines:
            d=initial
            while d<self.horizon-EPS:
                times.add(round(d,8))
                d+=self.renewal_period
        times=sorted(t for t in times if -EPS<=t<=self.horizon+EPS)
        if len(times)>MAX_STEPS:
            raise ValueError('Scenario exceeds the pre-registered maximum sequence length')
        return tuple(times)


def next_deadlines(s: Scenario,time:float):
    initial=np.asarray(s.deadlines)
    multiples=np.maximum(np.ceil((time-initial-EPS)/s.renewal_period),0)
    return initial+multiples*s.renewal_period


def exogenous(s: Scenario,time:float,budget:int):
    before=budget
    removed=added=0
    if abs(time-s.shock_time)<EPS:
        removed=min(budget,s.shock_amount)
        budget-=removed
    if abs(time-s.refill_time)<EPS:
        added=s.refill_amount
        budget+=added
    return budget,removed,added


def state_features(s: Scenario,time:float,live:int,budget:int):
    x=np.zeros(22,dtype=np.float32)
    alive=np.array([(live>>i)&1 for i in range(4)],dtype=bool)
    remaining=np.maximum(next_deadlines(s,time)-time,0)*alive
    if time==0:
        x[:4]=s.values
        x[15:19]=[s.shock_amount/3,s.shock_time/4,s.refill_amount/2,s.refill_time/4]
        x[20]=1
    x[4]=budget/6
    x[5]=alive.mean()
    x[6]=remaining[alive].mean()/4 if alive.any() else 0
    x[7:11]=remaining/4
    x[11:15]=alive
    x[19]=time/4
    x[21]=1/6
    return x


def legal_actions(s: Scenario,time:float,live:int,budget:int):
    alive=np.array([(live>>i)&1 for i in range(4)],dtype=bool)
    due=alive & (np.abs(next_deadlines(s,time)-time)<EPS)
    if time>=s.horizon-EPS:
        due[:]=False
    act=ACTION_DIGITS
    mask=np.all((act==0)|due[None,:],axis=1) & ((act>0).sum(axis=1)<=budget)
    return mask,due


def transition(s: Scenario,time:float,live:int,budget:int,action:int):
    valid,due=legal_actions(s,time,live,budget)
    if not (0<=action<N_ACTIONS and valid[action]):
        raise ValueError('Infeasible action; resource overdraft or action on a non-due obligation')
    digits=ACTION_DIGITS[action]
    cost=int((digits>0).sum())
    emitted=0.0
    renewals=emissions=dropped=0
    for i in np.flatnonzero(due):
        if digits[i]==0:
            live &= ~(1<<int(i));dropped+=1
        elif digits[i]==1:
            renewals+=1
        else:
            live &= ~(1<<int(i));emissions+=1
            emitted+=s.values[i]*math.exp(-s.early_penalty*(s.horizon-time))
    return live,budget-cost,emitted,{'cost':cost,'renewals':renewals,'emissions':emissions,'dropped':dropped}


class Oracle:
    def __init__(self,s:Scenario):
        self.s=s;self.times=s.events();self.visited=0

        @lru_cache(None)
        def value(index,live,budget_before):
            self.visited+=1
            time=self.times[index]
            budget,_,_=exogenous(s,time,budget_before)
            if index==len(self.times)-1:
                return sum(s.values[i] for i in range(4) if (live>>i)&1)
            valid,_=legal_actions(s,time,live,budget)
            best=-math.inf
            for action in np.flatnonzero(valid):
                live2,budget2,reward,_=transition(s,time,live,budget,int(action))
                best=max(best,reward+value(index+1,live2,budget2))
            return best
        self.value=value

    def q_values(self,index,live,budget_after):
        time=self.times[index]
        valid,_=legal_actions(self.s,time,live,budget_after)
        q=np.full(N_ACTIONS,-np.inf)
        if index==len(self.times)-1:
            q[0]=sum(self.s.values[i] for i in range(4) if (live>>i)&1)
            return q
        for action in np.flatnonzero(valid):
            live2,budget2,reward,_=transition(self.s,time,live,budget_after,int(action))
            q[action]=reward+self.value(index+1,live2,budget2)
        return q

    def demonstration(self):
        s=self.s
        xs=[];dts=[];valids=[];optimals=[];decisions=[];actions=[]
        live=15;budget=s.budget;last=-0.1
        for index,time in enumerate(self.times):
            budget,_,_=exogenous(s,time,budget)
            xs.append(state_features(s,time,live,budget))
            dts.append(max(time-last,0.1));last=time
            valid,due=legal_actions(s,time,live,budget)
            q=self.q_values(index,live,budget)
            optimal=valid & (q>=np.max(q)-1e-9)
            action=int(np.flatnonzero(optimal)[0])
            valids.append(valid);optimals.append(optimal);decisions.append(bool(due.any()));actions.append(action)
            if index<len(self.times)-1:
                live,budget,_,_=transition(s,time,live,budget,action)
        n=len(xs)
        x=np.zeros((MAX_STEPS,22),dtype=np.float32);x[:n]=xs
        dt=np.full(MAX_STEPS,.1,dtype=np.float32);dt[:n]=dts
        valid=np.zeros((MAX_STEPS,N_ACTIONS),dtype=bool);valid[:,0]=True;valid[:n]=valids
        optimal=valid.copy();optimal[:n]=optimals
        decision=np.zeros(MAX_STEPS,dtype=bool);decision[:n]=decisions
        return x,dt,valid,optimal,decision,np.asarray(actions),n


def make_scenario(rng,profile=None,split='train'):
    if profile is None:
        profile=str(rng.choice(['A','B','C']))
    if split=='future':
        patterns={'A':[.75,1.25,2.75,3.25],'B':[1.75,1.75,2.25,2.25],
                  'C':[1.0,1.5,2.5,3.0]}
        # Same information format, shifted maturity shape, costs-in-time and values.
        values=tuple(np.round(rng.uniform(.1,1.9,4),6))
        shock_time,refill_time=1.25,2.75
        budget=int(rng.integers(2,6));shock=int(rng.integers(1,4));refill=int(rng.integers(0,3))
    else:
        patterns={'A':[1.,1.,3.,3.],'B':[2.,2.,2.,2.],
                  'C':[1.5,1.5,2.5,2.5]}
        values=tuple(np.round(rng.uniform(.25,1.5,4),6))
        shock_time,refill_time=1.5,2.5
        budget=int(rng.integers(2,6));shock=int(rng.integers(0,3));refill=int(rng.integers(0,3))
    deadlines=np.array(patterns[profile]);rng.shuffle(deadlines)
    return Scenario(values,tuple(deadlines),budget,shock,refill,shock_time,refill_time,
                    profile=profile,split=split)


def make_dataset(n,seed,split):
    rng=np.random.default_rng(seed)
    scenarios=[make_scenario(rng,split=split) for _ in range(n)]
    records=[Oracle(s).demonstration() for s in scenarios]
    names=['x','dt','valid','optimal','decision']
    arrays={name:np.stack([record[j] for record in records]) for j,name in enumerate(names)}
    arrays['lengths']=np.array([record[-1] for record in records])
    return scenarios,arrays


def rollout(s:Scenario,policy=None,*,use_oracle=False):
    """Execute a policy with observations only; oracle access is an explicit mode.

    Ordinary policy receives (history, elapsed_intervals, legal_actions). It is
    never given Q values, future labels, or the internal Scenario object.
    """
    if use_oracle == (policy is not None):
        raise ValueError('Choose either an observation-only policy or explicit oracle mode')
    oracle=Oracle(s)
    live=15;budget=s.budget;last=-.1;history=[];dts=[];reward=0.0
    spent=removed=added=emissions=renewals=dropped=0
    trace=[]
    for index,time in enumerate(oracle.times):
        budget,remove,add=exogenous(s,time,budget)
        removed+=remove;added+=add
        history.append(state_features(s,time,live,budget));dts.append(max(time-last,.1));last=time
        valid,due=legal_actions(s,time,live,budget)
        if index==len(oracle.times)-1:
            terminal=sum(s.values[i] for i in range(4) if (live>>i)&1)
            reward+=terminal
            trace.append({'time':time,'terminal_reward':terminal,'live':live,'budget':budget})
            break
        if due.any():
            if use_oracle:
                action=int(np.argmax(oracle.q_values(index,live,budget)))
            else:
                action=int(policy(np.asarray(history),np.asarray(dts),valid))
        else:
            action=0
        before=budget
        live,budget,instant,info=transition(s,time,live,budget,action)
        reward+=instant;spent+=info['cost'];renewals+=info['renewals'];emissions+=info['emissions'];dropped+=info['dropped']
        trace.append({'time':time,'due':due.tolist(),'action':ACTION_DIGITS[action].tolist(),
                      'budget_before':before,'budget_after':budget,'instant_reward':instant,**info})
    assert budget==s.budget+added-removed-spent
    assert budget>=0
    optimum=oracle.value(0,15,s.budget)
    if reward>optimum+1e-8:
        raise AssertionError('Policy utility exceeds its exact oracle')
    return {'utility':reward,'oracle_utility':optimum,'regret':max(optimum-reward,0),
            'normalized_utility':reward/optimum if optimum>1e-12 else 1.0,
            'spent':spent,'shock_removed':removed,'refill_added':added,'budget_final':budget,
            'renewals':renewals,'emissions':emissions,'dropped':dropped,'live_final':live,
            'retained_value':sum(s.values[i] for i in range(4) if (live>>i)&1),
            'budget_violations':0,'trace':trace}


def validate_and_prepare(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    # An exact pair matching the user's four state constraints.
    common=dict(values=(1.4,1.2,.7,.5),budget=4,shock_amount=2,refill_amount=1)
    a=Scenario(deadlines=(1.,1.,3.,3.),profile='A',**common)
    b=Scenario(deadlines=(2.,2.,2.,2.),profile='B',**common)
    ra,rb=rollout(a,use_oracle=True),rollout(b,use_oracle=True)
    assert np.mean(a.deadlines)==np.mean(b.deadlines)==2
    assert a.values==b.values and a.budget==b.budget
    negative=[]
    try:
        transition(a,1,15,0,40)
    except ValueError:
        negative.append('overdraft_rejected')
    try:
        transition(a,0,15,4,40)
    except ValueError:
        negative.append('non_due_mutation_rejected')
    assert len(negative)==2
    rng=np.random.default_rng(901)
    checked=0
    for _ in range(100):
        s=make_scenario(rng)
        o=rollout(s,use_oracle=True)
        greedy=rollout(s,lambda h,dt,valid:int(np.flatnonzero(valid)[-1]))
        assert o['utility']+1e-9>=greedy['utility']
        assert abs(o['regret'])<1e-8
        checked+=1
    report={'schema':'rrsnn.resource-validation.v1','synthetic':True,'negative_checks':negative,
      'oracle_vs_feasible_policy_scenarios':checked,'counterfactual':{'A':asdict(a),'B':asdict(b),
      'A_oracle':ra,'B_oracle':rb},'ledger_units':'dimensionless budget units; not physical joules',
      'limits':['Oracle has only the value and budget schedule exposed to all models at t=0.',
                'This is a finite synthetic planning task, not the general RR neural QVI.',
                'Shared feasibility masking guarantees budget safety; safety is not attributed to model quality.']}
    (destination/'resource_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    specs=[('train',1024,12001),('validation',256,22001),('test',384,32001),('future',384,42001)]
    manifest={'schema':'rrsnn.experiment-plan.v1','seeds':[101,211,307,401,503],
       'hidden_size':16,'input_size':22,'output_size':81,'max_steps':MAX_STEPS,
       'epochs':16,'batch_size':128,'learning_rate':0.003,'optimizer':'Adam',
       'checkpoint_selection':'minimum validation oracle-set negative log likelihood; test never selects',
       'scope':'synthetic closed-loop policy experiment using observation-grid neural proxies',
       'features':FEATURES,'splits':[],'full_QVI_optimality_claim':False}
    for split,n,seed in specs:
        scenarios,arrays=make_dataset(n,seed,split)
        np.savez_compressed(destination/(split+'.npz'),**arrays)
        raw=json.dumps([asdict(s) for s in scenarios],separators=(',',':'))
        (destination/(split+'_scenarios.json')).write_text(raw+'\n')
        manifest['splits'].append({'name':split,'n':n,'seed':seed,
          'scenario_sha256':hashlib.sha256(raw.encode()).hexdigest(),
          'maximum_length':int(max(arrays['lengths']))})
        print('prepared',split,n,'max_length',max(arrays['lengths']),flush=True)
    (destination/'experiment_plan.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'counterfactual_A_utility':ra['utility'],'counterfactual_B_utility':rb['utility'],
                      'validation_checks':checked+2},indent=2))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',default=str(Path(__file__).parent/'data'))
    args=p.parse_args();validate_and_prepare(args.output)
