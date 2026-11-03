"""Pre-shock action-distribution diagnostic at the first A-profile decision.

The shock is announced at t=0 and occurs at t=1.5. At t=1 both versions have
identical values, ledger, live mask and maturity profile. The only differing
observation was the initial announcement. 64 independent paths per value group
estimate distributions; simple single-path action disagreement is not treated
as evidence of anticipation.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import replace
import json
import numpy as np
import torch
from rrsnn_experiments.resource_env import state_features,legal_actions,ACTION_DIGITS
from .evaluate import load_policy,load_scenarios
from .audit.sampled_policy import SampledDensityRollout

ROOT=Path(__file__).resolve().parent

@torch.no_grad()
def run_candidate(name,seed,paths=64):
    model,blob=load_policy(ROOT/'results'/name/f'seed_{seed}'/'model.pt')
    torch.set_num_threads(1)
    originals=[s for s in load_scenarios('paired') if s.profile=='A' and s.shock_amount==0]
    stochastic=blob['sampled_training'];repeats=paths if stochastic else 1
    actions=np.zeros((len(originals),2,repeats),dtype=int)
    for condition,shock in enumerate([0,2]):
        scenarios=[replace(s,shock_amount=shock) for s in originals for _ in range(repeats)]
        # Fixed seed is reused across the counterfactual conditions. Differing
        # event counts can consume randomness differently; inference concerns
        # the action distributions, not pathwise equality of this coupling.
        for begin in range(0,len(scenarios),256):
            part=scenarios[begin:begin+256];n=len(part)
            runtime=(SampledDensityRollout(model.encoder,n,'ctmc',seed=1970000+seed+begin,record_spikes=False)
                     if stochastic else None)
            state=model.initial_state(n)
            for time_value,delta in [(0.,0.),(1.,1.)]:
                features=torch.tensor(np.stack([state_features(s,time_value,15,4) for s in part]))
                if runtime is not None:
                    out=runtime.step(features,delta,True);logits=model.head(out['latent'])
                else:
                    state,out=model.step(state,features,delta,True);logits=out['logits']
            masks=torch.tensor(np.stack([legal_actions(s,1.,15,4)[0] for s in part]))
            chosen=logits.masked_fill(~masks,-1e9).argmax(-1).numpy()
            flat=np.arange(begin,begin+n);actions[flat//repeats,condition,flat%repeats]=chosen
    digits=ACTION_DIGITS[actions]
    renewal=(digits==1).sum(-1).mean(-1)
    emission=(digits==2).sum(-1).mean(-1)
    due_drop=(digits[...,:2]==0).sum(-1).mean(-1)
    frequencies=np.stack([(actions==action).mean(-1) for action in range(81)],axis=-1)
    tv=.5*np.abs(frequencies[:,1]-frequencies[:,0]).sum(-1)
    return {'run_name':name,'seed':seed,'value_groups':len(originals),'paths_per_group_condition':repeats,
        'mean_renewals_shock0_shock2':renewal.mean(0).tolist(),
        'mean_emissions_shock0_shock2':emission.mean(0).tolist(),
        'mean_due_drops_shock0_shock2':due_drop.mean(0).tolist(),
        'renewal_treatment_effect':float((renewal[:,1]-renewal[:,0]).mean()),
        'emission_treatment_effect':float((emission[:,1]-emission[:,0]).mean()),
        'mean_empirical_action_distribution_tv':float(tv.mean()),
        'tv_warning':'Plug-in TV is upward biased with finite samples. It is descriptive and not a rejection test for zero effect.',
        'group_renewals':renewal.tolist(),'group_emissions':emission.tolist(),'group_due_drops':due_drop.tolist(),
        'raw_actions':actions.tolist(),'real_future_window':False}

def main():
    plan=json.loads((ROOT/'experiment_plan.json').read_text());results=[]
    for name in ['rr_density_sampled','ctrnn_matched_cpu','rr_density']:
        for seed in plan['seeds']:
            result=run_candidate(name,seed);results.append(result)
            print(json.dumps({k:v for k,v in result.items() if k in ['run_name','seed','renewal_treatment_effect','emission_treatment_effect']}),flush=True)
    destination=ROOT/'results/anticipation_probe.json'
    destination.write_text(json.dumps({'schema':'rrsnn.v2.anticipation.v1','announced_shock':True,
        'pre_shock_decision_time':1.,'shock_time':1.5,'results':results},indent=2)+'\n')

if __name__=='__main__': main()
