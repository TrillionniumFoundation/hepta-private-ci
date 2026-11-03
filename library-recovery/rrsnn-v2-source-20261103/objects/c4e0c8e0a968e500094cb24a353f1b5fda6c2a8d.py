"""Frozen-budget training and closed-loop evaluation of deadline policies.

The neural models here are observation-grid training proxies. The environment
executes actual discrete renewal/emission/drop actions with a conserved ledger.
Expected/probability training and hard-event proxy replay are reported separately.
Neither is represented as the separate exact continuous-time R1 engine.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import resource
import time
import numpy as np
import torch
from torch import nn

from .models.sequence_models import SurrogateSequenceModel
from .models.budget_ctrnn import BudgetMatchedCTRNN
from .resource_env import (Scenario,Oracle,MAX_STEPS,ACTION_DIGITS,state_features,
                          legal_actions,exogenous,transition)

VARIANTS={
 'lif':('lif',()),'alif':('alif',()),'resource_lif':('resource_lif',()),
 'fp_no_maturity':('fp_no_maturity',()),'fp_multi_fixed':('fp_multi_fixed',()),
 'rr_full':('rr_full',()),'ctrnn':('ctrnn',()),
 'rr_no_rollover':('rr_full',('no_rollover',)),
 'rr_collapse_maturity':('rr_full',('collapse_maturity',)),
 'rr_shuffle_maturity':('rr_full',('shuffle_maturity',)),
 'rr_frozen_resource':('rr_full',('frozen_resource',)),
 'ctrnn_budget':('ctrnn_budget',()),
}
ROOT=Path(__file__).resolve().parent

class Policy(nn.Module):
    def __init__(self,variant,hidden=16,mode='expected'):
        super().__init__()
        family,ablations=VARIANTS[variant]
        self.budget_matched=family=='ctrnn_budget'
        if self.budget_matched:
            self.encoder=BudgetMatchedCTRNN()
            self.head=nn.Identity()
        else:
            self.encoder=SurrogateSequenceModel(family,22,hidden,ablations=ablations,mode=mode)
            self.head=nn.Linear(hidden,81)

    def forward(self,x,dt,generator=None):
        out=self.encoder(x,dt,generator=generator)
        if not self.budget_matched:
            out['logits']=self.head(out['latent'])
        return out

    def set_mode(self,mode):
        self.encoder.mode=mode

    def metadata(self):
        out=self.encoder.metadata()
        out['total_trainable_parameters']=sum(p.numel() for p in self.parameters())
        return out


def load_arrays(name):
    z=np.load(ROOT/'data'/f'{name}.npz')
    return {k:torch.from_numpy(z[k]) for k in ['x','dt','valid','optimal','decision','lengths']}


def set_loss(logits,valid,optimal,decision):
    denominator=torch.logsumexp(logits.masked_fill(~valid,-1e9),dim=-1)
    numerator=torch.logsumexp(logits.masked_fill(~optimal,-1e9),dim=-1)
    return (denominator-numerator)[decision].mean()


@torch.no_grad()
def validation_loss(model,arrays):
    model.eval()
    length=int(arrays['lengths'].max())
    out=model(arrays['x'][:,:length],arrays['dt'][:,:length])
    return float(set_loss(out['logits'],arrays['valid'][:,:length],arrays['optimal'][:,:length],arrays['decision'][:,:length]))


def load_scenarios(name):
    raw=json.loads((ROOT/'data'/f'{name}_scenarios.json').read_text())
    return [Scenario(**s) for s in raw]


def ece_score(confidence,correct):
    conf=np.asarray(confidence);corr=np.asarray(correct)
    if not len(conf):
        return None
    total=0.
    for lo,hi in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
        mask=(conf>=lo)&(conf<hi if hi<1 else conf<=hi)
        if mask.any():
            total+=mask.mean()*abs(conf[mask].mean()-corr[mask].mean())
    return float(total)


@torch.no_grad()
def evaluate_closed_loop(model,scenarios,seed=9001,mode='expected',keep_trace=False):
    model.eval();model.set_mode(mode)
    n=len(scenarios)
    oracles=[Oracle(s) for s in scenarios]
    lives=np.full(n,15,dtype=np.int64)
    budgets=np.array([s.budget for s in scenarios],dtype=np.int64)
    removed=np.zeros(n,dtype=int);added=removed.copy();spent=removed.copy()
    renewals=removed.copy();emissions=removed.copy();drops=removed.copy()
    rewards=np.zeros(n);internal_events=np.zeros(n)
    histories=np.zeros((n,MAX_STEPS,22),dtype=np.float32)
    dts=np.full((n,MAX_STEPS),.1,dtype=np.float32)
    confidence=[];correct=[];nll=[]
    traces=[[] for _ in range(n)] if keep_trace else None
    terminal_latents=None
    begun=time.perf_counter()
    for index in range(max(len(o.times) for o in oracles)):
        decision=[];masks=[];qvals=[]
        alive_rows=[]
        for row,(s,o) in enumerate(zip(scenarios,oracles)):
            if index>=len(o.times):
                continue
            t=o.times[index]
            budgets[row],rm,ad=exogenous(s,t,int(budgets[row]));removed[row]+=rm;added[row]+=ad
            histories[row,index]=state_features(s,t,int(lives[row]),int(budgets[row]))
            dts[row,index]=max(t-(o.times[index-1] if index else -.1),.1)
            alive_rows.append(row)
            if index==len(o.times)-1:
                rewards[row]+=sum(s.values[i] for i in range(4) if (lives[row]>>i)&1)
                continue
            mask,due=legal_actions(s,t,int(lives[row]),int(budgets[row]))
            if due.any():
                decision.append(row);masks.append(mask)
                qvals.append(o.q_values(index,int(lives[row]),int(budgets[row])))
        gen=torch.Generator().manual_seed(seed)
        out=model(torch.from_numpy(histories[:,:index+1]),torch.from_numpy(dts[:,:index+1]),generator=gen)
        events=out['spikes'][:,-1].sum(dim=-1).numpy()
        internal_events[alive_rows]+=events[alive_rows]
        current_latents=out['latent'][:,-1].numpy()
        if terminal_latents is None:
            terminal_latents=np.zeros_like(current_latents)
        for row in alive_rows:
            if index==len(oracles[row].times)-1:
                terminal_latents[row]=current_latents[row]
        if not decision:
            continue
        logits=out['logits'][decision,-1]
        valid=torch.from_numpy(np.stack(masks))
        probabilities=torch.softmax(logits.masked_fill(~valid,-1e9),dim=-1).numpy()
        actions=probabilities.argmax(axis=-1)
        for j,row in enumerate(decision):
            s=scenarios[row];t=oracles[row].times[index]
            optimal=qvals[j]>=np.max(qvals[j])-1e-9
            action=int(actions[j])
            confidence.append(float(probabilities[j,action]));correct.append(bool(optimal[action]))
            nll.append(-math_log(float(probabilities[j,optimal].sum())))
            before=int(budgets[row])
            live,budget,reward,info=transition(s,t,int(lives[row]),before,action)
            lives[row]=live;budgets[row]=budget;rewards[row]+=reward
            spent[row]+=info['cost'];renewals[row]+=info['renewals'];emissions[row]+=info['emissions'];drops[row]+=info['dropped']
            if keep_trace:
                traces[row].append({'time':t,'action':ACTION_DIGITS[action].tolist(),
                    'budget_before':before,'budget_after':budget,'reward':reward,**info})
    assert np.all(budgets==np.array([s.budget for s in scenarios])+added-removed-spent)
    assert budgets.min()>=0
    oracle_values=np.array([o.value(0,15,s.budget) for o,s in zip(oracles,scenarios)])
    if np.any(rewards>oracle_values+1e-8):
        raise AssertionError('Policy exceeds its exact task oracle: simulator inconsistency')
    ratio=np.divide(rewards,oracle_values,out=np.ones_like(rewards),where=oracle_values>1e-12)
    retained=np.array([sum(s.values[i] for i in range(4) if (lives[j]>>i)&1) for j,s in enumerate(scenarios)])
    result={
       'mode':mode,'episodes':n,'utility_mean':float(rewards.mean()),
       'oracle_mean':float(oracle_values.mean()),'normalized_utility_mean':float(ratio.mean()),
       'zero_oracle_episodes':int(np.sum(oracle_values<=1e-12)),
       'normalized_utility_zero_oracle_convention':'1 for the necessarily zero-achieved-utility episodes',
       'regret_mean':float((oracle_values-rewards).mean()),
       'retained_value_mean':float(retained.mean()),'budget_spent_mean':float(spent.mean()),
       'renewal_count_mean':float(renewals.mean()),'emission_count_mean':float(emissions.mean()),
       'dropped_count_mean':float(drops.mean()),'internal_events_mean':float(internal_events.mean()),
       'policy_optimal_set_accuracy':float(np.mean(correct)),
       'policy_optimal_set_nll':float(np.mean(nll)),'policy_ece_10_bins':ece_score(confidence,correct),
       'budget_violations':0,'ledger_conservation':True,
       'elapsed_seconds_with_oracle_and_prefix_replay':time.perf_counter()-begun,
       'episode_utility':rewards.tolist(),'episode_oracle':oracle_values.tolist(),
       'episode_normalized_utility':ratio.tolist(),'episode_internal_events':internal_events.tolist(),
       'terminal_latents':terminal_latents.tolist(),
    }
    if keep_trace:
        result['traces']=traces
    return result


def math_log(v):
    return float(np.log(max(v,1e-12)))


def train_one(variant,seed,epochs=None):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(seed);np.random.seed(seed)
    plan=json.loads((ROOT/'data/experiment_plan.json').read_text())
    epochs=plan['epochs'] if epochs is None else epochs
    train=load_arrays('train');val=load_arrays('validation')
    model=Policy(variant)
    optimizer=torch.optim.Adam(model.parameters(),lr=plan['learning_rate'])
    initial_loss=validation_loss(model,val)
    best=initial_loss;best_state=copy.deepcopy(model.state_dict());best_epoch=-1
    history=[];grad_norms=[]
    begin=time.perf_counter()
    generator=torch.Generator().manual_seed(seed+100_000)
    n=len(train['x']);bs=plan['batch_size']
    for epoch in range(epochs):
        model.train();order=torch.randperm(n,generator=generator)
        losses=[]
        for start in range(0,n,bs):
            ids=order[start:start+bs]
            length=int(train['lengths'][ids].max())
            optimizer.zero_grad(set_to_none=True)
            out=model(train['x'][ids,:length],train['dt'][ids,:length])
            loss=set_loss(out['logits'],train['valid'][ids,:length],train['optimal'][ids,:length],train['decision'][ids,:length])
            if not torch.isfinite(loss):
                raise FloatingPointError(f'Nonfinite loss {variant} {seed} epoch={epoch}')
            loss.backward()
            for name,p in model.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():
                    raise FloatingPointError(f'Nonfinite gradient in {name}')
            norm=nn.utils.clip_grad_norm_(model.parameters(),1.0)
            grad_norms.append(float(norm));optimizer.step();losses.append(float(loss.detach()))
        vl=validation_loss(model,val)
        history.append({'epoch':epoch+1,'train_loss':float(np.mean(losses)),'validation_loss':vl})
        if vl<best:
            best=vl;best_epoch=epoch+1;best_state=copy.deepcopy(model.state_dict())
    train_seconds=time.perf_counter()-begin
    model.load_state_dict(best_state)
    destination=ROOT/'results'/variant/f'seed_{seed}'
    destination.mkdir(parents=True,exist_ok=True)
    checkpoint=destination/'model.pt'
    torch.save({'state_dict':best_state,'variant':variant,'seed':seed,'plan':plan,
                'metadata':model.metadata()},checkpoint)
    results={'variant':variant,'seed':seed,'metadata':model.metadata(),
             'training_mode':'expected','training_updates':epochs*((n+bs-1)//bs),
             'train_seconds':train_seconds,'initial_validation_loss':initial_loss,
             'best_validation_loss':best,'best_epoch':best_epoch,'history':history,
             'gradient_norm_max_before_clip':max(grad_norms),
             'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
             'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'model_source_sha256':hashlib.sha256((ROOT/'models/sequence_models.py').read_bytes()).hexdigest(),
             'evidence_level':'synthetic planning with observation-grid neural proxies',
             'evaluation':{}}
    for name,dataset_name in [('test','confirm_test'),('future','confirm_future')]:
        scenarios=load_scenarios(dataset_name)
        for mode in ['expected','hard']:
            results['evaluation'][name+'_'+mode]=evaluate_closed_loop(model,scenarios,seed+900_000,mode)
    # Exact paired state: identical values/budget/quantity/mean, different profile.
    common=dict(values=(1.4,1.2,.7,.5),budget=4,shock_amount=2,refill_amount=1)
    pair=[Scenario(deadlines=(1.,1.,3.,3.),profile='A',**common),
          Scenario(deadlines=(2.,2.,2.,2.),profile='B',**common)]
    results['counterfactual_pair']=evaluate_closed_loop(model,pair,seed+910_000,'expected',keep_trace=True)
    results['process_peak_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    (destination/'result.json').write_text(json.dumps(results,indent=2)+'\n')
    summary={'variant':variant,'seed':seed,'train_s':round(train_seconds,3),'val_nll':round(best,4),
       'test_utility':round(results['evaluation']['test_expected']['normalized_utility_mean'],4),
       'future_utility':round(results['evaluation']['future_expected']['normalized_utility_mean'],4),
       'hard_future_utility':round(results['evaluation']['future_hard']['normalized_utility_mean'],4)}
    print(json.dumps(summary),flush=True)
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--variant',choices=VARIANTS,required=True)
    p.add_argument('--seed',type=int,required=True);p.add_argument('--epochs',type=int)
    args=p.parse_args();train_one(args.variant,args.seed,args.epochs)
