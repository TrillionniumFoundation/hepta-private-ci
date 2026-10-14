"""R6 create-only continuous-law sweep. Seal predictions before reference fitting."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1'); os.environ.setdefault('MKL_NUM_THREADS','1')
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
from domain import PARENT, Policy, make_problem, rule, probe, evaluate
from solver import fit

torch.set_num_threads(1)
PROTOCOL = 'f2b5f2fa13de7638d8f4eb26dcf6b15d2d7f5948'


def digest(data): return hashlib.sha256(data).hexdigest()


def dump(path, obj):
    data = (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    with open(path,'xb') as f: f.write(data)
    return digest(data)


def save(path, obj):
    with open(path,'xb') as f: np.savez_compressed(f, **obj)


def sources():
    here=Path(__file__).parent
    return {str(p.relative_to(here.parent)):digest(p.read_bytes()) for directory in (here,PARENT)
            for p in sorted(directory.glob('*.py'))}


def specs():
    runs=[]; seeds=(11,23,47)
    for r in ('corners','cc3','cc5'):
        for i,s in enumerate(seeds):
            for m in (('adam','adjoint') if i%2==0 else ('adjoint','adam')):
                runs.append(dict(family='nonlinear',method=m,seed=s,rule=r,ridge=0.))
    for s in seeds:
        for m in ('adtrust','lbfgs','root'):
            runs.append(dict(family='nonlinear',method=m,seed=s,rule='cc5',ridge=0.))
        for m in ('adam','adjoint'):
            runs.append(dict(family='nonlinear',method=m,seed=s,rule='cc5',ridge=.001))
        runs.append(dict(family='attention',method='adam',seed=s,rule='cc5',ridge=0.))
        runs.append(dict(family='nonlinear',method='none',seed=s,rule='cc5',ridge=0.))
    for f,methods in [('matrix',('adam','adjoint')),('scalar',('adam','root'))]:
        for m in methods:runs.append(dict(family=f,method=m,seed=11,rule='cc5',ridge=0.))
    return runs


def name_for(s):
    return f"{s['family']}-{s['method']}-{s['rule']}-s{s['seed']}-r{float(s['ridge']):g}"


def panels():
    for r in ('cc3','cc5','cc9','cc17','gl9'):
        s,w=rule(r); yield r,s,w,make_problem(),'same_parent_quadrature'
    for k in range(4):
        s=probe(k); yield f'qmc{k}',s,np.full(len(s),1/len(s)),make_problem(),'same_parent_scramble'
    s=probe(0)[:128]
    for name,states,change in [('scale',2*s,'base'),('dynamics',s,'dynamics'),('horizon4',s,'horizon')]:
        yield name,states,np.full(len(states),1/len(states)),make_problem(change),'changed_problem'


def gradient_at(policy,theta,p,name,ridge=0.):
    s,w=rule(name);grad=torch.zeros_like(theta)
    for i in range(0,len(s),256):
        fn=lambda z:policy.value(z,p,s[i:i+256],w[i:i+256])
        grad=grad+torch.func.grad(fn)(theta).detach()
    return grad+ridge*theta/theta.numel()


def trial(out,spec,budget):
    start=time.process_time(),time.perf_counter();out.mkdir(parents=True,exist_ok=False)
    plan=dict(spec=spec,budget=budget,source=sources(),protocol_commit=PROTOCOL)
    ph=dump(out/'PLAN.json',plan);dump(out/'STARTED.json',dict(plan_sha256=ph))
    p=make_problem();state,w=rule(spec['rule']);pol=Policy(spec['family'],spec['seed'])
    save(out/'TRAIN_LAW.npz',dict(states=state,weights=w));save(out/'INITIAL.npz',dict(theta=pol.initial))
    prep=time.process_time()-start[0]
    theta,info=fit(pol,p,state,w,spec['method'],budget,spec['ridge'])
    wh=digest(theta.tobytes());save(out/'WEIGHTS.npz',dict(theta=theta))
    dump(out/'WEIGHT_SEAL.json',dict(sha256=wh));fit_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    t=time.process_time();raw={};metrics={};times={};z=torch.tensor(theta)
    for name,ss,ww,pp,scope in panels():
        now=time.process_time();values=evaluate(pol,z,pp,ss)
        if not np.isfinite(values).all(): raise FloatingPointError('nonfinite panel: '+name)
        raw[name]=values;metrics[name]=float(ww@values.mean(1));times[name]=time.process_time()-now
    # One fixed reference subset: all action paths saved, no optimal labels queried.
    ss=probe(0)[:16]
    with torch.no_grad():
        costs,L,tilts,end,_=pol.tree(z,p,ss)
    raw['ref_cost']=costs.numpy();raw['ref_errors']=end['errors'].numpy();raw['ref_mass']=end['mass'].numpy()
    for k,item in enumerate(L):raw[f'ref_actions{k}']=item['u'].numpy()
    save(out/'PREDICTIONS.npz',raw);rh=digest((out/'PREDICTIONS.npz').read_bytes())
    dump(out/'PREDICTIONS_SEAL.json',dict(sha256=rh,weights=wh))
    prediction=time.process_time()-t;t=time.process_time()
    g5=gradient_at(pol,z,p,'cc5');g9=gradient_at(pol,z,p,'cc9')
    with torch.no_grad():training=float(pol.value(z,p,state,w,spec['ridge']))
    gradient_arrays=dict(cc5=g5.numpy(),cc9=g9.numpy())
    hmin=None
    if spec['family']!='attention':
        H=torch.func.jacfwd(torch.func.grad(lambda v:pol.value(v,p,state,w,spec['ridge'])))(z).detach().numpy()
        hmin=float(np.linalg.eigvalsh((H+H.T)/2).min())
    save(out/'DIAGNOSTICS.npz',gradient_arrays)
    qmc=np.array([metrics[f'qmc{k}'] for k in range(4)])
    report=dict(spec=spec,plan_sha256=ph,source=plan['source'],budget=budget,fit=info,parameters=len(theta),
                initial_sha256=digest(pol.initial.tobytes()),weight_sha256=wh,prediction_sha256=rh,
                law_sha256=digest((out/'TRAIN_LAW.npz').read_bytes()),weight_change=float(np.linalg.norm(theta-pol.initial)),
                train_objective=training,ridge_cost=.5*spec['ridge']*float(np.mean(theta**2)),metrics=metrics,
                integration=dict(cc17_minus_cc9=metrics['cc17']-metrics['cc9'],cc17_minus_gl9=metrics['cc17']-metrics['gl9'],
                                 qmc_mean=float(qmc.mean()),qmc_se=float(qmc.std(ddof=1)/2),
                                 qmc_minus_cc17=float(qmc.mean()-metrics['cc17']),certified_error_bound=False),
                diagnostics=dict(cc5_gradient_inf=float(g5.abs().max()),cc9_gradient_inf=float(g9.abs().max()),
                                 gradient_rule_difference_inf=float((g9-g5).abs().max()),training_hessian_min=hmin),
                phase_cpu=dict(preparation=prep,predictions_and_seal=prediction,postfit_diagnostics=time.process_time()-t),
                panel_cpu=times,fit_peak_rss=fit_peak,peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                cpu_from_main=time.process_time()-start[0],wall_from_main=time.perf_counter()-start[1],
                environment=dict(python=sys.version,torch=torch.__version__,numpy=np.__version__,scipy=scipy.__version__,
                                 platform=platform.platform(),threads=torch.get_num_threads()),
                energy_joules=None,total_flops=None,production_authorized=False,project_cloud=False)
    if sources()!=plan['source']:raise ValueError('source drift')
    dump(out/'REPORT.json',report)
    print(json.dumps(dict(name=name_for(spec),cc17=metrics['cc17'],qmc=report['integration']['qmc_mean'],fit_cpu=info['cpu'])),flush=True)


def sweep(out,budget):
    out.mkdir(parents=True,exist_ok=False)
    inputs={}
    for name,s,w,p,scope in panels():inputs[name+'_states']=s;inputs[name+'_weights']=w
    save(out/'EVALUATION_LAWS.npz',inputs)
    plan=dict(source=sources(),protocol_commit=PROTOCOL,runs=specs(),budget=budget,
              evaluation_laws_sha256=digest((out/'EVALUATION_LAWS.npz').read_bytes()),
              primary='CC5 nonlinear adjoint vs Adam, ridge=0, CC17 cost checked by GL9/QMC, all seeds',
              known_continuous_parent=True,exact_continuous_integration=False,production_authorized=False)
    ph=dump(out/'PLAN.json',plan);rows=[];start=time.perf_counter()
    for spec in specs():
        name=name_for(spec);cmd=[sys.executable,str(Path(__file__).resolve()),'trial','--out',str(out/name),'--budget',str(budget)]
        for k,v in spec.items():cmd+=['--'+k,str(v)]
        before=resource.getrusage(resource.RUSAGE_CHILDREN);t=time.perf_counter()
        row=dict(name=name,spec=spec)
        with open(out/(name+'.log'),'xb') as log:
            try:
                r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=180)
                row.update(status='complete' if r.returncode==0 else 'failed',returncode=r.returncode)
            except subprocess.TimeoutExpired:row.update(status='timeout',returncode=None)
            except OSError as e:row.update(status='launch_error',returncode=None,error=str(e))
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,child_wall=time.perf_counter()-t)
        if row['status']=='complete':row['report_sha256']=digest((out/name/'REPORT.json').read_bytes())
        rows.append(row);dump(out/(name+'.completion.json'),row);print(json.dumps(row),flush=True)
    if sources()!=plan['source']:raise ValueError('sweep source drift')
    failures=sum(r['status']!='complete' for r in rows)
    dump(out/'COMPLETE.json',dict(plan_sha256=ph,census=rows,failed=failures,complete=len(rows)-failures,
                                wall=time.perf_counter()-start,child_cpu=sum(r['child_cpu'] for r in rows)))
    if failures:raise SystemExit('failures retained')


def main():
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['sweep','trial']);a.add_argument('--out',type=Path,required=True)
    a.add_argument('--family',choices=['nonlinear','attention','matrix','scalar']);a.add_argument('--method',choices=['adam','adjoint','adtrust','lbfgs','root','none'])
    a.add_argument('--seed',type=int,default=11);a.add_argument('--rule',choices=['corners','cc3','cc5'],default='cc5')
    a.add_argument('--ridge',type=float,default=0.);a.add_argument('--budget',type=float,default=8.);v=a.parse_args()
    if not np.isfinite(v.budget) or v.budget<=0 or not np.isfinite(v.ridge) or v.ridge<0:a.error('invalid budget/ridge')
    if v.mode=='sweep':sweep(v.out,v.budget)
    else:
        if v.family is None or v.method is None:a.error('family/method required')
        if v.family=='attention' and v.method!='adam':a.error('attention only Adam')
        trial(v.out,{k:getattr(v,k) for k in ('family','method','seed','rule','ridge')},v.budget)

if __name__=='__main__':main()
