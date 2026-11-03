"""Isolated one-CPU inference measurements of trained observation-grid proxies.

One cost unit is a batch of B independent 8-observation sequences plus the
complete 81-action readout. Parameters are shared; recurrent states are per row.
This is the current scratch CPU PyTorch runtime, NOT production Hepta Cells.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent


def rss_mib():
    status=Path('/proc/self/status').read_text()
    values={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status.splitlines() if ':' in line}
    return {key:float(values[key].split()[0])/1024 for key in ['VmRSS','VmHWM'] if key in values}


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child(variant,batch,seed,repetitions,warmups,path):
    for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:
        os.environ[name]='1'
    import numpy as np
    import torch
    sys.path.insert(0,str(ROOT.parent))
    from rrsnn_experiments.train_compare import Policy
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    affinity_before=sorted(os.sched_getaffinity(0))
    pinned_cpu=affinity_before[-1]
    os.sched_setaffinity(0,{pinned_cpu})
    process_baseline=rss_mib()
    checkpoint=ROOT/'results'/variant/f'seed_{seed}'/'model.pt'
    content=torch.load(checkpoint,map_location='cpu',weights_only=True)
    model=Policy(variant,mode='expected')
    model.load_state_dict(content['state_dict']);model.eval();model.set_mode('expected')
    after_model=rss_mib()
    archive=ROOT/'data'/'validation.npz'
    source=np.load(archive)
    source_rows=np.flatnonzero(source['lengths']==8)
    if not len(source_rows):
        raise RuntimeError('No fully observed 8-step validation sequence; refuse to benchmark padding as work')
    rows=source_rows[np.arange(batch)%len(source_rows)]
    x=torch.from_numpy(source['x'][rows,:8].copy())
    dt=torch.from_numpy(source['dt'][rows,:8].copy())
    before_run=rss_mib()
    before_load=os.getloadavg()
    latencies=[];cpu_seconds=[];checksums=[]
    with torch.inference_mode():
        for _ in range(warmups):
            output=model(x,dt)
            _=float(output['logits'].sum())
            del output
        for _ in range(repetitions):
            cpu0=time.process_time();start=time.perf_counter()
            output=model(x,dt)
            checksum=float(output['logits'].sum())
            elapsed=time.perf_counter()-start
            elapsed_cpu=time.process_time()-cpu0
            checksums.append(checksum);latencies.append(elapsed);cpu_seconds.append(elapsed_cpu)
            del output
    post=rss_mib()
    active=model.encoder.state_accounting(batch_size=batch)
    parameters=sum(p.numel() for p in model.parameters())
    p=np.percentile(np.array(latencies)*1000,[50,95,99])
    result={
      'schema':'rrsnn.trained-proxy-scaling.v1','variant':variant,'seed':seed,
      'batch_instances':batch,'observed_steps_per_instance':8,'action_outputs_per_step':81,
      'mode':'expected/probability training proxy',
      'scope':'current scratch CPU, complete model+head; not target-host or production-Cell acceptance',
      'cost_unit':'one batch of independent 8-step sequences plus complete action readout; states restart each repetition',
      'parameters_shared_across_rows':True,'per_row_state_independent':True,
      'unique_observed_templates_available':len(source_rows),'templates_used':min(batch,len(source_rows)),
      'input_row_selection':'validation rows with length exactly 8, cycled when B exceeds source pool',
      'warmup_repetitions':warmups,'timed_repetitions':repetitions,
      'latency_ms_raw':[v*1000 for v in latencies],
      'latency_ms_p50':float(p[0]),'latency_ms_p95':float(p[1]),'latency_ms_p99':float(p[2]),
      'latency_ms_mean':float(np.mean(latencies)*1000),
      'cpu_seconds_raw':cpu_seconds,'cpu_seconds_mean':float(np.mean(cpu_seconds)),
      'eight_step_sequences_per_second':float(batch/np.mean(latencies)),
      'state_observations_per_second':float(batch*8/np.mean(latencies)),
      'trainable_parameters_including_head':parameters,
      'shared_parameter_bytes':sum(p.numel()*p.element_size() for p in model.parameters()),
      'active_model_state_bytes_per_instance':active['active_state_bytes_per_sequence'],
      'active_model_state_bytes_batch':active['active_state_bytes_batch'],
      'input_tensor_bytes':x.numel()*x.element_size()+dt.numel()*dt.element_size(),
      'logit_output_bytes':batch*8*81*4,
      'temporary_bytes':'not analytically summed; reflected in isolated process VmHWM/ru_maxrss along with allocator and libraries',
      'rss_after_imports_mib':process_baseline,'rss_after_model_mib':after_model,
      'rss_before_warmup_mib':before_run,'rss_post_measurement_mib':post,
      'process_peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
      'rss_peak_minus_pre_run_current_mib':post['VmHWM']-before_run['VmRSS'],
      'output_checksum_min':min(checksums),'output_checksum_max':max(checksums),
      'checkpoint_sha256':fingerprint(checkpoint),'validation_arrays_sha256':fingerprint(archive),
      'source_sha256':{str(p.relative_to(ROOT)):fingerprint(p) for p in [
          ROOT/'models'/'sequence_models.py',ROOT/'models'/'budget_ctrnn.py',ROOT/'train_compare.py']},
      'runtime':{'python':platform.python_version(),'torch':str(torch.__version__),
          'platform':platform.platform(),'logical_cpu_count':os.cpu_count(),
          'torch_threads':torch.get_num_threads(),'torch_interop_threads':torch.get_num_interop_threads(),
          'cpu_affinity':[pinned_cpu],'loadavg_before':list(before_load),'loadavg_after':list(os.getloadavg())},
      'limitations':['Empirical p99 from 20 or more repeats, not a production tail SLO.',
          'Concurrent training/other host workloads may affect wall latency.',
          'Process RSS includes Python/PyTorch, checkpoint metadata, inputs, output buffers, temporaries and allocator.',
          'Repeated templates do not imply independent task samples; only independent model states.',
          'No hardware power/energy measurement, no Hepta integration, no shared-Encoder cost included.']}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'variant':variant,'batch':batch,'p50_ms':result['latency_ms_p50'],
                      'p99_ms':result['latency_ms_p99'],'peak_rss_mib':result['process_peak_rss_mib']}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variants',nargs='+',default=['lif','rr_full','ctrnn_budget'])
    p.add_argument('--sizes',nargs='+',type=int,default=[64,256,1024,4096])
    p.add_argument('--seed',type=int,default=101)
    p.add_argument('--repetitions',type=int,default=20)
    p.add_argument('--warmups',type=int,default=3)
    p.add_argument('--child-variant')
    p.add_argument('--child-batch',type=int)
    p.add_argument('--child-output',type=Path)
    args=p.parse_args()
    if args.repetitions<20:
        raise ValueError('At least 20 timed repeats are required by the benchmark protocol')
    if args.child_variant:
        child(args.child_variant,args.child_batch,args.seed,args.repetitions,args.warmups,args.child_output)
        return
    results=[];missing=[]
    for variant in args.variants:
        checkpoint=ROOT/'results'/variant/f'seed_{args.seed}'/'model.pt'
        receipt=checkpoint.with_name('result.json')
        if not checkpoint.exists() or not receipt.exists():
            missing.append({'variant':variant,'seed':args.seed,'reason':'completed checkpoint receipt absent'})
            continue
        for batch in args.sizes:
            destination=OUT/'scaling_runs'/f'{variant}_seed{args.seed}_b{batch}.json'
            command=[sys.executable,str(Path(__file__).resolve()),'--child-variant',variant,
                     '--child-batch',str(batch),'--child-output',str(destination),
                     '--seed',str(args.seed),'--repetitions',str(args.repetitions),
                     '--warmups',str(args.warmups)]
            env=os.environ.copy()
            for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:
                env[name]='1'
            subprocess.run(command,check=True,env=env)
            results.append(json.loads(destination.read_text()))
            (OUT/'scaling_results_partial.json').write_text(json.dumps({'results':results,'missing':missing},indent=2)+'\n')
    aggregate={'schema':'rrsnn.trained-proxy-scaling-matrix.v1','complete':len(results)==len(args.variants)*len(args.sizes),
               'results':results,'missing':missing,'requested_variants':args.variants,'requested_sizes':args.sizes,
               'benchmark_source_sha256':fingerprint(Path(__file__).resolve())}
    (OUT/'scaling_results.json').write_text(json.dumps(aggregate,indent=2)+'\n')
    print(json.dumps({'completed_rows':len(results),'missing':missing,'output':str(OUT/'scaling_results.json')}),flush=True)


if __name__=='__main__':
    main()
