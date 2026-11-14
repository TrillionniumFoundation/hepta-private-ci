"""Streaming closed-loop evaluation with causal clocks and independent task DP.

The evaluator supplies observations and a common feasible-action mask only.
Oracle values are used after the actor has selected its action, for scoring.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import time
import numpy as np
import torch
from rrsnn_experiments.resource_env import (Scenario,Oracle,ACTION_DIGITS,
    state_features,legal_actions,exogenous,transition)
from .policy import Policy

ROOT=Path(__file__).resolve().parent

class OracleTable:
    def __init__(self,scenario,values):
        self.s=scenario;self.times=scenario.events();self.values=values
    def value(self,index,live,budget_before):
        return float(self.values[index,live,budget_before])
    def q_values(self,index,live,budget_after):
        time_value=self.times[index]
        q=np.full(81,-np.inf)
        if index==len(self.times)-1:
            q[0]=sum(self.s.values[i] for i in range(4) if (live>>i)&1)
            return q
        valid,_=legal_actions(self.s,time_value,live,budget_after)
        for action in np.flatnonzero(valid):
            live2,budget2,reward,_=transition(self.s,time_value,live,budget_after,int(action))
            q[action]=reward+self.value(index+1,live2,budget2)
        return q

def load_scenarios(name):
    return [Scenario(**row) for row in json.loads((ROOT/'data'/f'{name}_scenarios.json').read_text())]

def prepare_oracle_cache(name):
    scenarios=load_scenarios(name);tables=[];checked=0;begun=time.perf_counter()
    for row,s in enumerate(scenarios):
        maximum=s.budget+s.refill_amount
        values=np.zeros((len(s.events()),16,maximum+1),dtype=np.float64)
        # Backward table solves exactly the same public transition function.
        table=OracleTable(s,values)
        for index in range(len(s.events())-1,-1,-1):
            t=s.events()[index]
            for live in range(16):
                for budget_before in range(maximum+1):
                    budget,_,_=exogenous(s,t,budget_before)
                    # States that would exceed this scenario's global budget
                    # bound are unreachable; their placeholders are never read.
                    if budget>maximum: continue
                    values[index,live,budget_before]=np.max(table.q_values(index,live,budget))
        if row<8:
            original=Oracle(s)
            assert abs(original.value(0,15,s.budget)-table.value(0,15,s.budget))<1e-10
            rng=np.random.default_rng(911001+row)
            for _ in range(64):
                index=int(rng.integers(0,len(s.events())))
                live=int(rng.integers(0,16));budget=int(rng.integers(0,maximum+1))
                # Only compare reachable-budget states, allowing future refill.
                remaining_refill=s.refill_amount if s.events()[index]<=s.refill_time else 0
                if budget+remaining_refill>maximum: continue
                assert abs(original.value(index,live,budget)-table.value(index,live,budget))<1e-10
                checked+=1
        tables.append(values)
    destination=ROOT/'data'/f'{name}_oracle.npz'
    np.savez_compressed(destination,**{str(i):table for i,table in enumerate(tables)})
    info={'dataset':name,'episodes':len(scenarios),'checked_values_against_original':checked,
          'source_scenario_sha256':hashlib.sha256((ROOT/'data'/f'{name}_scenarios.json').read_bytes()).hexdigest(),
          'cache_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'elapsed_seconds':time.perf_counter()-begun}
    (ROOT/'data'/f'{name}_oracle_provenance.json').write_text(json.dumps(info,indent=2)+'\n')
    return info

def load_oracles(name,scenarios):
    provenance=json.loads((ROOT/'data'/f'{name}_oracle_provenance.json').read_text())
    if provenance['episodes']!=len(scenarios): raise ValueError('Oracle cache episode count mismatch')
    for field,path in [('source_scenario_sha256',ROOT/'data'/f'{name}_scenarios.json'),
                       ('cache_sha256',ROOT/'data'/f'{name}_oracle.npz')]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=provenance[field]:
            raise ValueError(f'Oracle cache integrity mismatch: {field}')
    with np.load(ROOT/'data'/f'{name}_oracle.npz') as z:
        if set(z.files)!=set(map(str,range(len(scenarios)))): raise ValueError('Unexpected oracle cache table set')
        return [OracleTable(s,z[str(i)].copy()) for i,s in enumerate(scenarios)]

def calibration(confidence,correct):
    confidence=np.asarray(confidence);correct=np.asarray(correct)
    if len(confidence)==0: return None
    total=0.
    for lo,hi in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
        m=(confidence>=lo)&(confidence<hi if hi<1 else confidence<=hi)
        if m.any(): total+=m.mean()*abs(confidence[m].mean()-correct[m].mean())
    return float(total)

@torch.no_grad()
def evaluate(model,scenarios,oracles=None,mode='density',seed=900001,keep_trace=False):
    if mode not in ('density','endpoint','ctmc','brownian'): raise ValueError(mode)
    if mode!='density' and not model.is_density: raise ValueError('Stochastic backend needs density encoder')
    model.eval();n=len(scenarios)
    if oracles is None: oracles=[Oracle(s) for s in scenarios]
    lives=np.full(n,15,dtype=np.int64);budgets=np.array([s.budget for s in scenarios],dtype=np.int64)
    removed=np.zeros(n,dtype=np.int64);added=removed.copy();spent=removed.copy()
    renewals=removed.copy();emissions=removed.copy();drops=removed.copy()
    rewards=np.zeros(n);counts=np.zeros(n);last=np.zeros(n)
    terminal_latents=np.zeros((n,model.head.in_features));traces=[[] for _ in scenarios]
    confidence=[];correct=[];nll=[];spike_times=[]
    state=model.initial_state(n)
    generator=torch.Generator().manual_seed(seed)
    sampled_rollout=None
    if mode in ('ctmc','brownian'):
        from .audit.sampled_policy import SampledDensityRollout
        sampled_rollout=SampledDensityRollout(model.encoder,n,backend=mode,seed=seed,record_spikes=keep_trace)
    begin=time.perf_counter()
    for index in range(max(len(o.times) for o in oracles)):
        x=np.zeros((n,22),dtype=np.float32);dt=np.zeros(n,dtype=np.float32);mask=np.zeros(n,dtype=bool)
        decision_rows=[];valids=[]
        for row,(s,o) in enumerate(zip(scenarios,oracles)):
            if index>=len(o.times): continue
            t=o.times[index];mask[row]=True;dt[row]=t-last[row];last[row]=t
            budgets[row],rm,ad=exogenous(s,t,int(budgets[row]));removed[row]+=rm;added[row]+=ad
            x[row]=state_features(s,t,int(lives[row]),int(budgets[row]))
            if index==len(o.times)-1:
                rewards[row]+=sum(s.values[i] for i in range(4) if (lives[row]>>i)&1)
                continue
            valid,due=legal_actions(s,t,int(lives[row]),int(budgets[row]))
            if due.any(): decision_rows.append(row);valids.append(valid)
        if sampled_rollout is not None:
            out=sampled_rollout.step(torch.from_numpy(x),torch.from_numpy(dt),torch.from_numpy(mask))
            out['logits']=model.head(out['latent']);spike_times.extend(out['spike_times'])
        else:
            state,out=model.step(state,torch.from_numpy(x),torch.from_numpy(dt),
                                  torch.from_numpy(mask),generator,sampled=(mode=='endpoint'))
        counts[mask]+=out['spikes'].sum(-1).numpy()[mask]
        for row in np.flatnonzero(mask):
            if index==len(oracles[row].times)-1: terminal_latents[row]=out['latent'][row].numpy()
        if not decision_rows: continue
        valid=torch.from_numpy(np.stack(valids))
        probabilities=torch.softmax(out['logits'][decision_rows].masked_fill(~valid,-1e9),dim=-1).numpy()
        actions=probabilities.argmax(axis=-1)
        for j,row in enumerate(decision_rows):
            s=scenarios[row];o=oracles[row];t=o.times[index];action=int(actions[j])
            # Labels enter only here, after action selection.
            q=o.q_values(index,int(lives[row]),int(budgets[row]));optimal=q>=q.max()-1e-9
            confidence.append(float(probabilities[j,action]));correct.append(bool(optimal[action]))
            nll.append(float(-np.log(max(float(probabilities[j,optimal].sum()),1e-12))))
            before=int(budgets[row]);live,budget,reward,info=transition(s,t,int(lives[row]),before,action)
            lives[row]=live;budgets[row]=budget;rewards[row]+=reward
            spent[row]+=info['cost'];renewals[row]+=info['renewals'];emissions[row]+=info['emissions'];drops[row]+=info['dropped']
            if keep_trace:
                traces[row].append({'time':t,'action':ACTION_DIGITS[action].tolist(),
                    'budget_before':before,'budget_after':budget,'reward':reward,**info})
    assert np.all(budgets==np.array([s.budget for s in scenarios])+added-removed-spent)
    assert np.all(budgets>=0)
    oracle_values=np.array([o.value(0,15,s.budget) for o,s in zip(oracles,scenarios)])
    if np.any(rewards>oracle_values+1e-8): raise AssertionError('Actor utility exceeds exact oracle')
    ratio=np.divide(rewards,oracle_values,out=np.ones_like(rewards),where=oracle_values>1e-12)
    retained=np.array([sum(s.values[i] for i in range(4) if (lives[row]>>i)&1) for row,s in enumerate(scenarios)])
    result={'mode':mode,'episodes':n,'normalized_utility_mean':float(ratio.mean()),
        'utility_mean':float(rewards.mean()),'oracle_mean':float(oracle_values.mean()),
        'regret_mean':float((oracle_values-rewards).mean()),'retained_value_mean':float(retained.mean()),
        'budget_spent_mean':float(spent.mean()),'renewal_count_mean':float(renewals.mean()),
        'emission_count_mean':float(emissions.mean()),'dropped_count_mean':float(drops.mean()),
        'internal_count_mean':float(counts.mean()),
        'internal_count_semantics':'real spikes' if mode in ('ctmc','brownian') else 'conditional expected counts' if model.is_density else 'model baseline events',
        'policy_optimal_set_accuracy':float(np.mean(correct)), 'policy_optimal_set_nll':float(np.mean(nll)),
        'policy_ece_10_bins':calibration(confidence,correct),'ledger_conservation':True,'budget_violations':0,
        'zero_oracle_episodes':int((oracle_values<=1e-12).sum()),'zero_oracle_convention':'normalized utility = 1 when both oracle and actor are necessarily zero',
        'elapsed_seconds_with_task_scoring':time.perf_counter()-begin,
        'episode_utility':rewards.tolist(),'episode_oracle':oracle_values.tolist(),'episode_normalized_utility':ratio.tolist(),
        'episode_retained_value':retained.tolist(),'episode_budget_spent':spent.tolist(),
        'episode_live_final':lives.tolist(),
        'episode_internal_count':counts.tolist(),'terminal_latents':terminal_latents.tolist()}
    if keep_trace: result.update({'traces':traces,'real_spike_times':spike_times})
    return result

def load_policy(checkpoint):
    blob=torch.load(checkpoint,map_location='cpu',weights_only=False)
    model=Policy(blob['variant']);model.load_state_dict(blob['state_dict']);model.eval()
    return model,blob

def evaluate_checkpoint(checkpoint,datasets=('test','shift'),modes=None):
    torch.set_num_threads(1)
    model,blob=load_policy(checkpoint)
    if modes is None: modes=['ctmc','density'] if blob.get('sampled_training') else ['density']
    results={}
    for name in datasets:
        scenarios=load_scenarios(name);oracles=load_oracles(name,scenarios)
        for mode in modes:
            results[name+'_'+mode]=evaluate(model,scenarios,oracles,mode,seed=900000+blob['seed'],keep_trace=(name=='paired'))
    destination=Path(checkpoint).parent/('evaluation_'+'_'.join(datasets)+'_'+'_'.join(modes)+'.json.gz')
    payload={'run_name':blob['run_name'],'variant':blob['variant'],'seed':blob['seed'],
        'checkpoint_sha256':hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
        'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'evaluation':results,'real_future_window':False}
    with gzip.open(destination,'wt',encoding='utf-8') as handle: json.dump(payload,handle)
    print(json.dumps({'evaluated':str(destination),'means':{k:v['normalized_utility_mean'] for k,v in results.items()}}),flush=True)
    return payload

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--checkpoint');parser.add_argument('--cache')
    parser.add_argument('--datasets',nargs='+',default=['test','shift']);parser.add_argument('--modes',nargs='+')
    args=parser.parse_args()
    if args.cache: print(json.dumps(prepare_oracle_cache(args.cache)),flush=True)
    else: evaluate_checkpoint(args.checkpoint,args.datasets,args.modes)
