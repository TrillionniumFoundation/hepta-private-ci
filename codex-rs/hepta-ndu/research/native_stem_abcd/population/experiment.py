"""R4 source-bound finite-population experiment. No model selection on evaluation."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import hashlib
import json
import platform
from pathlib import Path
import resource
import subprocess
import sys
import time
import numpy as np
import scipy
import torch
from problem import (AttentionStem,MatrixStem,make_problem,initial_states,objective,
                     enumerate_policy,riccati,moment_gradient,stationarity,scalar_lower_bound)
from solve import vector,assign,fit

torch.set_num_threads(1)


def digest(data):return hashlib.sha256(data).hexdigest()


def write(path,value):
    data=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    with open(path,'xb') as f:f.write(data)
    return digest(data)


def sources():
    return {p.name:digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}


def specs():
    runs=[]
    groups=[('matrix','adam'),('matrix','adjoint'),('matrix','lbfgs'),('matrix','gradient_root'),('attention','adam')]
    for i,seed in enumerate((11,23,47)):
        for family,method in groups[i:]+groups[:i]:
            runs.append(dict(family=family,method=method,seed=seed,cap=8))
        for method in ('adam','adjoint'):runs.append(dict(family='matrix',method=method,seed=seed,cap=2))
    for family in ('scalar','diagonal'):
        for method in ('adam','gradient_root'):runs.append(dict(family=family,method=method,seed=0,cap=8))
    for seed in (11,23,47):runs.append(dict(family='matrix',method='none',seed=seed,cap=0))
    runs.append(dict(family='direct',method='none',seed=0,cap=0))
    return runs


def name_for(s):return f"{s['family']}-{s['method']}-s{s['seed']}-b{s['cap']}"


def panels():
    return [('train','base','train'),('new_initial','base','new'),('scale','base','scale'),
            ('correlated','base','correlated'),('dynamics','dynamics','new'),
            ('preference','preference','new'),('noise','noise','new'),('horizon4','horizon','new')]


def model_for(family,seed):
    if family=='direct':return None
    if family=='attention':return AttentionStem(seed)
    return MatrixStem(seed,family)


def to_arrays(raw):return {k:v.detach().numpy() for k,v in raw.items()}


def score(raw,problem,states):
    # This reference may only run after every prediction panel is sealed.
    K,P,c,H=riccati(problem)
    expected=np.array([s@P[p]@s+c[p] for s in states for p in range(2)])
    error=raw['states'][:,:3]-raw['states'][:,3:]@problem.target.T
    readouts=np.random.default_rng(2026101442).normal(size=(7,3))
    readouts/=np.linalg.norm(readouts,axis=1,keepdims=True)
    n=len(raw['cost'])
    task=np.sum(raw['prob'][:,None]*(error@problem.readouts.T)**2)/(n*len(problem.readouts))
    newtask=np.sum(raw['prob'][:,None]*(error@readouts.T)**2)/(n*len(readouts))
    return dict(objective=float(raw['cost'].mean()),optimal_objective=float(expected.mean()),
                objective_gap=float(raw['cost'].mean()-expected.mean()),
                value_to_optimum_rmse=float(np.sqrt(np.mean((raw['cost']-expected)**2))),
                original_task_mse=float(task),new_readout_mse=float(newtask),
                leaf_cases=len(raw['prob']),initial_cases=n,
                minimum_reference_action_hessian_eigenvalue=float(np.linalg.eigvalsh(H).min()),
                probability_calibration=None)


def trial(s,out):
    started=time.process_time(),time.perf_counter();out.mkdir(parents=True,exist_ok=False)
    plan=dict(schema='hepta.ndu.population.r4',run=s,source_sha256=sources(),panels=panels(),
              objective='exact population discounted preference-modulated quadratic recursive cost',
              reference_in_fit=False,production_authorized=False)
    phash=write(out/'PLAN.json',plan);write(out/'STARTED.json',dict(plan_sha256=phash))
    p=make_problem();model=model_for(s['family'],s['seed']);initial=None if model is None else vector(model)
    if model is None:
        t=time.process_time();selected=riccati(p)[0].reshape(-1)
        fitted=dict(method='direct_riccati',cpu_seconds=time.process_time()-t,counts={})
    else:
        with open(out/'INITIAL.npy','xb') as f:np.save(f,initial,allow_pickle=False)
        fitted=(fit(model,p,s['method'],s['cap']) if s['method']!='none' else
                dict(method='none',cpu_seconds=0.,counts={}))
        selected=vector(model)
    with open(out/'WEIGHTS.npy','xb') as f:np.save(f,selected,allow_pickle=False)
    whash=digest(selected.tobytes());write(out/'WEIGHT_SEAL.json',dict(sha256=whash))
    fit_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    raw={};t=time.process_time();panel_times={}
    with torch.no_grad():
        for name,change,split in panels():
            now=time.process_time();pr=make_problem(change);st=initial_states(split)
            # D is an adaptive known-problem reference. It is NOT a frozen learned policy.
            gain=torch.tensor(riccati(pr)[0]) if model is None else None
            result=to_arrays(enumerate_policy(model,pr,st,gains=gain))
            for k,v in result.items():
                if not np.isfinite(v).all():raise FloatingPointError('nonfinite output')
                raw[name+'__'+k]=v
            panel_times[name]=time.process_time()-now
    with open(out/'PREDICTIONS.npz','xb') as f:np.savez_compressed(f,**raw)
    rhash=digest((out/'PREDICTIONS.npz').read_bytes())
    write(out/'PREDICTIONS_SEAL.json',dict(sha256=rhash,weights=whash))
    prediction_cpu=time.process_time()-t
    t=time.process_time();metrics={}
    for name,change,split in panels():
        arr={k.split('__')[1]:v for k,v in raw.items() if k.startswith(name+'__')}
        metrics[name]=score(arr,make_problem(change),initial_states(split))
    reference_cpu=time.process_time()-t
    t=time.process_time();replay=0.;diagnostics={}
    if model is not None:
        restored=model_for(s['family'],s['seed']);assign(restored,np.load(out/'WEIGHTS.npy',allow_pickle=False))
        with torch.no_grad():
            for name,change,split in panels():
                again=to_arrays(enumerate_policy(restored,make_problem(change),initial_states(split)))
                for k,v in again.items():replay=max(replay,float(np.max(np.abs(v-raw[name+'__'+k]))))
            diagnostics['training_objective']=float(objective(model,p,initial_states()))
            if isinstance(model,MatrixStem):
                g,M=moment_gradient(model,p,initial_states())
                diagnostics['minimum_conditional_second_moment_eigenvalue']=float(torch.linalg.eigvalsh(M).min())
                if s['family']=='matrix':
                    diagnostics['adjoint_max_residual']=float(stationarity(model,p,model.weights).abs().max())
                    diagnostics['population_gradient_max']=float(g.abs().max())
                    diagnostics['reference_gain_max_error']=float(np.max(np.abs(model.gains().numpy()-riccati(p)[0])))
        if replay>1e-12 or digest(vector(model).tobytes())!=whash:raise ValueError('replay or mutation')
    if plan['source_sha256']!=sources():raise ValueError('source drift')
    report=dict(plan_sha256=phash,run=s,fit=fitted,metrics=metrics,diagnostics=diagnostics,
                parameter_count=0 if model is None else len(selected),
                initial_sha256=None if initial is None else digest(initial.tobytes()),selected_sha256=whash,
                weight_change_norm=None if initial is None else float(np.linalg.norm(selected-initial)),
                prediction_sha256=rhash,replay_max_error=replay,panel_cpu_seconds=panel_times,
                phases_cpu_seconds=dict(prediction_and_seal=prediction_cpu,reference_scoring=reference_cpu,
                                        diagnostics_replay=time.process_time()-t),
                training_peak_rss_bytes=fit_peak,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                total_main_cpu=time.process_time()-started[0],total_main_wall=time.perf_counter()-started[1],
                environment=dict(python=sys.version,torch=torch.__version__,numpy=np.__version__,scipy=scipy.__version__,
                                 platform=platform.platform(),threads=torch.get_num_threads()),
                total_flops=None,energy_joules=None,gpu_peak_bytes=None,production_authorized=False)
    write(out/'REPORT.json',report)
    print(json.dumps(dict(run=s,primary=metrics['new_initial'],cpu=fitted['cpu_seconds'])),flush=True)


def sweep(out):
    out.mkdir(parents=True,exist_ok=False);root=Path(__file__).parent.resolve()
    plan=dict(schema='hepta.ndu.population.sweep.r4',runs=specs(),panels=panels(),source_sha256=sources(),
              primary='new_initial objective gap to independent optimum, matrix adjoint versus Adam, 8s, all seeds',
              source_parent='801c38a4811e9eacffa47f2f37d92e43ddfa76de',
              train_initial_cases=128,train_leaf_cases=8192,known_full_law=True,external_preregistration=False,
              scalar_family='u=alpha_(time,mode)*(x-h), six scalars not one global slope',
              special_case='Markov-preference conditional quadratic cost, not general nonlinear NDU',
              production_authorized=False)
    phash=write(out/'PLAN.json',plan);t=time.perf_counter();census=[]
    for spec in specs():
        name=name_for(spec);before=resource.getrusage(resource.RUSAGE_CHILDREN);now=time.perf_counter()
        cmd=[sys.executable,str(root/'experiment.py'),'trial','--out',str(out/name),'--spec',json.dumps(spec)]
        row=dict(name=name,run=spec)
        with open(out/(name+'.log'),'xb') as log:
            try:
                r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=150,check=False,
                                 env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'))
                row.update(status='completed' if r.returncode==0 else 'failed',returncode=r.returncode)
            except subprocess.TimeoutExpired:row.update(status='timeout',returncode=None)
            except OSError as e:row.update(status='launch_failed',error=str(e),returncode=None)
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(child_wall=time.perf_counter()-now,child_cpu=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
        if row['status']=='completed':
            try:
                data=(out/name/'REPORT.json').read_bytes();rr=json.loads(data)
                if rr['run']!=spec or rr['plan_sha256']!=digest((out/name/'PLAN.json').read_bytes()):raise ValueError('identity')
                row['report_sha256']=digest(data)
                row['new_initial_gap']=rr['metrics']['new_initial']['objective_gap']
            except (OSError,ValueError,KeyError) as e:row.update(status='evidence_failed',error=str(e))
        census.append(row);write(out/(name+'.completion.json'),row);print(json.dumps(row),flush=True)
    complete=dict(plan_sha256=phash,census=census,completed=sum(r['status']=='completed' for r in census),
                  failed=sum(r['status']!='completed' for r in census),wall=time.perf_counter()-t,
                  child_cpu=sum(r['child_cpu'] for r in census),production_authorized=False)
    write(out/'COMPLETE.json',complete)
    if complete['failed']:raise SystemExit('failures retained')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['sweep','trial'])
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--spec')
    args=parser.parse_args()
    if args.action=='sweep':sweep(args.out.resolve())
    else:trial(json.loads(args.spec),args.out.resolve())
