"""Run independent and distribution-level checks of the R1 event runtime."""
from __future__ import annotations

import argparse
import json
import math
import platform
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.sparse import diags
from scipy.sparse.linalg import splu
from scipy.stats import kstest

try:
    from .event_runtime import (Connection,InputEvent,Neuron,conditional_survival_cdf,
        first_hit_cdf,killed_density,log_surviving_tail,sample_first_hit,
        sample_surviving_endpoint,simulate)
except ImportError:
    from event_runtime import (Connection,InputEvent,Neuron,conditional_survival_cdf,
        first_hit_cdf,killed_density,log_surviving_tail,sample_first_hit,
        sample_surviving_endpoint,simulate)


def forward_pde_switch(x0, sigma, t1, t2, mu1, mu2, kick, dx=0.005, xmax=8.0):
    """Independent forward Fokker-Planck solution with absorbing boundary.

    A true input jump shifts distance x -> x-kick and discards crossed mass.
    Initial and post-kick corners use Rannacher smoothing. The result is a
    numerical finite-domain/grid approximation, with convergence checked.
    """
    n=int(round(xmax/dx)); dx=xmax/n
    grid=np.linspace(0,xmax,n+1)
    density=np.zeros(n+1)
    p=x0/dx
    idx=int(math.floor(p)); frac=p-idx
    density[idx]=(1-frac)/dx
    density[idx+1]=frac/dx
    def advance(density,mu,duration):
        D=sigma*sigma/2
        m=n-1
        A=diags([np.full(m-1,D/dx**2+mu/(2*dx)),np.full(m,-2*D/dx**2),
                 np.full(m-1,D/dx**2-mu/(2*dx))],[-1,0,1],format='csc')
        I=diags([np.ones(m)],[0],format='csc')
        steps=max(10,int(math.ceil(duration/0.0005)))
        dt=duration/steps
        lu=splu(I-dt*A/2)
        v=density[1:-1].copy()
        for _ in range(2):
            v=lu.solve(v)
        R=I+dt*A/2
        for _ in range(steps-1):
            v=lu.solve(R@v)
        return np.concatenate(([0.0],v,[0.0]))
    density=advance(density,mu1,t1)
    density=np.interp(grid+kick,grid,density,left=0,right=0)
    density[0]=density[-1]=0
    density=advance(density,mu2,t2)
    return float(1-dx*np.sum(density[1:-1]))


def _close(actual,expected,tolerance=1e-10):
    if not np.allclose(actual,expected,rtol=0,atol=tolerance):
        raise AssertionError(f'{actual} != {expected} within {tolerance}')


def _probability_check(value,reference,n,extra=0.0):
    standard_error=math.sqrt(max(reference*(1-reference),1e-12)/n)
    z=(value-reference)/standard_error
    if abs(value-reference)>5*standard_error+extra:
        raise AssertionError(f'Probability mismatch {value} vs {reference}; z={z}')
    return {'observed':float(value),'reference':float(reference),'n':n,
            'theoretical_standard_error':standard_error,'z_score':z}


def validate(output: Path, samples=12000):
    output.mkdir(parents=True,exist_ok=True)
    began=time.perf_counter()
    tests=[]
    def passed(name,details):
        tests.append({'name':name,'status':'passed','details':details})

    # Deterministic scheduling checks have known independent event times.
    deterministic=simulate([Neuron(drift=1,sigma=0,refractory=.2)],4,seed=1)
    times=[s['time'] for s in deterministic['spikes']]
    _close(times,[1,2.2,3.4])
    passed('multiple_spikes_and_refractory',{'spike_times':times})

    switched=simulate([Neuron(drift=.5,sigma=0,refractory=.1)],1,
        inputs=[InputEvent(.4,0,drift=2)],seed=1)
    _close([s['time'] for s in switched['spikes']],[.8])
    passed('piecewise_drift_switch',{'spike_times':[s['time'] for s in switched['spikes']]})

    jumped=simulate([Neuron(drift=0,sigma=0,refractory=.5)],1,
        inputs=[InputEvent(.25,0,kick=1.1),InputEvent(.3,0,kick=100)],seed=1)
    _close([s['time'] for s in jumped['spikes']],[.25])
    assert jumped['stats']['dropped_refractory_inputs']==1
    passed('jump_crossing_and_refractory_input_policy',{'spike_times':[.25],
            'dropped_refractory_inputs':1})

    threshold=simulate([Neuron(drift=1,sigma=0,refractory=.2)],.5,
        inputs=[InputEvent(.4,0,threshold=.3)],seed=1)
    _close([s['time'] for s in threshold['spikes']],[.4])
    passed('threshold_switch_triggers_immediately',{'spike_times':[.4]})

    paired=simulate([Neuron(drift=1,sigma=0),Neuron(drift=0,sigma=0)],1.2,
        connections=[Connection(0,1,1.1,.1)],seed=1)
    _close([s['time'] for s in paired['spikes']],[1,1.1])
    assert [s['neuron'] for s in paired['spikes']]==[0,1]
    passed('delayed_synaptic_coupling',{'spikes':paired['spikes']})

    # Deterministic exact LIF, not Euler, is an independent model baseline.
    lif=simulate([Neuron(model='lif',drift=2,sigma=0,tau=.3,refractory=.1)],1,seed=1)
    first=.3*math.log(2)
    expected=[first+n*(first+.1) for n in range(3)]
    _close([s['time'] for s in lif['spikes']],expected)
    passed('exact_event_lif',{'spike_times':expected,'method':'closed-form exponential crossing'})

    # Full first-passage law including defective mass for outward drift.
    rng=np.random.default_rng(211)
    n=100_000
    hit_times=np.fromiter((sample_first_hit(rng,.7,.8,.9) for _ in range(n)),float,n)
    theoretical=math.exp(-2*.8*.7/.9**2)
    defective=_probability_check(np.mean(np.isfinite(hit_times)),theoretical,n)
    for deadline in (.25,1,3):
        _probability_check(np.mean(hit_times<=deadline),first_hit_cdf(.7,deadline,.8,.9),n)
    passed('outward_drift_never_hit_mass',defective)

    # The conditional endpoint distribution differs from a truncated normal.
    rng=np.random.default_rng(307)
    cn=16000
    params={'x':.15,'dt':.8,'mu':-.7,'sigma':.8}
    sampler_stats={'survival_proposals':0,'survival_inversions':0}
    endpoints=np.fromiter((sample_surviving_endpoint(rng,**params,stats=sampler_stats)
                           for _ in range(cn)),float,cn)
    ks=kstest(endpoints,lambda v:conditional_survival_cdf(v,**params))
    s=math.exp(log_surviving_tail(0,**params))
    mean_theory=quad(lambda z:z*killed_density(z,**params)/s,0,np.inf,epsabs=1e-10)[0]
    mean_se=float(np.std(endpoints,ddof=1)/math.sqrt(cn))
    assert ks.statistic < 1.95/math.sqrt(cn)
    assert abs(float(np.mean(endpoints))-mean_theory)<5*mean_se
    passed('killed_kernel_conditional_endpoints',{'n':cn,'ks_statistic':float(ks.statistic),
        'ks_pvalue':float(ks.pvalue),'sample_mean':float(np.mean(endpoints)),
        'quadrature_mean':mean_theory,'sample_mean_standard_error':mean_se,
        'survival_probability':s,**sampler_stats})

    # Forcing the rejection sampler into a rare-survival regime exercises the
    # exact-tail inversion fallback; it does not silently clip the state.
    rng=np.random.default_rng(401)
    rare_stats={'survival_proposals':0,'survival_inversions':0}
    rare_params={'x':.0005,'dt':1.,'mu':-.6,'sigma':.8}
    rare=np.array([sample_surviving_endpoint(rng,**rare_params,stats=rare_stats) for _ in range(600)])
    assert rare_stats['survival_inversions']>0
    rare_ks=kstest(rare,lambda v:conditional_survival_cdf(v,**rare_params))
    assert rare_ks.statistic<1.95/math.sqrt(len(rare))
    passed('rare_survival_inverse_fallback',{'n':len(rare),'ks_statistic':float(rare_ks.statistic),
                                           **rare_stats})

    # Random input affects an actually propagated survivor, not its mean.
    x0,sigma,t1,t2,mu1,mu2,kick=1.,.7,.4,.6,.25,-1.1,.2
    survival_composition=quad(lambda z:killed_density(z,x0,t1,mu1,sigma)*
        (1-first_hit_cdf(z-kick,t2,mu2,sigma)),kick,np.inf,epsabs=1e-11,epsrel=1e-10)[0]
    composed=1-survival_composition
    pde_coarse=forward_pde_switch(x0,sigma,t1,t2,mu1,mu2,kick,dx=.01)
    pde_fine=forward_pde_switch(x0,sigma,t1,t2,mu1,mu2,kick,dx=.005)
    assert abs(pde_fine-composed)<8e-5
    assert abs(pde_fine-composed)<abs(pde_coarse-composed)
    first_spiked=0
    survivors=[]
    input_events=[InputEvent(t1,0,kick=kick,drift=-mu2)]
    for seed in range(samples):
        sim=simulate([Neuron(drift=-mu1,sigma=sigma,refractory=2)],t1+t2,
                     inputs=input_events,seed=100000+seed,record_trace=False)
        first_spiked+=bool(sim['spikes'])
        if not sim['spikes']:
            survivors.append(1-sim['final_values'][0])
    observed=first_spiked/samples
    check=_probability_check(observed,composed,samples)
    passed('input_jump_and_drift_switch_vs_forward_pde',{
        **check,'kernel_composition_reference':composed,'forward_pde_coarse':pde_coarse,
        'forward_pde_fine':pde_fine,'pde_absolute_error':abs(pde_fine-composed),
        'pde_coarse_absolute_error':abs(pde_coarse-composed),
        'parameters':dict(x0=x0,sigma=sigma,t1=t1,t2=t2,mu1=mu1,mu2=mu2,kick=kick)})

    # Inserting observation/no-op events must not change the marginal law.
    noop_hit=0
    noop=[InputEvent(t,0,tag='observation') for t in (.2,.4,.6,.8)]
    nn=10000
    for seed in range(nn):
        sim=simulate([Neuron(drift=.7,sigma=.8,refractory=2)],1,inputs=noop,
                     seed=500000+seed,record_trace=False)
        noop_hit+=bool(sim['spikes'])
    passed('event_partition_invariance',_probability_check(noop_hit/nn,first_hit_cdf(1,1,-.7,.8),nn))

    # Real stochastic recurrent network with delayed excitation/inhibition.
    specs=[Neuron(drift=.5+.06*i,sigma=.25+.025*i,refractory=.08) for i in range(8)]
    edges=[]
    for i in range(8):
        edges.extend([Connection(i,(i+1)%8,.18,.03),Connection(i,(i+3)%8,-.08,.05)])
    network=simulate(specs,8,inputs=[InputEvent(2,i,drift=.9) for i in range(8)]
                     +[InputEvent(4,i,kick=.2) for i in (0,2,4,6)],
                     connections=edges,seed=503)
    assert len(network['spikes'])>8
    last=np.full(8,-np.inf)
    for spike in network['spikes']:
        i=spike['neuron']
        assert spike['time']-last[i]>=specs[i].refractory-1e-12
        last[i]=spike['time']
    assert all(a['time']<=b['time'] for a,b in zip(network['spikes'],network['spikes'][1:]))
    assert network['stats']['survival_updates']>0 and network['stats']['transmitted_inputs']>0
    (output/'coupled_network_trace.json').write_text(json.dumps(network,indent=2)+'\n')
    passed('stochastic_sparse_recurrent_network',{'neurons':8,'connections':len(edges),
        'spikes':len(network['spikes']),'horizon':8,**network['stats']})

    result={'stage':'R1','status':'reference_engine_validated','all_checks_passed':True,
            'checks':tests,'wall_seconds':time.perf_counter()-began,
            'environment':{'python':platform.python_version(),'numpy':np.__version__,
                           'scipy':scipy.__version__},
            'limitations':['Independent Brownian innovations; coupling is through delayed jumps.',
              'Coefficients and threshold are constant between explicitly scheduled events.',
              'No multiplicative noise, OU diffusion, continuously moving boundary, or within-segment resource dynamics.',
              'Refractory kicks are explicitly discarded; parameter changes are retained.',
              'All-neuron synchronization is O(neurons * events), not a production scale implementation.',
              'Exact kernel requires special-function and numerical-inverse tolerances; unresolved tails fail explicitly.',
              'This validates simulation correctness only; not trained SNN quality or Hepta integration.']}
    (output/'runtime_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'results')
    parser.add_argument('--samples',type=int,default=12000)
    args=parser.parse_args()
    validate(args.output,args.samples)
