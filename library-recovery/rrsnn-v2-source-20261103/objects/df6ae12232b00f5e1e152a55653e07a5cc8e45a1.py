"""Independent scalar event-loop check of analytic interval LIF comparators."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import torch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from rrsnn_v2.spiking_baselines import CausalSpikingBaseline


def main():
    torch.set_num_threads(1)
    rng=np.random.default_rng(31415)
    results=[]
    for variant in ['lif','alif','resource_lif']:
        model=CausalSpikingBaseline(variant,hidden_size=1).double();n=200
        elapsed=rng.uniform(0,12,n);current=rng.uniform(-1.3,1.3,n)
        refractory=rng.uniform(0,.18,n)*(rng.uniform(0,1,n)<.3)
        voltage=rng.uniform(-.4,.5,n);voltage[refractory>0]=0
        state=model.initial_state(n,dtype=torch.double)
        state['context'][:,0]=torch.from_numpy(np.arctanh(current/model.current_scale))
        state['voltage'][:,0]=torch.from_numpy(voltage)
        state['refractory_remaining'][:,0]=torch.from_numpy(refractory)
        state['spike_trace'][:,0]=.4
        threshold=np.full(n,model.threshold)
        if variant=='alif':
            state['adaptation_trace'][:,0]=.3;threshold+=.3*model.adaptation_strength
        if variant=='resource_lif':
            threshold+=rng.uniform(0,.5,n)
        if variant!='lif':
            state['held_threshold'][:,0]=torch.from_numpy(threshold)
        after,count=model._advance(state,torch.from_numpy(elapsed)[:,None])
        maximum={key:0. for key in ['voltage','refractory_remaining','spike_trace','count','adaptation_trace']}
        for row in range(n):
            t=min(elapsed[row],refractory[row]);v=voltage[row]
            r=max(refractory[row]-elapsed[row],0.);events=[]
            while t<elapsed[row]-1e-14:
                hit=math.inf
                if current[row]>threshold[row]:
                    hit=model.membrane_tau*math.log((current[row]-v)/(current[row]-threshold[row]))
                if hit>elapsed[row]-t:
                    v=current[row]+(v-current[row])*math.exp(-(elapsed[row]-t)/model.membrane_tau)
                    t=elapsed[row];break
                t+=hit;events.append(t);v=0.
                if t+model.refractory>=elapsed[row]:
                    r=t+model.refractory-elapsed[row];t=elapsed[row];break
                t+=model.refractory
            values={'voltage':v,'refractory_remaining':r,'count':len(events),
                    'spike_trace':.4*math.exp(-elapsed[row]/model.trace_tau)
                        +sum(math.exp(-(elapsed[row]-s)/model.trace_tau) for s in events)}
            if variant=='alif':
                values['adaptation_trace']=.3*math.exp(-elapsed[row]/model.adaptation_tau)
                values['adaptation_trace']+=sum(math.exp(-(elapsed[row]-s)/model.adaptation_tau) for s in events)
            for key,value in values.items():
                actual=float(count[row,0] if key=='count' else after[key][row,0])
                maximum[key]=max(maximum[key],abs(value-actual))
        assert max(maximum.values())<1e-11
        torch.manual_seed(15)
        model=CausalSpikingBaseline(variant).double()
        x=torch.rand(2,3,22,dtype=torch.double)
        dt=torch.tensor([[0.,.6,.5]],dtype=torch.double).repeat(2,1)
        original=model(x,dt)
        split_x=torch.cat((x[:,:1],torch.full_like(x[:,:1],float('nan')),x[:,1:]),1)
        split_dt=torch.tensor([[0.,.2,.4,.5]],dtype=torch.double).repeat(2,1)
        mask=torch.tensor([[True,False,True,True]]).repeat(2,1)
        divided=model(split_x,split_dt,event_mask=mask)
        noop=max(float((original['final_state'][key]-divided['final_state'][key]).abs().max()) for key in original['final_state'])
        assert noop<1e-12
        divided['latent'].square().sum().backward()
        finite=all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
        assert finite
        results.append({'variant':variant,'reference_cases':n,'max_scalar_event_loop_error':maximum,
                        'no_op_state_error':noop,'all_gradients_finite_with_nan_noop':finite,
                        'hard_counts_integer':bool(torch.equal(original['spikes'],original['spikes'].round())),
                        'metadata':model.metadata()})
    result={'schema':'rrsnn.v2.spiking-baseline-validation.v1','random_seed':31415,
            'source_sha256':hashlib.sha256((ROOT/'spiking_baselines.py').read_bytes()).hexdigest(),
            'results':results,'all_assertions_passed':True,
            'gradient_qualification':'Finiteness only: count/threshold gradients are explicitly biased surrogates; forward no-op equivalence does not assert surrogate-gradient semigroup equivalence.'}
    path=ROOT/'spiking_baselines_validation.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(path),'all_assertions_passed':True}))


if __name__=='__main__':
    main()
