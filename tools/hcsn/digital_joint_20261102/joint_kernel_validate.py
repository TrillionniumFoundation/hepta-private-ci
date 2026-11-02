"""Deterministic full-state derivative and independent numerical qualification."""
import argparse
import csv
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback
import sys
import numpy as np
from scipy.linalg import expm
import torch
from .joint_kernel import (DifferentiableRenewalCell,generator_from_physical,physical_from_raw,
                          RAW_NAMES,THRESHOLDS,HORIZONS)
from ..digital_read_followup_20261101 import continuous_renewal as continuous
_legacy_path=str(Path(__file__).resolve().parents[1]/'digital_read_followup_20261101')
sys.path.insert(0,_legacy_path)
from ..digital_read_followup_20261101.continuous_renewal_validate import pde
sys.path.remove(_legacy_path)

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def raw_law(raw,symbol,reliability):
    p=physical_from_raw(raw);p['drift']=p['drift_bias']+p['gain']*symbol*(2*reliability-1)
    return p


def initial(n):
    p=torch.zeros(n+2,dtype=torch.float64)
    p[n//2-3]=.3;p[n//2+3]=.3;p[-2]=.2;p[-1]=.2
    return p


def expected_count(p,q,dt):
    n=q.shape[-1];rates=q[:,-2:].sum(-1)*torch.cat((q.new_ones(n-2),q.new_zeros(2)))
    a=torch.cat((torch.cat((q,rates[:,None]),-1),q.new_zeros(1,n+1)),0)
    return (torch.cat((p,p.new_zeros(1)))@torch.matrix_exp(a*dt))[-1]


def full_outputs(raw,n=31):
    p=initial(n)
    for dt,s,r in ((.25,1.,.85),(.7,-1.,.65),(.9,1.,.95)):
        p=p@torch.matrix_exp(generator_from_physical(raw_law(raw,s,r),n)*dt)
    q=generator_from_physical(raw_law(raw,-1.,.85),n)
    u=torch.cat((torch.linspace(-1,1,n+2,dtype=torch.float64)[1:-1],raw.new_tensor([-1.,1.])))
    indicator=(u[:,None]>u.new_tensor(THRESHOLDS)).to(raw.dtype)
    bank=torch.cat([p@torch.matrix_exp(q*h)@indicator for h in HORIZONS])
    return torch.cat((p,bank,expected_count(p,q,1.1)[None]))


def fd_jacobian(function,x,step):
    cols=[]
    for j in range(len(x)):
        plus=x.detach().clone();minus=x.detach().clone();plus[j]+=step;minus[j]-=step
        cols.append(((function(plus)-function(minus))/(2*step)).detach())
    return torch.stack(cols,-1)


def physical_output(v):
    keys=('boundary','diffusion','drift','reset_plus','reset_minus','recovery_rate','reset_sd')
    q=generator_from_physical(dict(zip(keys,v)),31)
    p=initial(31)@torch.matrix_exp(q*1.35)
    return torch.cat((p,expected_count(p,q,.45)[None]))


def summarize(p,law):
    n=len(p)-2;xs=np.linspace(-law.boundary,law.boundary,n+2)[1:-1]
    return np.array([p[-2],p[-1],p[:-2].sum(),p[:-2]@xs+law.boundary*(p[-1]-p[-2])])


def physical_dict(law):
    return {k:torch.tensor(getattr(law,k),dtype=torch.float64) for k in
            ('boundary','diffusion','drift','reset_plus','reset_minus','recovery_rate','reset_sd')}


def projected_cdf(mass,xs,y,b):
    edges=np.r_[-b,(xs[:-1]+xs[1:])/2,b]
    fractions=np.clip((y-edges[:-1])/(edges[1:]-edges[:-1]),0,1)
    return float(mass@fractions)


def run():
    checks=[];details={};start=time.perf_counter();cpu=time.process_time()
    def check(name,passed,**data):checks.append(dict(name=name,passed=bool(passed),**data))
    raws=[torch.tensor(v,dtype=torch.float64) for v in
          ((.2,-.3,.25,-.15,.3,-.4,.2,-.35),(-1.,1.,-.4,.5,-.6,.4,-.3,.7))]
    gradient_cases=[]
    for case,raw in enumerate(raws):
        raw.requires_grad_();jac=torch.autograd.functional.jacobian(full_outputs,raw)
        for step in (1e-4,1e-5):
            fd=fd_jacobian(full_outputs,raw,step);delta=(jac-fd).abs();allow=3e-6+3e-4*jac.abs()
            check('raw_full_state_Jacobian',bool((delta<=allow).all()),case=case,step=step,
                  max_absolute_error=float(delta.max()),column_norms=jac.norm(dim=0).tolist())
        check('all_raw_coordinates_exercised',bool((jac.norm(dim=0)>1e-7).all()),case=case)
        gradient_cases.append(dict(raw=raw.detach().tolist(),jacobian=jac.detach().tolist()))
    v=torch.tensor([1.,.575,.2,.21,-.17,1.2,.09],dtype=torch.float64,requires_grad=True)
    jac=torch.autograd.functional.jacobian(physical_output,v);fd=fd_jacobian(physical_output,v,1e-5)
    check('physical_full_state_Jacobian',bool(((jac-fd).abs()<=3e-6+3e-4*jac.abs()).all()),
          max_absolute_error=float((jac-fd).abs().max()),column_norms=jac.norm(dim=0).tolist())
    raw=raws[0].detach().requires_grad_()
    def whole(r):return initial(31)@torch.matrix_exp(generator_from_physical(raw_law(r,1.,.85))*(.37+.88))
    def split(r):
        q=generator_from_physical(raw_law(r,1.,.85))
        return initial(31)@torch.matrix_exp(q*.37)@torch.matrix_exp(q*.88)
    a,b=whole(raw),split(raw);ja=torch.autograd.functional.jacobian(whole,raw);jb=torch.autograd.functional.jacobian(split,raw)
    check('semigroup_complete_mass',float((a-b).abs().max())<1e-9,error=float((a-b).abs().max()))
    check('semigroup_complete_Jacobian',float((ja-jb).abs().max())<1e-8,error=float((ja-jb).abs().max()))
    q=generator_from_physical(raw_law(raw,1.,.85));p=initial(31)
    direct=expected_count(p,q,1.25);parts=expected_count(p,q,.37)+expected_count(p@torch.matrix_exp(q*.37),q,.88)
    gd=torch.autograd.grad(direct,raw,retain_graph=True)[0];gs=torch.autograd.grad(parts,raw)[0]
    check('count_split_value',float(abs(direct-parts))<1e-9,error=float(abs(direct-parts)))
    check('count_split_gradient',float((gd-gs).abs().max())<1e-8,error=float((gd-gs).abs().max()))
    c=DifferentiableRenewalCell(raw=raws[0].detach())
    t0=c.transition(0.,1.,.85);zero=(t0*torch.arange(33,dtype=torch.float64)[:,None]).sum()
    zgrad=torch.autograd.grad(zero,c.raw)[0]
    check('zero_time_identity_gradient',torch.equal(t0,torch.eye(33,dtype=torch.float64)) and torch.equal(zgrad,torch.zeros_like(zgrad)))
    fixed=DifferentiableRenewalCell(raw=raws[0].detach(),learn_boundary=False);before=float(fixed.physical()['boundary'])
    opt=torch.optim.AdamW(fixed.parameters(),lr=.05,weight_decay=.1)
    fixed.advance_distribution(initial(31),.75,1.,.85).square().sum().backward()
    check('fixed_boundary_zero_gradient',float(fixed.raw.grad[0])==0.)
    opt.step();check('fixed_boundary_weight_decay_safe',float(fixed.physical()['boundary'])==before)
    dt=torch.tensor([.25,.75],dtype=torch.float64);s=torch.tensor([1.,-1.]);r=torch.tensor([.85,.65])
    batched=c.transition(dt,s,r);individual=torch.stack([c.transition(float(dt[i]),float(s[i]),float(r[i])) for i in range(2)])
    check('broadcast_transition',torch.allclose(batched,individual,atol=1e-11,rtol=1e-11),error=float((batched-individual).abs().max()))
    features=c.features(s,r);bank=c.bank_features(s,r)
    check('reset_aware_bank_shapes',list(features.shape)==[2,33,12] and list(bank.shape)==[2,33,9])
    check('reset_aware_bank_probabilities',float(bank.min())>=-1e-12 and float(bank.max())<=1+1e-9)
    base=dict(boundary=1.,diffusion=.575,drift=.2,reset_plus=.2,reset_minus=-.15,recovery_rate=1.2,reset_sd=.09)
    scaled={k:(x*1.05 if k!='recovery_rate' else x) for k,x in base.items()}
    gauge=(generator_from_physical(base)-generator_from_physical(scaled)).abs().max()
    check('declared_scale_gauge',float(gauge)<1e-10,error=float(gauge))
    stochastic=[]
    for grid in (31,63,127):
        cell=DifferentiableRenewalCell(raw=raws[0].detach(),n_grid=grid)
        q=cell.generator(1.,.85);off=q-torch.diag_embed(torch.diagonal(q))
        check('generator_sign_mass',float(off.min())>=0 and float(q.sum(-1).abs().max())<1e-10,grid=grid)
        for duration in (0.,.01,.25,.75,2.):
            t=cell.transition(duration,1.,.85);err=float((t.sum(-1)-1).abs().max())
            check('stochastic_exponential',float(t.min())>=-1e-12 and err<1e-9,grid=grid,dt=duration,mass_error=err)
        scipy_error=float(np.max(abs(cell.transition(.75,1.,.85).detach().numpy()-expm(.75*q.detach().numpy()))))
        check('independent_scipy_expm',scipy_error<1e-9,grid=grid,error=scipy_error)
        stochastic.append(dict(grid=grid,scipy_error=scipy_error))
    killed=[]
    cases=[(continuous.Law(boundary=.8,diffusion=.8,drift=0.,reset_sd=.072),0.,2.),
           (continuous.Law(boundary=1.,diffusion=.575,drift=.3,reset_sd=.09),.25,.75),
           (continuous.Law(boundary=1.2,diffusion=.35,drift=-1.1,reset_sd=.108),.25,1.5)]
    errors={31:[],63:[],127:[]}
    for ci,(law,u0,duration) in enumerate(cases):
        truth_exit=continuous.exit_cdf(u0*law.boundary,duration,law)
        for grid in (31,63,127):
            q=generator_from_physical(physical_dict(law),grid).detach().numpy();q[-2:]=0.
            xs=np.linspace(-law.boundary,law.boundary,grid+2)[1:-1]
            initial_index=int(np.argmin(abs(xs-u0*law.boundary)));mass=expm(q*duration)[initial_index]
            values=[abs(mass[-2]-truth_exit[0]),abs(mass[-1]-truth_exit[1])]
            for rel in (-.5,0.,.5):
                approximate=projected_cdf(mass[:-2],xs,rel*law.boundary,law.boundary)
                truth=continuous.killed_cdf(u0*law.boundary,rel*law.boundary,duration,law)
                values.append(abs(approximate-truth))
            errors[grid].append(max(values));killed.append(dict(case=ci,grid=grid,max_absolute_error=max(values)))
    check('killed_default_accuracy',max(errors[31])<.01,maximum_error=max(errors[31]))
    check('killed_refined_accuracy',max(errors[127])<.00075,maximum_error=max(errors[127]))
    check('killed_refinement_improves',sum(errors[127])<sum(errors[31])/2,coarse_sum=sum(errors[31]),fine_sum=sum(errors[127]))
    law=continuous.Law(boundary=.8,diffusion=.8,drift=0.,recovery_rate=2.,reset_minus=-.2,reset_plus=.2,reset_sd=.096)
    reference=pde(law,2.,n=240,renewal=True,count=True)
    true=np.array([reference[k] for k in ('lower','upper','active','mean_voltage','event_count')])
    regenerative={}
    for grid in (31,63,127):
        q=generator_from_physical(physical_dict(law),grid);p=torch.zeros(grid+2,dtype=torch.float64);p[grid//2]=1
        final=(p@torch.matrix_exp(q*2)).detach().numpy();moments=np.r_[summarize(final,law),float(expected_count(p,q,2))]
        regenerative[grid]=moments
        check('regenerative_PDE',float(np.max(abs(moments-true)))<.005,grid=grid,error=float(np.max(abs(moments-true))))
    check('many_events_in_one_interval',regenerative[31][-1]>1.1,expected_events=float(regenerative[31][-1]))
    old=HERE.parent/'digital_read_followup_20261101/continuous_renewal_samples.csv'
    with old.open() as stream:rows=[x for x in csv.DictReader(stream) if x['condition']=='truncated_reset']
    mc=np.array([[float(x[k]) for k in ('lower_refractory','upper_refractory','active','voltage','event_count')] for x in rows])
    mean=mc.mean(0);se=mc.std(0,ddof=1)/np.sqrt(len(mc));tol=6*se+2*abs(regenerative[63]-regenerative[127])+.002
    check('continuous_trajectory_reference',bool((abs(regenerative[127]-mean)<tol).all()),samples=len(mc),mean=mean.tolist(),ctmc=regenerative[127].tolist(),tolerance=tol.tolist())
    details=dict(raw_gradient_cases=gradient_cases,physical_jacobian=jac.detach().tolist(),killed=killed,
      regenerative={str(k):v.tolist() for k,v in regenerative.items()},independent_PDE=true.tolist(),stochastic=stochastic,
      continuous_input=dict(path=str(old.relative_to(ROOT)),sha256=hashlib.sha256(old.read_bytes()).hexdigest()))
    return dict(schema='joint-kernel-validation-v1',passed=all(c['passed'] for c in checks),checks=checks,
      details=details,wall_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu)


if __name__=='__main__':
    torch.set_num_threads(1)
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',default='001');args=parser.parse_args()
    out=HERE/('joint_kernel_validation_attempt_'+args.attempt+'.json')
    sources={p.name:p.read_text() for p in (Path(__file__),HERE/'joint_kernel.py',HERE/'joint_kernel_protocol.json')}
    snap=HERE/('joint_kernel_validation_attempt_'+args.attempt+'_sources.json.gz')
    with snap.open('xb') as f:f.write(gzip.compress(json.dumps(sources,sort_keys=True).encode(),mtime=0))
    try:result=run()
    except Exception:
        result=dict(schema='joint-kernel-validation-v1',passed=False,error=traceback.format_exc())
    result['source_sha256']={k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()}
    result['runtime']=dict(torch=torch.__version__,numpy=np.__version__,dtype='float64',threads=torch.get_num_threads())
    with out.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('details','checks')},indent=2))
    if 'checks' in result:print(json.dumps([c for c in result['checks'] if not c['passed']],indent=2))
    raise SystemExit(0 if result['passed'] else 1)
