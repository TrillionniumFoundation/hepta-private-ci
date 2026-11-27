"""R7 source-frozen, fresh-process solver comparison; no evaluation feedback."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import hashlib
import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import qmc
import torch

from solver import fit, Policy, make_problem, rule
from domain import SCALE, evaluate

torch.set_num_threads(1)
HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    data=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with open(path,'xb') as f:
        f.write(data)
    return digest(data)


def save(path, value):
    with open(path,'xb') as f:
        np.savez_compressed(f,**value)


def sources():
    return {str(p.relative_to(HERE.parent)):digest(p.read_bytes())
            for folder in (HERE,HERE.parent/'continuous',HERE.parent/'nonquadratic')
            for p in sorted(folder.glob('*.py'))}


def specs():
    result=[]
    methods=['adam','dense','adjoint_ncg','ad_ncg','lbfgs']
    for i,seed in enumerate((11,23,47)):
        order=methods[i:]+methods[:i]
        for schedule in ('cc5','adaptive'):
            for method in order:
                result.append(dict(seed=seed,method=method,schedule=schedule))
        for method in ('adam','adjoint_ncg'):
            result.append(dict(seed=seed,method=method,schedule='cc3'))
        result.append(dict(seed=seed,method='none',schedule='cc5'))
    return result


def name_for(s):
    return f"{s['method']}-{s['schedule']}-s{s['seed']}"


def probe(rep):
    if rep not in range(4):
        raise ValueError('invalid probe')
    return (2*qmc.Sobol(4,scramble=True,seed=2026101471+rep).random_base2(9)-1)*SCALE


def panels():
    for name in ('cc3','cc5','cc9','cc17','gl9'):
        s,w=rule(name)
        yield name,s,w,make_problem(),'same_continuous_law'
    for k in range(4):
        s=probe(k)
        yield f'qmc{k}',s,np.full(len(s),1/len(s)),make_problem(),'same_continuous_law'
    s=probe(0)[:128]
    for name,ss,change in [('scale',2*s,'base'),('dynamics',s,'dynamics'),('horizon4',s,'horizon')]:
        yield name,ss,np.full(len(ss),1/len(ss)),make_problem(change),'changed_problem'


def gradient_at(policy, theta, name):
    s,w=rule(name)
    result=torch.zeros_like(theta)
    for i in range(0,len(s),256):
        f=lambda z:policy.value(z,make_problem(),s[i:i+256],w[i:i+256])
        result+=torch.func.grad(f)(theta).detach()
    return result


def trial(out,spec,budget):
    out.mkdir(parents=True,exist_ok=False)
    begin=time.process_time(),time.perf_counter()
    plan=dict(schema='hepta.ndu.matrix-free.r7',spec=spec,budget=budget,source=sources(),
              parent='569f302a5dbdfb1dd15e3454d6c2ddc5e8170321',
              protocol_sha256=digest((HERE/'PROTOCOL.md').read_bytes()),
              probe_seeds=[2026101471+k for k in range(4)],
              primary='fixed CC5, adjoint_ncg versus Adam; CC17 cost, all three seeds')
    ph=dump(out/'PLAN.json',plan)
    dump(out/'STARTED.json',dict(plan_sha256=ph))
    policy=Policy('nonlinear',spec['seed'])
    save(out/'INITIAL.npz',dict(theta=policy.initial))
    laws={}
    for name in ('cc3','cc5'):
        s,w=rule(name);laws[name+'_states']=s;laws[name+'_weights']=w
    save(out/'TRAIN_LAWS.npz',laws)
    theta,info=fit(spec['seed'],spec['method'],spec['schedule'],budget)
    fit_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    save(out/'WEIGHTS.npz',dict(theta=theta))
    wh=digest(theta.tobytes())
    dump(out/'WEIGHT_SEAL.json',dict(sha256=wh))
    now=time.process_time()
    raw,metrics,ptimes={},{},{}
    z=torch.tensor(theta)
    for name,s,w,p,scope in panels():
        t=time.process_time();v=evaluate(policy,z,p,s)
        if not np.isfinite(v).all():
            raise FloatingPointError('nonfinite panel '+name)
        raw[name]=v;metrics[name]=float(w@v.mean(1));ptimes[name]=time.process_time()-t
    # Four fixed action-coordinate cross-check cases; reference fit comes later.
    with torch.no_grad():
        costs,levels,_,terminal,_=policy.tree(z,make_problem(),probe(0)[:2])
    raw['check_costs']=costs.numpy()
    for k,L in enumerate(levels):
        raw[f'check_actions{k}']=L['u'].numpy()
    save(out/'PREDICTIONS.npz',raw)
    predhash=digest((out/'PREDICTIONS.npz').read_bytes())
    dump(out/'PREDICTIONS_SEAL.json',dict(sha256=predhash,weights=wh))
    pred_cpu=time.process_time()-now
    now=time.process_time()
    g5,g9=gradient_at(policy,z,'cc5'),gradient_at(policy,z,'cc9')
    save(out/'DIAGNOSTICS.npz',dict(g5=g5.numpy(),g9=g9.numpy()))
    with torch.no_grad():
        s,w=rule(info['final_rule'])
        f=float(policy.value(z,make_problem(),s,w))
    q=np.array([metrics[f'qmc{k}'] for k in range(4)])
    report=dict(plan_sha256=ph,spec=spec,budget=budget,source=plan['source'],
                fit=info,parameters=len(theta),initial_sha256=digest(policy.initial.tobytes()),
                weights_sha256=wh,changed=not np.array_equal(theta,policy.initial),
                law_sha256=digest((out/'TRAIN_LAWS.npz').read_bytes()),
                prediction_sha256=predhash,metrics=metrics,training_cost=f,
                integration=dict(cc17_minus_cc9=metrics['cc17']-metrics['cc9'],
                                 cc17_minus_gl9=metrics['cc17']-metrics['gl9'],
                                 qmc_mean=float(q.mean()),qmc_se=float(q.std(ddof=1)/2),
                                 certified=False),
                diagnostics=dict(g5_inf=float(g5.abs().max()),g9_inf=float(g9.abs().max()),
                                 gradient_rule_delta=float((g9-g5).abs().max()),
                                 stationary_minimum_certified=False),
                phases_cpu=dict(fit=info['cpu'],evaluation_seal=pred_cpu,
                                diagnostics=time.process_time()-now),
                panel_cpu=ptimes,fit_peak_rss=fit_peak,
                process_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                total_main_cpu=time.process_time()-begin[0],total_main_wall=time.perf_counter()-begin[1],
                environment=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,
                                 torch=torch.__version__,platform=platform.platform(),threads=torch.get_num_threads()),
                total_flops=None,energy_joules=None,production_authorized=False,project_cloud=False)
    if sources()!=plan['source']:
        raise ValueError('source drift')
    dump(out/'REPORT.json',report)
    print(json.dumps(dict(name=name_for(spec),cc17=metrics['cc17'],cpu=info['cpu'],counts=info['counts'])),flush=True)


def sweep(out,budget):
    out.mkdir(parents=True,exist_ok=False)
    laws={}
    for name,s,w,p,scope in panels():
        laws[name+'_states']=s;laws[name+'_weights']=w
    save(out/'EVALUATION_LAWS.npz',laws)
    plan=dict(source=sources(),specs=specs(),budget=budget,
              protocol_sha256=digest((HERE/'PROTOCOL.md').read_bytes()),
              evaluation_sha256=digest((out/'EVALUATION_LAWS.npz').read_bytes()),
              primary='fixed CC5 adjoint_ncg vs Adam, no ridge, CC17 cost with GL9/QMC cross-check',
              adaptive_is_secondary=True,holdout_selection=False,production_authorized=False)
    ph=dump(out/'PLAN.json',plan)
    start=time.perf_counter();census=[]
    for s in specs():
        name=name_for(s)
        cmd=[sys.executable,str(Path(__file__).resolve()),'trial','--out',str(out/name),'--budget',str(budget)]
        for k,v in s.items():
            cmd+=['--'+k,str(v)]
        before=resource.getrusage(resource.RUSAGE_CHILDREN);now=time.perf_counter()
        entry=dict(name=name,spec=s)
        with open(out/(name+'.log'),'xb') as log:
            try:
                r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=180)
                entry.update(returncode=r.returncode,status='completed' if r.returncode==0 else 'failed')
            except subprocess.TimeoutExpired:
                entry.update(returncode=None,status='timeout')
            except OSError as exc:
                entry.update(returncode=None,status='launch_failed',error=str(exc))
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        entry.update(child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                     child_wall=time.perf_counter()-now)
        if entry['status']=='completed':
            entry['report_sha256']=digest((out/name/'REPORT.json').read_bytes())
        census.append(entry)
        dump(out/(name+'.completion.json'),entry)
        print(json.dumps(entry),flush=True)
    failed=sum(r['status']!='completed' for r in census)
    dump(out/'COMPLETE.json',dict(plan_sha256=ph,census=census,failed=failed,
                                completed=len(census)-failed,wall=time.perf_counter()-start,
                                child_cpu=sum(r['child_cpu'] for r in census)))
    if failed or sources()!=plan['source']:
        raise SystemExit('failed/inconsistent sweep; original evidence retained')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['trial','sweep'])
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--method',choices=['adam','dense','adjoint_ncg','ad_ncg','lbfgs','none'],default='adjoint_ncg')
    p.add_argument('--schedule',choices=['cc3','cc5','adaptive'],default='cc5')
    p.add_argument('--seed',type=int,default=11)
    p.add_argument('--budget',type=float,default=8.)
    a=p.parse_args()
    if not np.isfinite(a.budget) or a.budget<=0 or a.seed<0:
        p.error('invalid seed/budget')
    if a.mode=='sweep':
        sweep(a.out,a.budget)
    else:
        trial(a.out,dict(seed=a.seed,method=a.method,schedule=a.schedule),a.budget)


if __name__=='__main__':
    main()
