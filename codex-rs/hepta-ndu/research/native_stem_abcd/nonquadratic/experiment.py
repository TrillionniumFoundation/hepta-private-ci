"""R5 complete, create-only, fresh-process numerical experiment. No oracle in fit."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MKL_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import numpy as np
import scipy
import torch
from torch import nn
from problem import initial,initial_weights,make_problem,objective,rollout
from solve import fit

torch.set_num_threads(1)
PROTOCOL_COMMIT='779b4bb92fee43a649d0a0ef0836d7046374d31c'

def digest(b):return hashlib.sha256(b).hexdigest()
def dump(path,x):
    b=(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    with open(path,'xb') as f:f.write(b)
    return digest(b)
def sources():return {p.name:digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}
def save(path,data):
    with open(path,'xb') as f:np.savez_compressed(f,**data)

class Attention(nn.Module):
    def __init__(self,seed):
        super().__init__()
        with torch.random.fork_rng():
            torch.manual_seed(seed);self.embed=nn.Linear(5,8)
            self.block=nn.TransformerEncoderLayer(8,2,16,dropout=0.,batch_first=True,norm_first=True)
            self.out=nn.Linear(8,2)
            with torch.no_grad():self.out.weight.mul_(.1);self.out.bias.zero_()
        self.double()
    def forward(self,s,mode,k,bound):
        ctx=torch.stack((mode.to(torch.float64),torch.full_like(mode,k%3,dtype=torch.float64)/2),-1)
        a=torch.cat((s[:,:2],ctx,torch.zeros_like(s[:,:1])),-1)
        b=torch.cat((s[:,2:],ctx,torch.ones_like(s[:,:1])),-1)
        raw=self.out(self.block(self.embed(torch.stack((a,b),1)))[:,0])
        return bound*torch.tanh(raw/bound)

def avector(m):return torch.cat([p.detach().flatten() for p in m.parameters()]).numpy().copy()
def restore_attention(m,v):
    offset=0
    with torch.no_grad():
        for p in m.parameters():p.copy_(torch.tensor(v[offset:offset+p.numel()]).reshape(p.shape));offset+=p.numel()
    if offset!=len(v):raise ValueError('weight length')

def fit_attention(m,p,states,seconds):
    t=time.process_time();wall=time.perf_counter();opt=torch.optim.Adam(m.parameters(),lr=.015)
    hist=[];count=0
    while time.process_time()-t<seconds:
        opt.zero_grad(set_to_none=True);loss=rollout(None,p,states,policy=m)[0].mean()
        if not torch.isfinite(loss):raise FloatingPointError('attention objective')
        loss.backward();opt.step();count+=1
        if count%25==0:hist.append(dict(cpu=time.process_time()-t,objective=float(loss.detach()),objective_is_pre_update=True))
    return dict(status='cpu_cap',cpu=time.process_time()-t,wall=time.perf_counter()-wall,
                counts=dict(objectives=count,gradients=count,hessians=0,accepted=count,ad_lanes=0),history=hist)

def panels():
    return [('train','train','base'),('new','new','base'),('scale','scale','base'),
            ('correlated','correlated','base'),('risk_zero','new','risk'),('quartic','new','quartic'),
            ('dynamics','new','dynamics'),('horizon4','new','horizon')]

def cases():
    runs=[];seeds=(11,23,47)
    for seed in seeds:
        for m in ('adam','adjoint'):runs.append(dict(family='nonlinear',method=m,seed=seed,budget=2))
    base=['adam','adjoint','adtrust','root','lbfgs']
    for i,seed in enumerate(seeds):
        for method in base[i:]+base[:i]:runs.append(dict(family='nonlinear',method=method,seed=seed,budget=8))
        for method in ('adam','adjoint'):runs.append(dict(family='matrix',method=method,seed=seed,budget=8))
        runs.append(dict(family='attention',method='adam',seed=seed,budget=8))
    for method in ('adam','root'):runs.append(dict(family='scalar',method=method,seed=11,budget=8))
    runs.extend(dict(family='nonlinear',method='none',seed=s,budget=1) for s in seeds)
    return runs

def name_for(s):return f"{s['family']}-{s['method']}-s{s['seed']}-b{s['budget']}"

def trial(args):
    start=time.process_time(),time.perf_counter();out=args.out;out.mkdir(parents=True,exist_ok=False)
    spec={k:getattr(args,k) for k in ('family','method','seed','budget')}
    plan=dict(spec=spec,source=sources(),protocol_commit=PROTOCOL_COMMIT,panels=panels(),
              no_reference_in_fit=True,calibration='not_applicable_no_probability_head')
    ph=dump(out/'PLAN.json',plan);dump(out/'STARTED.json',dict(plan_sha256=ph))
    p=make_problem();states=initial();m=None
    if args.family=='attention':m=Attention(args.seed);init=avector(m)
    else:init=initial_weights(args.seed,args.family)
    save(out/'INITIAL.npz',dict(theta=init))
    initialization=time.process_time()-start[0]
    if m is None:theta,fitting=fit(p,states,args.family,args.method,args.seed,args.budget)
    else:fitting=fit_attention(m,p,states,args.budget);theta=avector(m)
    save(out/'WEIGHTS.npz',dict(theta=theta));wh=digest(theta.tobytes())
    dump(out/'WEIGHT_SEAL.json',dict(sha256=wh));fitpeak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    raw={};t=time.process_time()
    for name,split,change in panels():
        pp=make_problem(change);ss=initial(split)
        with torch.no_grad():v,L,tilts,end,_=rollout(torch.tensor(theta),pp,ss,args.family,policy=m)
        raw[name+'_cost']=v.numpy();raw[name+'_states']=end['h'].numpy();raw[name+'_errors']=end['errors'].numpy()
        raw[name+'_mass']=end['mass'].numpy();raw[name+'_initial']=ss
        for k,item in enumerate(L):raw[name+f'_actions_{k}']=item['u'].numpy()
    if not all(np.isfinite(a).all() for a in raw.values()):raise FloatingPointError('nonfinite prediction')
    save(out/'PREDICTIONS.npz',raw);rh=digest((out/'PREDICTIONS.npz').read_bytes())
    dump(out/'PREDICTIONS_SEAL.json',dict(sha256=rh,weights=wh))
    prediction=time.process_time()-t;t=time.process_time()
    if m is None:
        th=torch.tensor(theta)
        grad=torch.func.grad(lambda z:objective(z,p,states,args.family))(th)
        H=torch.func.hessian(lambda z:objective(z,p,states,args.family))(th)
        training=float(objective(th,p,states,args.family))
        diag=dict(gradient_inf=float(grad.abs().max()),hessian_min=float(torch.linalg.eigvalsh(H).min()))
    else:
        m.zero_grad(set_to_none=True);loss=rollout(None,p,states,policy=m)[0].mean();loss.backward()
        training=float(loss.detach());diag=dict(gradient_inf=max(float(p.grad.abs().max()) for p in m.parameters()),hessian_min=None)
    report=dict(spec=spec,plan_sha256=ph,source=plan['source'],fitting=fitting,
                initial_sha256=digest(init.tobytes()),weight_sha256=wh,prediction_sha256=rh,
                parameters=len(theta),weight_change=float(np.linalg.norm(theta-init)),train_objective=training,
                diagnostics=diag,phases_cpu=dict(initialization=initialization,prediction_seal=prediction,
                                                postfit_diagnostics=time.process_time()-t),
                fit_peak_rss=fitpeak,peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                cpu_from_main=time.process_time()-start[0],wall_from_main=time.perf_counter()-start[1],
                environment=dict(python=sys.version,torch=torch.__version__,numpy=np.__version__,scipy=scipy.__version__,
                                 platform=platform.platform(),threads=torch.get_num_threads()),
                flops=None,energy_joules=None,project_cloud=False,production_authorized=False)
    if sources()!=plan['source']:raise ValueError('source drift')
    dump(out/'REPORT.json',report)
    print(json.dumps(dict(name=name_for(spec),training=training,fit=fitting['cpu'],diag=diag)),flush=True)

def sweep(out):
    out.mkdir(parents=True,exist_ok=False)
    plan=dict(source=sources(),protocol_commit=PROTOCOL_COMMIT,runs=cases(),panels=panels(),
              primary='nonlinear adjoint vs Adam new-state regret interval at 8-second cap, all seeds',
              oracle_after_all_predictions=True,production_authorized=False)
    sha=dump(out/'PLAN.json',plan);rows=[];start=time.perf_counter()
    for s in cases():
        name=name_for(s);command=[sys.executable,str(Path(__file__).resolve()),'trial','--out',str(out/name)]
        for k,v in s.items():command+=['--'+k,str(v)]
        before=resource.getrusage(resource.RUSAGE_CHILDREN);t=time.perf_counter();row=dict(name=name,spec=s)
        with open(out/(name+'.log'),'xb') as log:
            try:
                r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=120)
                row.update(status='complete' if r.returncode==0 else 'failed',returncode=r.returncode)
            except subprocess.TimeoutExpired:row.update(status='timeout',returncode=None)
            except OSError as e:row.update(status='launch_error',returncode=None,error=str(e))
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,child_wall=time.perf_counter()-t)
        if row['status']=='complete':row['report_sha256']=digest((out/name/'REPORT.json').read_bytes())
        rows.append(row);dump(out/(name+'.completion.json'),row);print(json.dumps(row),flush=True)
    if sources()!=plan['source']:raise ValueError('source drift')
    failed=sum(r['status']!='complete' for r in rows)
    dump(out/'COMPLETE.json',dict(plan_sha256=sha,census=rows,complete=len(rows)-failed,failed=failed,
                                wall=time.perf_counter()-start,child_cpu=sum(r['child_cpu'] for r in rows)))
    if failed:raise SystemExit('failed attempts retained')

def main():
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['trial','sweep']);a.add_argument('--out',type=Path,required=True)
    a.add_argument('--family',choices=['nonlinear','matrix','scalar','attention']);a.add_argument('--method',choices=['adam','adjoint','adtrust','root','lbfgs','none'])
    a.add_argument('--seed',type=int,default=11);a.add_argument('--budget',type=float,default=8);args=a.parse_args()
    if not np.isfinite(args.budget) or args.budget<=0 or args.seed<0:a.error('invalid budget/seed')
    if args.mode=='sweep':sweep(args.out)
    else:
        if args.family is None or args.method is None:a.error('family/method required')
        if args.family=='attention' and args.method!='adam':a.error('attention only Adam')
        trial(args)

if __name__=='__main__':main()
