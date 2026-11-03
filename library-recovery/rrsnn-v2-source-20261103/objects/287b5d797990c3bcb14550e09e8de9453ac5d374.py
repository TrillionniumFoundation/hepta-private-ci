"""Exploratory, isolated-process scaling measurements for the R1 runtime.

The three event engines are exact-event deterministic LIF, Brownian first-hit
sampling by its inverse-Gaussian/Levy law, and Brownian first-hit sampling by
numerically inverting the same analytic CDF. The last is a numerical sampling
implementation comparison, NOT an ablation removing the analytic kernel.
An independent PDE local-operator microbenchmark is reported separately.

64/256/1024/4096 refer to reference neurons, not actual Hepta Cells. Sparse
active work has exactly eight active lanes at every scale; this controls total
events while exposing all-neuron propagation cost. Tail quantiles from five
repetitions are descriptive and exploratory, not validated tail-latency SLAs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

import numpy as np
from scipy.optimize import brentq

try:
    from . import event_runtime as er
    from .validate_runtime import forward_pde_switch
except ImportError:
    import event_runtime as er
    from validate_runtime import forward_pde_switch


SEEDS=[101,211,307,401,503,607,709,809,907,1009,1103,1201,1301,1409,1511]


def peak_rss_mib():
    raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform.startswith('linux'):
        return raw/1024.0,'ru_maxrss KiB on Linux, divided by 1024'
    if sys.platform=='darwin':
        return raw/(1024.0**2),'ru_maxrss bytes on macOS, divided by 1024^2'
    raise RuntimeError('Unknown ru_maxrss platform unit; refusing an ungrounded memory claim')


def current_rss_mib():
    if sys.platform.startswith('linux'):
        resident_pages=int(Path('/proc/self/statm').read_text().split()[1])
        return resident_pages*os.sysconf('SC_PAGE_SIZE')/(1024.0**2)
    return None


def install_inverse_cdf_sampler(window,stats):
    """Numerical inversion is exact to root tolerance, censored after window.

    This window is >= the remaining simulation horizon at every global event;
    censoring later draws cannot change any event in the observed simulation.
    """
    def sampler(rng,x,mu,sigma):
        stats['draws']+=1
        if x<=0:
            return 0.0
        if sigma==0:
            return -x/mu if mu<0 else math.inf
        u=float(rng.random())
        def cdf(t):
            stats['cdf_evaluations']+=1
            return er.first_hit_cdf(x,t,mu,sigma)
        if u>=cdf(window):
            stats['censored_after_window']+=1
            return math.inf
        stats['root_solves']+=1
        return float(brentq(lambda t:cdf(t)-u,0.0,window,xtol=1e-11,rtol=1e-12))
    er.sample_first_hit=sampler


def build_workload(size,load,backend):
    active=8 if load=='sparse_active' else 0
    neurons=[]
    for i in range(size):
        active_lane=i<active
        neurons.append(er.Neuron(drift=1.5 if active_lane else .05,
            sigma=0 if backend=='exact_lif' else (.2 if active_lane else .05),
            refractory=.05,model='lif' if backend=='exact_lif' else 'brownian',
            tau=.5))
    inputs=[]
    for t,multiplier in [(.6,1.2),(1.4,.8)]:
        for i in range(size):
            inputs.append(er.InputEvent(t,i,drift=neurons[i].drift*multiplier,
                                        tag='common_piecewise_drive'))
    return neurons,inputs,{'horizon':2.0,'components':size,'active_components':active,
        'quiet_components':size-active,'connections':0,'global_input_update_times':[.6,1.4],
        'refractory':.05,'threshold':1.,'reset':0.,
        'active_drive':1.5,'quiet_drive':.05,
        'brownian_active_sigma':.2,'brownian_quiet_sigma':.05,'lif_tau':.5,
        'semantic_caution':'Identical scheduled drive values; LIF drive is equilibrium offset and Brownian drive is evidence drift. No cross-model speedup ratio is valid.'}


def worker(size,load,backend,repeats):
    inverse_stats={'draws':0,'cdf_evaluations':0,'censored_after_window':0,'root_solves':0}
    if backend=='brownian_inverse_cdf':
        install_inverse_cdf_sampler(2.,inverse_stats)
    neurons,inputs,spec=build_workload(size,load,backend)
    rss_before=current_rss_mib()
    start=time.perf_counter()
    er.simulate(neurons,2.,inputs=inputs,seed=17,record_trace=False)
    warmup=time.perf_counter()-start
    rows=[]
    for seed in SEEDS[:repeats]:
        before=dict(inverse_stats)
        t0=time.perf_counter()
        result=er.simulate(neurons,2.,inputs=inputs,seed=seed,record_trace=False)
        seconds=time.perf_counter()-t0
        row={'seed':seed,'wall_seconds':seconds,'spikes':len(result['spikes']),
             'global_events':result['stats']['global_events'],
             'survival_updates':result['stats']['survival_updates'],
             'first_hit_draws':result['stats']['first_hit_draws'],
             'inverse_cdf':{key:inverse_stats[key]-before[key] for key in inverse_stats}}
        rows.append(row)
    times=np.array([r['wall_seconds'] for r in rows])
    peak,unit=peak_rss_mib()
    return {'status':'completed','backend':backend,'load':load,'components':size,
        'workload':spec,'repetitions':repeats,'warmup_seconds_excluded':warmup,
        'raw':rows,'latency_seconds':{'p50':float(np.quantile(times,.5)),
            'p95':float(np.quantile(times,.95)),'p99':float(np.quantile(times,.99)),
            'min':float(times.min()),'max':float(times.max())},
        'whole_run_component_throughput_per_second':float(size/np.median(times)),
        'throughput_definition':'Reference components simulated for a fixed two-unit horizon divided by total wall time; not biological firing rate and not Hepta task throughput.',
        'peak_process_rss_mib':peak,'rss_measurement':unit,
        'rss_before_simulation_mib':rss_before,'rss_after_simulation_mib':current_rss_mib(),
        'tail_quantiles':'Exploratory empirical linear-interpolation quantiles from a small sample; not production p95/p99 claims.'}


def local_pde_benchmark(repeats):
    """True numerical PDE local-operator alternative, separate from networks."""
    x,sigma,t1,t2,mu1,mu2=1.,.8,.5,.5,-.7,-.7
    reference=er.first_hit_cdf(x,t1+t2,mu1,sigma)
    # Vector batches keep observable output (a checksum), avoiding optimizer
    # removal while timing the real scalar special-function implementation.
    analytic=[]
    for _ in range(repeats):
        start=time.perf_counter(); checksum=0.
        for __ in range(10000):
            checksum+=er.first_hit_cdf(x,1.,mu1,sigma)
        elapsed=time.perf_counter()-start
        analytic.append({'batch_size':10000,'wall_seconds':elapsed,
                         'seconds_per_call':elapsed/10000,'checksum':checksum})
    numeric=[]
    for _ in range(repeats):
        start=time.perf_counter()
        value=forward_pde_switch(x,sigma,t1,t2,mu1,mu2,0,dx=.005)
        elapsed=time.perf_counter()-start
        numeric.append({'wall_seconds':elapsed,'value':value,'absolute_error':abs(value-reference)})
    peak,unit=peak_rss_mib()
    return {'scope':'Scalar constant-drift first-passage probability; numerical PDE solve includes its matrix/grid setup, not cached. Not a full numerical event network.',
        'analytic_probability':reference,'analytic_raw':analytic,'pde_raw':numeric,
        'pde_grid':{'dx':.005,'xmax':8,'time_step_max':.0005},
        'peak_process_rss_mib':peak,'rss_measurement':unit,
        'max_pde_error':max(x['absolute_error'] for x in numeric),
        'median_analytic_seconds_per_probability':float(np.median([x['seconds_per_call'] for x in analytic])),
        'median_pde_seconds_per_probability':float(np.median([x['wall_seconds'] for x in numeric])),
        'reuse_caution':'PDE solves many spatial states jointly and can be cached; these uncached scalar-query times do not establish end-to-end network speedup.'}


def main(output,repeats=5):
    if not 5<=repeats<=15:
        raise ValueError('Use 5..15 repetitions')
    output.mkdir(parents=True,exist_ok=True)
    rows=[]
    environment=os.environ.copy()
    environment['OPENBLAS_NUM_THREADS']='1'
    environment['OMP_NUM_THREADS']='1'
    start=time.perf_counter()
    for size in [64,256,1024,4096]:
        for load in ['quiet','sparse_active']:
            for backend in ['exact_lif','brownian_direct','brownian_inverse_cdf']:
                cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--size',str(size),
                     '--load',load,'--backend',backend,'--repeats',str(repeats)]
                try:
                    child=subprocess.run(cmd,capture_output=True,text=True,env=environment,timeout=180)
                    if child.returncode:
                        row={'status':'failed','components':size,'load':load,'backend':backend,
                             'stderr':child.stderr[-4000:]}
                    else:
                        row=json.loads(child.stdout)
                except subprocess.TimeoutExpired:
                    row={'status':'timeout','components':size,'load':load,'backend':backend,
                         'timeout_seconds':180,'scope':'Includes imports, warmup and repetitions'}
                rows.append(row)
                print(json.dumps({'components':size,'load':load,'backend':backend,
                    'status':row['status'],'p50':row.get('latency_seconds',{}).get('p50'),
                    'rss_mib':row.get('peak_process_rss_mib')}) ,flush=True)
                (output/'runtime_benchmark_partial.json').write_text(json.dumps(rows,indent=2)+'\n')
    cmd=[sys.executable,str(Path(__file__).resolve()),'--pde-worker','--repeats',str(repeats)]
    child=subprocess.run(cmd,capture_output=True,text=True,env=environment,timeout=180)
    if child.returncode:
        pde={'status':'failed','stderr':child.stderr[-4000:]}
    else:
        pde={'status':'completed',**json.loads(child.stdout)}
    result={'scope':'Current scratch reference-engine measurements; no real Hepta Cell, model, device, energy, or production integration claim.',
        'date':'2026-10-29','all_cases_completed':all(r['status']=='completed' for r in rows),
        'environment':{'python':platform.python_version(),'platform':platform.platform(),
            'logical_cpu_count':os.cpu_count(),'blas_threads':1,'omp_threads':1,
            'isolation':'One sequential subprocess per model/scale/workload; host is shared and not dedicated.'},
        'cases':rows,'numerical_pde_operator':pde,'wall_seconds_total':time.perf_counter()-start,
        'limitations':['Only eight active components per active case; active fraction decreases with scale.',
            'Exact LIF and Brownian dynamics are different models; their runtimes cannot establish equal-quality acceleration.',
            'Inverse-CDF runtime uses the analytic CDF and is a numerical-sampling comparison, not an analytic-kernel-removal ablation.',
            'Numerical PDE microbenchmark is a local probability operator; it is not a complete numerical first-passage network.',
            'P95/P99 from five to fifteen repetitions are exploratory and have inadequate support for reliable tail inference.',
            'ru_maxrss is process high-water RSS including imports and warmup; it is not per-neuron storage or an allocator-only footprint.',
            'No hardware energy measurement; do not infer energy from spike count or CPU wall time.']}
    (output/'runtime_benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'saved':str(output/'runtime_benchmark.json'),
                      'completed':result['all_cases_completed'],'wall_seconds_total':result['wall_seconds_total']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'results')
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--pde-worker',action='store_true')
    parser.add_argument('--size',type=int,default=64)
    parser.add_argument('--load',default='quiet')
    parser.add_argument('--backend',default='brownian_direct')
    args=parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.size,args.load,args.backend,args.repeats)))
    elif args.pde_worker:
        print(json.dumps(local_pde_benchmark(args.repeats)))
    else:
        main(args.output,args.repeats)
