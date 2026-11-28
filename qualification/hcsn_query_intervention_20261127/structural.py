"""Finite-query rank bound, byte budgets, independent Brownian-bridge verification."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.special import ndtr
from model import DT,SIGMA,MU,GRID,boundary,kernel,reset_vector

def matrices(u,prev,scale=.7):
    b=boundary(np.r_[prev,u],'literal')
    q=kernel(GRID[None,:]-np.diff(b)[:,None],MU-scale*.25*u)
    n=len(u);h=len(GRID)
    s=np.zeros((n,h+1,h+1));s[:,:h,:h]=q;s[:,-1,:h]=reset_vector()
    reg=s.copy();reg[:,:h,-1]=1-q.sum(2)
    return s,reg

def analytical(x,mu):
    sd=SIGMA*np.sqrt(DT)
    return ndtr((-x-mu*DT)/sd)+np.exp(-2*mu*x/SIGMA**2)*ndtr((-x+mu*DT)/sd)

def run(out):
    rng=np.random.default_rng(8559031);n=512;h=len(GRID)+1
    # Batched history construction using shared terminal boundary and random switch times.
    uu=rng.uniform(-.55,.55,(n,24));uu=np.where(np.arange(24)%3==0,uu,0.)
    for j in range(1,24):
        if j%3:uu[:,j]=uu[:,j-1]
    uu[:,-1]=0.
    b=boundary(uu.ravel(),'literal').reshape(uu.shape);start=np.r_[reset_vector(),0.]
    states=np.broadcast_to(start,(n,h)).copy();r=reset_vector();mass_error=0.
    for j in range(24):
        diff=(b[:,j-1] if j else np.zeros(n))-b[:,j];q=kernel(GRID[None,:]+diff[:,None],MU-.7*.25*uu[:,j])
        active=np.einsum('ni,nij->nj',states[:,:-1],q)
        hit=states[:,:-1].sum(1)-active.sum(1)
        states=np.column_stack([active+states[:,-1,None]*r,hit])
        mass_error=max(mass_error,float(np.max(abs(states.sum(1)-1))))
    schedules=[];vectors=[];replay_max=0.;up=[];costs=[]
    for k in range(32):
        horizon=(2,4,6,8)[k%4]
        a,c=rng.uniform(-1.,1.,2)
        if k%2:u=np.r_[np.full(horizon//2,a),np.full(horizon-horizon//2,c)]
        else:u=np.linspace(a,c,horizon)
        schedules.append(u.tolist());s,_=matrices(u,0)
        w=np.ones(h)
        for step in s[::-1]:w=step@w
        vectors.append(1-w)
        present=states.copy()
        for step in s:present=present@step
        forward=1-present.sum(1);basis=states@(1-w)
        replay_max=max(replay_max,float(np.max(abs(forward-basis))))
        costs.append(1+4*horizon)
    Y=states@np.stack(vectors).T
    sv=np.linalg.svd(Y-Y.mean(0),compute_uv=False);bounds={k:float(np.sqrt((sv[k:]**2).sum()/Y.size)) for k in (0,1,2,3,4,7,8,11,12)}
    x=np.array([.03,.15,.45]);dr=np.array([-.15,.03355,.20])
    for xx,mm in zip(x,dr):
        count=400000;end=xx+mm*DT+SIGMA*np.sqrt(DT)*rng.standard_normal(count)
        p_bridge=np.exp(-2*xx*np.maximum(end,0)/(SIGMA**2*DT));fraction=np.mean(rng.uniform(size=count)<p_bridge)
        exact=analytical(xx,mm);se=np.sqrt(exact*(1-exact)/count)
        up.append(dict(start=float(xx),drift=float(mm),paths=count,analytic=float(exact),mc=float(fraction),se=float(se),z=float((fraction-exact)/se)))
    walltest=kernel(np.array([[.03],[.03-.04]]),np.array([.0,.0])).sum((1,2))
    assert walltest[0]>0 and walltest[1]==0
    checkx=np.linspace(.00001,1.3,88);dm=np.linspace(-.23,.23,88)
    survival=kernel(checkx[:,None],dm).sum((1,2));kernel_error=np.max(abs((1-survival)-analytical(checkx,dm)))
    assert kernel_error<1e-12 and replay_max<1e-12 and mass_error<1e-10 and max(abs(v['z']) for v in up)<4
    quant_error=float(np.max(abs(Y.astype(np.float32).astype(float)-Y)))
    # Actual CPU byte representations, derivative checked independent of any network fit.
    report=dict(histories=n,schedules=schedules,full_state_scalars=h,conditional_probability_extent=[float(Y.min()),float(Y.max())],
                answer_fp32_max_absolute_roundoff=quant_error,expected_float32_query_response_bytes=4,
                shared_waveform_packet_bytes='1-byte query ID or horizon plus 4-byte answer',
                sent_waveform_overhead_lengths_bytes=sorted(set(costs)),one_static_message_bytes=4,
                raw_schedule_transmit_note='1 horizon byte plus 4 bytes per scalar current per step plus 4 answer bytes; two currents doubles the waveform bytes',
                centered_singular_values=sv.tolist(),best_fixed_k_affine_port_rmse=bounds,shared_boundary_historical_range=[-.55,.55],
                backward_vs_forward=replay_max,history_mass_error=mass_error,one_step_hit_formula_error=float(kernel_error),
                wall_shift_remaining=walltest.tolist(),bridge_mc=up)
    out.mkdir(parents=True,exist_ok=True);(out/'structural_results.json').write_text(json.dumps(report,indent=2)+'\n')
    np.savez_compressed(out/'structural_arrays.npz',histories=states,queries=np.stack(vectors),all_answers=Y,singular_values=sv)
    print('RMSE bounds',bounds,'FP32 max',quant_error,'bridge z',[q['z'] for q in up])
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--out',type=Path,required=True);run(a.parse_args().out)
