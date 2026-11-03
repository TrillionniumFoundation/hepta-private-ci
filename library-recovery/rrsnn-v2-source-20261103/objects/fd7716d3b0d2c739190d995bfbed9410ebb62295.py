"""Deterministic numerical/gradient/cause checks for the v2 density operator.

Run with /tmp/rrsnn-venv/bin/python; writes density_validation_results.json.
Independent path sampling and continuous-model audits live in audit/ and are
not replaced by these finite-chain implementation checks.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import time

for _name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:
    os.environ[_name]='1'

import numpy as np
from scipy.linalg import expm
from scipy.stats import norm
import torch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from rrsnn_v2.density_model import DensityNeuronOperator,DensitySequenceModel


def scalar(value):
    return torch.tensor([[value]],dtype=torch.float64)


def first_hit_brownian(drift,sigma,boundary,time):
    scale=sigma*np.sqrt(time)
    return float(norm.cdf((drift*time-boundary)/scale)
                 +np.exp(2*drift*boundary/(sigma*sigma))*norm.cdf((-drift*time-boundary)/scale))


def absorbing_hit(grid,lower,drift=.7,sigma=.4,boundary=1.,time=1.5):
    op=DensityNeuronOperator(grid_size=grid,lower_bound=lower,sigma=sigma)
    b=scalar(boundary);mu=scalar(drift)
    q,_=op.generator(mu,b)
    p=op.reset_distribution(b)[0,0,:grid].numpy()
    survivor=p@expm(q[0,0,:grid,:grid].numpy()*time)
    return float(1-survivor.sum())


def finite_chain_checks():
    op=DensityNeuronOperator()
    results=[]
    for drift,boundary,time in [(-.4,.8,.6),(.7,1.17,1.3),(2.,.7,4.)]:
        mu=scalar(drift);b=scalar(boundary);p=op.reset_distribution(b)
        q,r=op.generator(mu,b)
        s=op.state_size
        block=np.zeros((s+1,s+1));block[:s,:s]=q[0,0].numpy();block[:s,-1]=r[0,0].numpy()
        initial=np.r_[p[0,0].numpy(),0.]
        reference=initial@expm(block*time)
        prob,count=op.propagate(p,time,mu,b)
        up,uc=op.propagate(p,time,mu,b,method='uniformization')
        offdiag=q-torch.diag_embed(q.diagonal(dim1=-2,dim2=-1))
        error=max(float(np.max(np.abs(prob[0,0].numpy()-reference[:s]))),abs(float(count)-reference[-1]))
        assert error<2e-11
        assert float((q.sum(-1)).abs().max())<1e-13
        assert float(offdiag.min())>=0
        assert float((prob.sum(-1)-1).abs().max())<2e-12
        assert float(prob.min())>=-1e-14
        method_error=max(float((prob-up).abs().max()),float((count-uc).abs().max()))
        assert method_error<2e-11
        p1,c1=op.propagate(p,time*.37,mu,b)
        p2,c2=op.propagate(p1,time*.63,mu,b)
        semigroup=max(float((p2-prob).abs().max()),float((c1+c2-count).abs().max()))
        assert semigroup<2e-11
        results.append({'drift':drift,'boundary':boundary,'time':time,
            'matrix_exp_vs_scipy_max_abs':error,'uniformization_vs_matrix_exp_max_abs':method_error,
            'probability_mass_error':float((prob.sum(-1)-1).abs().max()),
            'minimum_probability':float(prob.min()),'semigroup_and_count_additivity_error':semigroup,
            'expected_firing_count':float(count)})
    assert results[-1]['expected_firing_count']>3
    p0,c0=op.propagate(p,0.,mu,b)
    assert torch.equal(p,p0) and torch.equal(c0,torch.zeros_like(c0))
    return results


def gradient_checks():
    op=DensityNeuronOperator()
    mu=scalar(.73).requires_grad_();boundary=scalar(1.173).requires_grad_()
    def loss(m,b):
        p,c=op.propagate(op.reset_distribution(b),.8,m,b)
        return c.sum()+.2*op.readout(p,b).sum()+.01*p.square().sum()
    passed=torch.autograd.gradcheck(loss,(mu,boundary),eps=1e-6,atol=2e-5,rtol=1e-4)
    value=loss(mu,boundary)
    grads=torch.autograd.grad(value,(mu,boundary))
    errors=[]
    for j in range(2):
        plus=[mu.detach().clone(),boundary.detach().clone()]
        minus=[v.clone() for v in plus]
        plus[j]+=1e-5;minus[j]-=1e-5
        fd=float((loss(*plus)-loss(*minus))/(2e-5))
        errors.append({'parameter':['drift','boundary'][j],'autograd':float(grads[j]),
                       'central_difference':fd,'absolute_error':abs(float(grads[j])-fd)})
    assert max(r['absolute_error'] for r in errors)<2e-7
    return {'torch_gradcheck':bool(passed),'central_differences':errors,
            'qualification':'local differentiability checked away from remap/reset grid knots and ReLU drift zero'}


def causal_and_remap_checks():
    torch.manual_seed(123)
    model=DensitySequenceModel().double()
    x=torch.rand(2,3,22,dtype=torch.float64)
    x[...,11:15]=1
    dt=torch.tensor([[0.,.6,.5]],dtype=torch.float64).repeat(2,1)
    regular=model(x,dt)
    inserted=torch.cat((x[:,:1],torch.full_like(x[:,:1],float('nan')),x[:,1:]),dim=1)
    inserted_dt=torch.tensor([[0.,.2,.4,.5]],dtype=torch.float64).repeat(2,1)
    mask=torch.tensor([[True,False,True,True]]).repeat(2,1)
    divided=model(inserted,inserted_dt,event_mask=mask)
    probability_error=float((regular['state'].probability-divided['state'].probability).abs().max())
    count_error=float((regular['spikes'].sum(1)-divided['spikes'].sum(1)).abs().max())
    assert probability_error<2e-12 and count_error<2e-12
    assert torch.equal(divided['controls_tape']['drift'][:,0],divided['controls_tape']['drift'][:,1])
    future=x.clone();future[:,-1]*=4
    altered=model(future,dt)
    prefix_error=float((altered['latent'][:,:-1]-regular['latent'][:,:-1]).abs().max())
    assert prefix_error==0
    initial=model.initial_state(2,dtype=torch.float64)
    state,_=model.step(initial,x[:,0],0)
    _,a=model.step(state,x[:,1],.6)
    _,b=model.step(state,x[:,1]*3,.6)
    past_count_error=float(((a['spikes']-a['immediate_counts'])-(b['spikes']-b['immediate_counts'])).abs().max())
    assert past_count_error<1e-14
    op=model.operator
    old=scalar(1.25);new=scalar(.83);kick=scalar(.12)
    p=torch.rand(1,1,op.state_size,dtype=torch.float64);p=p/p.sum(-1,keepdim=True)
    mapped,immediate=op.remap(p,old,new,kick)
    matrix,reward=op.remap_matrix(old,new,kick)
    map_error=float((mapped-(p.unsqueeze(-2)@matrix).squeeze(-2)).abs().max())
    reward_error=float((immediate-(p*reward).sum(-1)).abs().max())
    assert map_error<1e-14 and reward_error<1e-14
    assert float((matrix.sum(-1)-1).abs().max())<1e-14
    collapsed=op.collapse_active_mean(p,old)
    active_mean_error=float(((p[...,:op.grid_size]-collapsed[...,:op.grid_size])*op.nodes(old)).sum(-1).abs().max())
    assert active_mean_error<1e-14
    assert torch.equal(p[...,op.grid_size:],collapsed[...,op.grid_size:])
    return {'no_op_inserted_probability_error':probability_error,
            'no_op_inserted_total_count_error':count_error,'no_op_ignored_nan_features':True,
            'future_input_changed_prefix_error':prefix_error,
            'current_input_changed_past_interval_count_error':past_count_error,
            'remap_matrix_vs_direct_error':map_error,'remap_count_reward_error':reward_error,
            'moment_collapse_active_mean_preservation_error':active_mean_error,
            'no_op_scope':'event_mask=False; a real repeated observation may intentionally update context'}


def convergence_checks():
    target=first_hit_brownian(.7,.4,1.,1.5)
    spatial=[]
    for grid in [16,32,64,128]:
        actual=absorbing_hit(grid,-2.)
        spatial.append({'N':grid,'hit_probability':actual,'absolute_error_vs_unbounded_brownian':abs(actual-target)})
    assert spatial[-1]['absolute_error_vs_unbounded_brownian']<spatial[0]['absolute_error_vs_unbounded_brownian']/3
    lower=[]
    for floor in [-1.,-2.,-4.,-8.]:
        grid=round((.6-floor)/.05)
        lower.append({'lower_bound':floor,'N':grid,'spacing':(.6-floor)/grid,
                      'hit_probability':absorbing_hit(grid,floor,-.2,.7,.6,2.)})
    phases=[]
    for k in [2,4,8,16,32,64]:
        op=DensityNeuronOperator(grid_size=64,refractory_phases=k,refractory=.2)
        mu=scalar(1.2);boundary=scalar(.7)
        p,count=op.propagate(op.reset_distribution(boundary),4.,mu,boundary)
        phases.append({'K':k,'refractory_mean':.2,'refractory_variance':.04/k,
                       'expected_firing_count':float(count),'mass_error':float((p.sum(-1)-1).abs().max())})
    return {'spatial_first_passage':spatial,'continuous_first_passage_reference':target,
        'spatial_reference_scope':'unbounded Brownian first hit; reflecting floor -2 is distant for this positive-drift test, not removed exactly',
        'lower_domain_at_fixed_spacing':lower,
        'lower_domain_scope':'changing the reflecting floor while holding h=.05; residual spatial error remains',
        'erlang_phase_refinement':phases,
        'erlang_scope':'K approaches deterministic refractory in distribution; these rows do not claim a continuum exact count oracle'}


def network_and_cost_checks():
    torch.manual_seed(456)
    x=torch.rand(4,4,22);x[...,11:15]=1
    dt=torch.tensor([[0.,.4,.5,.7]]).repeat(4,1)
    rows=[]
    for ablation in [None,'no_rollover','collapse_maturity','shuffle_maturity','fixed_boundary',
                     'moment_collapse','frozen_resource','numerical_kernel']:
        model=DensitySequenceModel(ablations=[] if ablation is None else [ablation])
        out=model(x,dt)
        loss=out['latent'].square().mean()+.01*out['spikes'].mean()
        loss.backward()
        assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
        assert bool(torch.isfinite(out['latent']).all())
        state=out['state']
        state_scalars=sum(v.numel() for v in [state.probability,state.context,state.drift,state.boundary,state.initial_resource] if v is not None)//len(x)
        assert state_scalars==model.state_accounting()['active_state_scalars_per_sequence']
        rows.append({'ablation':ablation,'finite_gradients':True,'active_state_scalars':state_scalars,
                     'maximum_probability_mass_error':float((out['probabilities'].sum(-1)-1).abs().max().detach())})
    model=DensitySequenceModel()
    x=torch.rand(64,7,22);x[...,11:15]=1
    dt=torch.full((64,7),.5);dt[:,0]=0
    timings=[]
    for repetition in range(3):
        start=time.perf_counter();out=model(x,dt);forward=time.perf_counter()-start
        start=time.perf_counter();(out['latent'].square().mean()+.01*out['spikes'].mean()).backward();backward=time.perf_counter()-start
        model.zero_grad(set_to_none=True)
        timings.append({'repetition':repetition,'forward_seconds':forward,'backward_seconds':backward})
    return {'ablations':rows,'pilot_B64_T7_H8_N16_K2':timings,
            'metadata':model.metadata(),'fixed_tensor_buffer_bytes':sum(b.numel()*b.element_size() for b in model.buffers()),
            'pilot_scope':'single-thread CPU timing under possible concurrent workload; not a deployment latency benchmark'}


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    affinity=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,{affinity[-1]})
    begun=time.perf_counter()
    result={'schema':'rrsnn.v2.density-operator-validation.v1',
            'finite_chain':finite_chain_checks(),'gradients':gradient_checks(),
            'causality_and_remapping':causal_and_remap_checks(),
            'convergence':convergence_checks(),'network_and_compute':network_and_cost_checks(),
            'implementation_sha256':hashlib.sha256((ROOT/'density_model.py').read_bytes()).hexdigest(),
            'runtime':{'torch':str(torch.__version__),'threads':torch.get_num_threads(),'affinity':list(os.sched_getaffinity(0))},
            'all_assertions_passed':True,'elapsed_seconds':time.perf_counter()-begun}
    destination=ROOT/'density_validation_results.json'
    destination.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(destination),'all_assertions_passed':True,'elapsed_seconds':result['elapsed_seconds']}),flush=True)


if __name__=='__main__':
    main()
