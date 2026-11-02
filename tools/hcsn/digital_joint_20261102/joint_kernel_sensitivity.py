"""Registered local continuum-sensitivity comparison, independent PDE FD."""
import argparse
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
import numpy as np
import scipy
from scipy.sparse.linalg import expm_multiply
import torch
from .joint_kernel import generator_from_physical
from ..digital_read_followup_20261101 import continuous_renewal as continuous

HERE=Path(__file__).resolve().parent
LEGACY=HERE.parent/'digital_read_followup_20261101'
sys.path.insert(0,str(LEGACY))
from ..digital_read_followup_20261101.continuous_renewal_validate import generator as independent_generator
sys.path.remove(str(LEGACY))
NAMES=('boundary','diffusion','drift','reset_plus','reset_minus','recovery_rate','reset_sd')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cdf_weights(grid,like,projected):
    u=torch.linspace(-1,1,grid+2,dtype=like.dtype,device=like.device)[1:-1]
    edges=torch.cat((u.new_tensor([-1.]),(u[:-1]+u[1:])/2,u.new_tensor([1.])))
    cols=[]
    for k in (-.5,0.,.5):
        w=torch.clamp((k-edges[:-1])/(edges[1:]-edges[:-1]),0,1) if projected else (u<=k).to(like.dtype)
        cols.append(torch.cat((w,w.new_tensor([1.,0.]))))
    return torch.stack(cols,-1)


def torch_outputs(v,grid,duration):
    q=generator_from_physical(dict(zip(NAMES,v)),grid)
    p=q.new_zeros(grid+2);p[grid//2]=1
    final=p@torch.matrix_exp(q*duration)
    rates=q[:,-2:].sum(-1)*torch.cat((q.new_ones(grid),q.new_zeros(2)))
    augmented=torch.cat((torch.cat((q,rates[:,None]),-1),q.new_zeros(1,grid+3)),0)
    count=(torch.cat((p,p.new_zeros(1)))@torch.matrix_exp(augmented*duration))[-1]
    return torch.cat((final@cdf_weights(grid,q,True),final[-2:],count[None],final@cdf_weights(grid,q,False)))


def pde_outputs(v,intervals,duration):
    wall,cpu=time.perf_counter(),time.process_time()
    law=continuous.Law(**dict(zip(NAMES,map(float,v))));law.validate()
    a,xs=independent_generator(law,intervals,renewal=True,count=True)
    initial=np.zeros(a.shape[0]);initial[(intervals-1)//2]=1
    terminal=expm_multiply(a*duration,initial,traceA=float(a.diagonal().sum()*duration))
    grid=intervals-1
    weights=cdf_weights(grid,torch.empty((),dtype=torch.float64),True).numpy()
    cdf=terminal[:-1]@weights
    observable=np.r_[cdf,terminal[-3:-1],terminal[-1],cdf]
    return dict(physical=list(map(float,v)),intervals=intervals,observable=observable.tolist(),
      full_terminal_mass_and_count=terminal.tolist(),mass_error=float(abs(terminal[:-1].sum()-1)),
      wall_seconds=time.perf_counter()-wall,process_cpu_seconds=time.process_time()-cpu)


def hashes():
    paths=[Path(__file__),HERE/'joint_kernel_sensitivity_protocol.json',HERE/'joint_kernel.py',
           LEGACY/'continuous_renewal.py',LEGACY/'continuous_renewal_validate.py']
    return {str(p):digest(p) for p in paths}


def run(protocol):
    start,cpu=time.perf_counter(),time.process_time();checks=[];calls=[]
    v=torch.tensor(protocol['physical_point'],dtype=torch.float64,requires_grad=True)
    dt=protocol['duration'];gates=protocol['gates'];ad={};values={}
    for grid in protocol['autodiff_grids']:
        function=lambda x:torch_outputs(x,grid,dt)
        ad[grid]=torch.autograd.functional.jacobian(function,v).detach().numpy()
        values[grid]=function(v).detach().numpy()
        print(json.dumps(dict(phase='autodiff',grid=grid)),flush=True)
    references={};reference_values={};h=protocol['reference_fd_step']
    for intervals in protocol['reference_intervals']:
        columns=[]
        center=pde_outputs(v.detach().numpy(),intervals,dt);calls.append(center)
        reference_values[intervals]=center['observable']
        for coordinate in range(7):
            plus=v.detach().numpy().copy();minus=plus.copy();plus[coordinate]+=h;minus[coordinate]-=h
            a=pde_outputs(plus,intervals,dt);b=pde_outputs(minus,intervals,dt);calls.extend((a,b))
            columns.append((np.array(a['observable'])-np.array(b['observable']))/(2*h))
            print(json.dumps(dict(phase='independent_centered_FD',intervals=intervals,coordinate=NAMES[coordinate])),flush=True)
        references[intervals]=np.stack(columns,-1)
    def check(name,passed,**data):checks.append(dict(name=name,passed=bool(passed),**data))
    ref=references[480];mesh=float(np.max(abs(references[240]-ref)))
    check('reference_mesh_sensitivity',mesh<gates['reference_240_480_jacobian_max_difference'],max_error=mesh)
    errors={}
    for grid in protocol['autodiff_grids']:
        delta=abs(ad[grid]-ref)
        errors[grid]=dict(projected_ref_count=float(delta[:6].max()),strict_cdf=float(delta[6:].max()),
          by_physical_coordinate_projected=delta[:6].max(0).tolist(),by_physical_coordinate_strict=delta[6:].max(0).tolist())
    for grid in (31,127):
        for key,component in [('projected_ref_count','projected_ref_count'),('strict_cdf','strict_cdf')]:
            gate=gates[f'grid{grid}_{key}_max_jacobian_error']
            check('continuum_sensitivity_'+key,errors[grid][component]<gate,grid=grid,error=errors[grid][component],gate=gate)
    factor=gates['refinement_error_reduction_factor']
    for component in ('projected_ref_count','strict_cdf'):
        check('refinement_'+component,errors[127][component]*factor<errors[31][component],coarse=errors[31][component],fine=errors[127][component])
    check('multiple_events',float(values[31][5])>gates['stress_expected_event_count_minimum'],expected_events=float(values[31][5]))
    check('PDE_probability_mass',max(c['mass_error'] for c in calls)<1e-8,max_error=max(c['mass_error'] for c in calls))
    return dict(schema='joint-kernel-continuum-sensitivity-v1',passed=all(c['passed'] for c in checks),checks=checks,
      autodiff_jacobians={str(k):v.tolist() for k,v in ad.items()},
      reference_centered_FD={str(k):v.tolist() for k,v in references.items()},
      finite_observables={str(k):v.tolist() for k,v in values.items()},reference_observables=reference_values,
      errors=errors,reference_calls=calls,wall_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu)


if __name__=='__main__':
    torch.set_num_threads(1)
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',default='001');parser.add_argument('--published-source-commit',required=True)
    args=parser.parse_args();commit=args.published_source_commit
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise ValueError('full source commit required')
    protocol=json.loads((HERE/'joint_kernel_sensitivity_protocol.json').read_text())
    if digest(HERE/'joint_kernel.py')!=protocol['kernel_sha256']:raise ValueError('frozen kernel changed')
    before=hashes();prefix=HERE/('joint_kernel_sensitivity_attempt_'+args.attempt)
    sources={path:Path(path).read_text() for path in before}
    with prefix.with_name(prefix.name+'_sources.json.gz').open('xb') as f:f.write(gzip.compress(json.dumps(sources,sort_keys=True).encode(),mtime=0))
    try:result=run(protocol)
    except Exception:result=dict(schema='joint-kernel-continuum-sensitivity-v1',passed=False,error=traceback.format_exc())
    result.update(published_source_commit=commit,source_sha256=before,sources_unchanged_at_end=hashes()==before,
      runtime=dict(torch=torch.__version__,numpy=np.__version__,scipy=scipy.__version__,dtype='float64'))
    result['passed']=result['passed'] and result['sources_unchanged_at_end']
    with prefix.with_suffix('.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('autodiff_jacobians','reference_centered_FD','reference_calls')},indent=2))
    raise SystemExit(0 if result['passed'] else 1)
