"""Independent mathematical/event audit of v2's finite CTMC and diffusion gap.

The exactness claims are separated deliberately:
 1. Matrix exponential solves the supplied finite CTMC, tested against Gillespie.
 2. Its space/floor/Erlang approximations approach, but are not equal to, the
    unrestricted Brownian reference with deterministic refractory.
 3. Input remapping is its own discrete Markov observation kernel.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
import torch

from rrsnn_experiments.runtime.event_runtime import first_hit_cdf
from ..density_model import DensityNeuronOperator, DensitySequenceModel
from .gillespie_reference import sample_ctmc
from .exact_rollout import ExactIndependentRollout

OUT=Path(__file__).resolve().parent/"results"


def tensor(value):
    return torch.tensor(value,dtype=torch.float64)


def continuous_count_mean(drift,boundary,sigma,refractory,horizon,reset=0.):
    distance=boundary-reset
    return sum(first_hit_cdf(k*distance,horizon-(k-1)*refractory,-drift,sigma)
               for k in range(1,int(math.floor(horizon/refractory))+2))


def law_count(grid,phases,lower,drift=.9,boundary=.8,sigma=.45,refractory=.15,horizon=1.8):
    operator=DensityNeuronOperator(grid,phases,lower,sigma,refractory).double()
    d,b=tensor([[drift]]),tensor([[boundary]])
    p=operator.reset_distribution(b)
    with torch.no_grad():
        final,count=operator.propagate(p,horizon,d,b)
    return float(count.item()),float(final.sum().item())


def semigroup_and_gillespie():
    op=DensityNeuronOperator(24,4,-2.,.5,.15).double()
    d,b=tensor([[1.6]]),tensor([[.8]])
    p=op.reset_distribution(b)
    q,r=op.generator(d,b)
    whole,total=op.propagate(p,1.7,d,b)
    first,c1=op.propagate(p,.61,d,b)
    split,c2=op.propagate(first,1.09,d,b)
    numerical,ncount=op.propagate(p,1.7,d,b,method="uniformization")
    semigroup=float((whole-split).abs().max())
    count_comp=float((total-c1-c2).abs().max())
    assert semigroup<2e-12 and count_comp<2e-12
    assert float((whole-numerical).abs().max())<2e-12
    assert float((total-ncount).abs().max())<2e-12
    matrix=q[0,0].detach().numpy()
    off=matrix.copy();np.fill_diagonal(off,0)
    assert off.min()>=0 and abs(whole.sum().item()-1)<2e-12 and whole.min()>-1e-12
    sampled=sample_ctmc(matrix,p[0,0].numpy(),1.7,paths=32768,seed=81001,
                         counted_edges=[(op.grid_size-1,op.grid_size)])
    mean=float(total.item())
    z=(sampled["count_mean"]-mean)/sampled["count_standard_error"]
    tv=float(np.abs(sampled["empirical_probability"]-whole[0,0].detach().numpy()).sum()/2)
    assert abs(z)<4 and tv<.025 and mean>1 and sampled["repeat_fraction"]>.5
    return {"grid":24,"phases":4,"generator_row_sum_max":float(abs(matrix.sum(1)).max()),
        "minimum_offdiagonal_rate":float(off.min()),"mass_error":abs(whole.sum().item()-1),
        "semigroup_distribution_max_error":semigroup,"semigroup_count_error":count_comp,
        "uniformization_distribution_max_error":float((whole-numerical).abs().max()),
        "uniformization_count_error":float((total-ncount).abs().max()),
        "ctmc_expected_count":mean,"gillespie_count_mean":sampled["count_mean"],
        "gillespie_count_standard_error":sampled["count_standard_error"],
        "gillespie_count_z":z,"gillespie_state_total_variation":tv,
        "gillespie_repeat_spike_fraction":sampled["repeat_fraction"],"gillespie_paths":32768}


def gradients():
    op=DensityNeuronOperator(20,3,-2.,.45,.17).double()
    params=tensor([.73,.93]).requires_grad_()
    def objective(parameters):
        d,b=parameters[0].reshape(1,1),parameters[1].reshape(1,1)
        p=op.reset_distribution(b)
        final,count=op.propagate(p,1.1,d,b)
        return count.sum()+.3*op.readout(final,b).sum()
    value=objective(params)
    ad=torch.autograd.grad(value,params)[0].detach().numpy()
    finite=[]
    for eps in (1e-4,1e-5,1e-6):
        fd=[]
        for j in range(2):
            plus=params.detach().clone();minus=params.detach().clone()
            plus[j]+=eps;minus[j]-=eps
            fd.append(float((objective(plus)-objective(minus))/(2*eps)))
        finite.append({"epsilon":eps,"gradient":fd,"max_error":float(np.max(abs(ad-np.array(fd))))})
    assert np.isfinite(ad).all() and min(r["max_error"] for r in finite)<1e-7
    return {"parameters":{"drift":.73,"boundary":.93},"autodiff":ad.tolist(),
            "finite_differences":finite,
            "scope":"Derivative of finite CTMC expectation, away from reset/remap knots; not asserted equal to continuous diffusion derivative."}


def causal_and_jump_checks():
    torch.manual_seed(83001)
    model=DensitySequenceModel(hidden_size=3,grid_size=16,refractory_phases=3,
                              kick_scale=0.).double()
    initial=model.initial_state(1,dtype=torch.float64)
    x0=torch.zeros(1,22,dtype=torch.float64);x0[:,4]=.7;x0[:,7:11]=.5;x0[:,11:15]=1
    state,out0=model.step(initial,x0,0.)
    assert torch.max(out0["expected_counts"].abs())<1e-12
    # New information at the right endpoint cannot change prior-interval counts.
    xa=x0.clone();xb=x0.clone();xa[:,0]=2.;xb[:,0]=-2.
    end_a,out_a=model.step(state,xa,.6)
    end_b,out_b=model.step(state,xb,.6)
    ca=out_a["expected_counts"]-out_a["immediate_counts"]
    cb=out_b["expected_counts"]-out_b["immediate_counts"]
    prior_count_error=float((ca-cb).abs().max())
    # Subtracting separately rounded immediate counts is not bit-exact.
    assert prior_count_error<1e-13
    noop,_=model.step(state,None,.2,event_mask=False)
    end_split,out_split=model.step(noop,xa,.4)
    assert torch.max((end_split.probability-end_a.probability).abs())<1e-12
    assert torch.equal(noop.drift,state.drift) and torch.equal(noop.context,state.context)
    rejected=False
    try:
        model(x0[:,None,:],tensor([[.1]]))
    except ValueError:
        rejected=True
    assert rejected
    # Sharp jump atoms and held refractory mass. On a coarse remap, an atom
    # below the physical threshold can partly fire; this is a documented grid
    # interpolation discrepancy and must not be labelled exact jump semantics.
    jump_rows=[]
    for n in (10,20,40):
        op=DensityNeuronOperator(n,2,-1.,.4,.1).double()
        old,new=tensor([[1.]]),tensor([[.5]])
        nodes=op.nodes(old)[0,0]
        near=int(torch.argmin(abs(nodes-.4)))
        assert abs(float(nodes[near])-.4)<1e-12
        p=torch.zeros(1,1,n+2,dtype=torch.float64);p[0,0,near]=.7;p[0,0,n+1]=.3
        remap,fired=op.remap(p,old,new,tensor([[0.]]))
        assert abs(float(remap.sum())-1)<1e-12 and remap[0,0,n+1]==.3
        exact=ExactIndependentRollout([.4],threshold=1.,sigma=.4,refractory=.1)
        exact_events=exact.observe(threshold=.5)
        assert len(exact_events)==0
        jump_rows.append({"grid":n,"initial_active_mass":.7,"initial_refractory_mass":.3,
                          "ctmc_remap_immediate_count":float(fired.item()),
                          "continuous_sharp_jump_count":0,
                          "mass_error":abs(float(remap.sum())-1)})
    assert jump_rows[-1]["ctmc_remap_immediate_count"]==0
    op=DensityNeuronOperator(10,2,-1.,.4,.1).double()
    p=torch.zeros(1,1,12,dtype=torch.float64);p[0,0,9]=1.
    mapped,fire=op.remap(p,tensor([[1.]]),tensor([[.5]]),tensor([[0.]]))
    assert abs(fire.item()-1)<1e-12 and abs(mapped[0,0,10].item()-1)<1e-12
    return {"initial_dt_zero_counts":out0["expected_counts"].tolist(),
            "nonzero_initial_dt_rejected":rejected,
            "prior_interval_count_independent_of_new_right_endpoint_input":True,
            "prior_interval_count_max_difference":prior_count_error,
            "noop_preserves_held_controls":True,
            "noop_partition_probability_error":float((end_split.probability-end_a.probability).abs().max()),
            "sharp_above_boundary_atom_fires":True,
            "refractory_mass_untouched_by_remap":True,
            "below_boundary_atom_remap_discrepancy":jump_rows}


def convergence():
    # Space: positive drift keeps the floor far away; many refractory phases
    # isolate the spatial error without pretending to eliminate it entirely.
    ref=continuous_count_mean(.9,.8,.45,.15,1.8)
    space=[]
    for n in (16,32,64,128,256):
        count,mass=law_count(n,128,-2.)
        space.append({"grid":n,"phases":128,"count":count,"error_vs_continuous":count-ref,
                      "mass_error":abs(mass-1)})
    assert abs(space[-1]["error_vs_continuous"])<.5*abs(space[0]["error_vs_continuous"])
    # Phase: a larger refractory fraction makes Erlang-vs-deterministic error
    # visible. Residual fine-grid error is measured, not silently called zero.
    phase_ref=continuous_count_mean(2.5,.6,.4,.3,2.1)
    phase=[]
    for k in (1,2,8,32,128):
        count,mass=law_count(256,k,-2.,2.5,.6,.4,.3,2.1)
        phase.append({"grid":256,"phases":k,"count":count,
                      "error_vs_continuous":count-phase_ref,"mass_error":abs(mass-1)})
    assert abs(phase[-1]["error_vs_continuous"])<abs(phase[0]["error_vs_continuous"])
    # Floor: keep h=.05 fixed while extending the reflecting domain. Outward
    # drift exposes finite-floor artificial recrossings before the spatial limit.
    floor_ref=continuous_count_mean(-.3,1.,.7,.15,3.)
    floor=[]
    for lower,n in ((-.5,30),(-1.,40),(-2.,60),(-4.,100)):
        count,mass=law_count(n,64,lower,-.3,1.,.7,.15,3.)
        floor.append({"lower_bound":lower,"grid":n,"spacing":.05,"phases":64,
                      "count":count,"error_vs_continuous":count-floor_ref})
    # Direct continuous event Monte Carlo, independently of the CTMC generator.
    engine=ExactIndependentRollout(np.zeros(16384),drift=.9,sigma=.45,
                                    threshold=.8,refractory=.15,seed=84001)
    engine.advance_to(1.8)
    mc=float(engine.count.mean());se=float(engine.count.std(ddof=1)/np.sqrt(engine.n))
    assert abs(mc-ref)<4*se
    default_count,_=law_count(16,2,-2.)
    return {"space_reference_count":ref,"space_convergence":space,
        "phase_reference_count":phase_ref,"phase_convergence":phase,
        "floor_reference_count":floor_ref,"floor_expansion_at_fixed_spacing":floor,
        "continuous_event_paths":engine.n,"continuous_event_mean":mc,
        "continuous_event_standard_error":se,"continuous_event_z":(mc-ref)/se,
        "default16x2_count_same_case":default_count,
        "default16x2_error_vs_continuous":default_count-ref,
        "interpretation":"Separate approximation axes. Fine-grid remaining error includes finite Erlang phases; fixed-spacing floor sweep retains spatial error."}


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    begun=time.perf_counter();OUT.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).resolve().parents[1]/"density_model.py"
    start_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    report={"schema":"rrsnn.independent-density-audit.v1","source_sha256":start_hash,
            "finite_ctmc":semigroup_and_gillespie(),"gradients":gradients(),
            "causality_and_jumps":causal_and_jump_checks(),"convergence":convergence(),
            "scope":"Exact finite-CTMC propagation validated separately from continuous Brownian approximation.",
            "limits":["Two independent exact event laws differ: CTMC uses reflecting floor, discrete voltage and Erlang refractory; Brownian uses an unrestricted lower tail and deterministic refractory.",
                      "P1 observation remapping can cause fractional firing from a below-threshold point on a coarse grid; this is an explicit observation-kernel approximation.",
                      "Finite CTMC semigroup closure removes scalar-mean closure but does not prove exact closure of an unrestricted continuous recurrent network."]}
    report["elapsed_seconds"]=time.perf_counter()-begun
    report["source_unchanged_during_audit"]=start_hash==hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["source_unchanged_during_audit"]
    (OUT/"density_operator_validation.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"passed":True,"seconds":report["elapsed_seconds"],
                      "gillespie_count_z":report["finite_ctmc"]["gillespie_count_z"],
                      "default_continuous_count_error":report["convergence"]["default16x2_error_vs_continuous"]}),flush=True)


if __name__=="__main__":
    main()
