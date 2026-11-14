"""Isolated streaming CPU measurements and same-weight semigroup controls.

Formal measurements use 25 sequences and 200 timed all-row observation ticks.
One row is an independent eight-observation policy instance, NOT a
production Hepta Cell. A microbatch caps temporary workspaces, while the states
of every row remain resident simultaneously. The CTMC backend samples every
actual jump with the audited Gillespie implementation; it is not endpoint-only
sampling and does not substitute expected counts for real events.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import fields,is_dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rss():
    values={line.split(':',1)[0]:line.split(':',1)[1].strip()
            for line in Path('/proc/self/status').read_text().splitlines() if ':' in line}
    return {key:float(values[key].split()[0])*1024 for key in ['VmRSS','VmHWM']}


def setup(cpu):
    for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']:
        os.environ[name]='1'
    import torch
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    allowed=sorted(os.sched_getaffinity(0))
    chosen=cpu if cpu in allowed else allowed[-1]
    os.sched_setaffinity(0,{chosen})
    sys.path.insert(0,str(ROOT.parent))
    return torch


def state_items(state):
    if is_dataclass(state):
        return {field.name:getattr(state,field.name) for field in fields(state)}
    return state


def state_bytes(state):
    return sum(value.numel()*value.element_size() for value in state_items(state).values() if value is not None)


def state_slice(state,lo,hi):
    values={name:None if value is None else value[lo:hi] for name,value in state_items(state).items()}
    return type(state)(**values) if is_dataclass(state) else values


def copy_state_slice(target,source,lo,hi):
    for name,value in state_items(source).items():
        if value is not None:
            state_items(target)[name][lo:hi].copy_(value)


def get_policy(run_name,seed,group='results',preflight=False):
    import torch
    from rrsnn_v2.policy import Policy
    path=ROOT/group/run_name/f'seed_{seed}'/'model.pt'
    receipt=path.with_name('training.json')
    if path.exists() and receipt.exists():
        blob=torch.load(path,map_location='cpu',weights_only=True)
        model=Policy(blob['variant']);model.load_state_dict(blob['state_dict']);model.eval()
        return model,{'checkpoint':str(path),'checkpoint_sha256':sha(path),
                      'training_receipt_sha256':sha(receipt),'training_plan':blob['plan'],
                      'sampled_training':blob.get('sampled_training',False),
                      'trained_weights':True,'actual_variant':blob['variant']}
    if not preflight:
        raise FileNotFoundError(f'Completed checkpoint receipt absent: {path}')
    variant=run_name.removesuffix('_sampled').removesuffix('_cpu')
    torch.manual_seed(seed);model=Policy(variant);model.eval()
    return model,{'checkpoint':None,'checkpoint_sha256':None,'trained_weights':False,
                  'actual_variant':variant,'qualification':'temporary initialization for harness preflight only'}


def observed_inputs(batch,steps=8):
    import numpy as np
    import torch
    path=ROOT/'data'/'validation.npz'
    with np.load(path) as source:
        eligible=np.flatnonzero(source['lengths']==steps)
        if len(eligible)==0:
            raise RuntimeError('Refuse to benchmark padded frames as observed work')
        selected=eligible[np.arange(batch)%len(eligible)]
        x=torch.from_numpy(source['x'][selected,:steps].copy())
        dt=torch.from_numpy(source['dt'][selected,:steps].copy())
        mask=torch.from_numpy(source['event_mask'][selected,:steps].copy())
    assert bool(mask.all()) and bool((dt[:,0]==0).all())
    return x,dt,mask,{'validation_sha256':sha(path),'available_unique_templates':len(eligible),
                      'distinct_templates_used':min(batch,len(eligible)),
                      'selection':'validation rows of exactly eight real observations, cycled if necessary'}


class StreamingExecutor:
    def __init__(self,model,mode,x,dt,mask,microbatch):
        self.model=model;self.mode=mode;self.x=x;self.dt=dt;self.mask=mask
        self.batch,self.steps,_=x.shape
        self.microbatch=min(microbatch,self.batch) if microbatch else self.batch
        self.ranges=[(lo,min(lo+self.microbatch,self.batch)) for lo in range(0,self.batch,self.microbatch)]
        if mode=='ctmc' and not model.is_density:
            raise ValueError('Real CTMC backend requires a density model')

    def run(self,seed):
        import torch
        output=torch.empty(self.batch,self.steps,81,dtype=self.x.dtype)
        count_sum=0.
        numeric_bytes=0
        runtime_state_metadata=None
        tick_wall=[];tick_cpu=[];tick_counts=[]
        # Every row's state is constructed BEFORE processing any microbatch.
        if self.mode=='ctmc':
            from rrsnn_v2.audit.sampled_policy import SampledDensityRollout
            states=[SampledDensityRollout(self.model.encoder,hi-lo,backend='ctmc',
                       seed=seed+100003*index,record_spikes=False)
                    for index,(lo,hi) in enumerate(self.ranges)]
            metadata=[state.metadata() for state in states]
            numeric_bytes=sum(meta['persistent_numeric_buffer_bytes_total'] for meta in metadata)
            runtime_state_metadata=metadata[0]
        else:
            state=self.model.initial_state(self.batch,self.x.device,self.x.dtype)
            numeric_bytes=state_bytes(state)
        for t in range(self.steps):
            tick_start=time.perf_counter();tick_cpu_start=time.process_time()
            tick_count=0.
            for index,(lo,hi) in enumerate(self.ranges):
                if self.mode=='ctmc':
                    current=states[index].step(self.x[lo:hi,t],self.dt[lo:hi,t],self.mask[lo:hi,t])
                    logits=self.model.head(current['latent'])
                else:
                    part=state_slice(state,lo,hi)
                    updated,current=self.model.step(part,self.x[lo:hi,t],self.dt[lo:hi,t],self.mask[lo:hi,t])
                    copy_state_slice(state,updated,lo,hi)
                    logits=current['logits']
                output[lo:hi,t]=logits
                tick_count+=float(current['spikes'].sum())
            tick_cpu.append(time.process_time()-tick_cpu_start)
            tick_wall.append(time.perf_counter()-tick_start)
            tick_counts.append(tick_count);count_sum+=tick_count
        return output,{'count_sum':count_sum,'persistent_numeric_state_bytes':numeric_bytes,
                       'runtime_state_metadata':runtime_state_metadata,
                       'rng_objects':len(self.ranges) if self.mode=='ctmc' else 0,
                       'tick_wall_seconds':tick_wall,'tick_cpu_seconds':tick_cpu,'tick_counts':tick_counts}


def child(args):
    if not args.preflight and (args.repetitions!=25 or args.warmups!=5):
        raise ValueError('Frozen formal protocol requires 25 sequences, 200 ticks and 5 warmup sequences')
    torch=setup(args.cpu)
    import numpy as np
    baseline=rss()
    model,provenance=get_policy(args.run,args.seed,args.group,args.preflight)
    after_model=rss()
    x,dt,mask,input_metadata=observed_inputs(args.batch)
    # Matrix/exact-jump workspaces are bounded; inexpensive baselines can use
    # their full batch unless the caller explicitly requests a common microbatch.
    microbatch=args.microbatch
    if microbatch<0:
        microbatch=256 if args.mode in ('ctmc','density') else args.batch
    executor=StreamingExecutor(model,args.mode,x,dt,mask,microbatch)
    before_run=rss();load_before=os.getloadavg()
    wall=[];cpu=[];counts=[];checksums=[];state_info=None
    tick_wall=[];tick_cpu=[];tick_counts=[]
    with torch.inference_mode():
        for repetition in range(args.warmups):
            result,state_info=executor.run(args.seed+7000000+repetition)
            _=float(result.sum());del result
        for repetition in range(args.repetitions):
            t0=time.perf_counter();c0=time.process_time()
            result,state_info=executor.run(args.seed+8000000+repetition)
            checksum=float(result.sum())
            cpu.append(time.process_time()-c0);wall.append(time.perf_counter()-t0)
            counts.append(state_info['count_sum']);checksums.append(checksum);del result
            tick_wall.append(state_info['tick_wall_seconds']);tick_cpu.append(state_info['tick_cpu_seconds'])
            tick_counts.append(state_info['tick_counts'])
    after=rss()
    sequence_quantiles=np.percentile(np.asarray(wall)*1000,[50,95,99])
    tick_array=np.asarray(tick_wall)
    tick_quantiles=np.percentile(tick_array*1000,[50,95,99])
    positions=[]
    for index in range(8):
        values,multiplicity=np.unique(dt[:,index].numpy(),return_counts=True)
        quantiles=np.percentile(tick_array[:,index]*1000,[50,95,99])
        positions.append({'position':index,'latency_samples':args.repetitions,
            'latency_ms_p50':float(quantiles[0]),'latency_ms_p95':float(quantiles[1]),
            'latency_ms_p99_exploratory':float(quantiles[2]),
            'dt_histogram':[{'dt':float(value),'rows':int(number)} for value,number in zip(values,multiplicity)]})
    state_info={key:value for key,value in state_info.items() if key not in ['tick_wall_seconds','tick_cpu_seconds','tick_counts']}
    source_names=['benchmark.py','density_model.py','policy.py','causal_baselines.py',
                  'spiking_baselines.py','audit/sampled_policy.py']
    row={'schema':'rrsnn.v2.tick-and-sequence-cost.v2','formal':not args.preflight,
         'run_name':args.run,'mode':args.mode,'seed':args.seed,
         'rows':args.batch,'observations_per_row':8,'microbatch':executor.microbatch,
         'microbatches':len(executor.ranges),'all_row_states_resident_simultaneously':True,
         'parameters_shared':True,'row_states_independent':True,
         'scope':'scratch CPU policy instances, not production Hepta Cells',
         'primary_tick_cost_unit':'one observation event for all N rows including all microbatches and the complete 81-action readout',
         'secondary_sequence_cost_unit':'initialize all row states, stream eight real observations, retain logits and reduce checksums/counts',
         'initialization_in_sequence_timing':True,'initialization_in_tick_timing':False,'spike_timestamp_recording':False,
         'event_semantics':'actual sampled CTMC jumps' if args.mode=='ctmc' else 'expected finite-CTMC distribution' if model.is_density else model.metadata().get('forward','deterministic continuous-time RNN'),
         'warmup_sequences':args.warmups,'timed_sequences':args.repetitions,'timed_tick_samples':int(tick_array.size),
         'tick_latency_ms_raw_25_by_8':(tick_array*1000).tolist(),
         'tick_latency_ms_p50':float(tick_quantiles[0]),'tick_latency_ms_p95':float(tick_quantiles[1]),
         'tick_latency_ms_p99':float(tick_quantiles[2]),'tick_latency_ms_mean':float(tick_array.mean()*1000),
         'tick_process_cpu_seconds_raw':tick_cpu,'tick_process_cpu_seconds_mean':float(np.asarray(tick_cpu).mean()),
         'tick_positions_and_dt_mixture':positions,
         'whole_sequence_latency_ms_raw':[v*1000 for v in wall],
         'whole_sequence_latency_ms_p50':float(sequence_quantiles[0]),
         'whole_sequence_latency_ms_p95':float(sequence_quantiles[1]),
         'whole_sequence_latency_ms_p99_exploratory':float(sequence_quantiles[2]),
         'whole_sequence_latency_ms_mean':float(np.mean(wall)*1000),'process_cpu_seconds_raw':cpu,
         'process_cpu_seconds_mean':float(np.mean(cpu)),
         'eight_step_rows_per_second':float(args.batch/np.mean(wall)),
         'row_ticks_per_second':float(args.batch/tick_array.mean()),
         'internal_count_sum_raw':counts,'internal_count_by_tick':tick_counts,
         'internal_counts_per_tick_processing_second':float(np.sum(counts)/tick_array.sum()),
         'output_checksum_min':min(checksums),'output_checksum_max':max(checksums),
         'model_metadata':model.metadata(),'trainable_parameters_including_head':sum(p.numel() for p in model.parameters()),
         'shared_parameter_bytes':sum(p.numel()*p.element_size() for p in model.parameters()),
         'shared_constant_buffer_bytes':sum(b.numel()*b.element_size() for b in model.buffers()),
         **state_info,
         'persistent_numeric_state_bytes_per_row':state_info['persistent_numeric_state_bytes']/args.batch,
         'input_tensor_bytes':sum(t.numel()*t.element_size() for t in [x,dt,mask]),
         'retained_logit_output_bytes':args.batch*8*81*4,
         'temporary_allocation_accounting':'not attributed as a separate exact tensor sum; matrix/jump workspaces, Python/RNG objects and allocator are included in isolated-process RSS',
         'rss_after_imports_bytes':baseline,'rss_after_model_bytes':after_model,
         'rss_before_warmup_bytes':before_run,'rss_after_measurement_bytes':after,
         'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
         'rss_high_water_increase_from_pre_run_bytes':max(0,after['VmHWM']-before_run['VmRSS']),
         'checkpoint':provenance,'input_provenance':input_metadata,
         'source_sha256':{name:sha(ROOT/name) for name in source_names},
         'experiment_plan_sha256':sha(ROOT/'experiment_plan.json') if (ROOT/'experiment_plan.json').exists() else None,
         'benchmark_protocol_sha256':sha(ROOT/'benchmark_protocol.json'),
         'runtime':{'python':platform.python_version(),'torch':str(torch.__version__),
                    'platform':platform.platform(),'threads':torch.get_num_threads(),
                    'affinity':list(os.sched_getaffinity(0)),
                    'loadavg_before':list(load_before),'loadavg_after':list(os.getloadavg())},
         'limitations':['Pooled p99 uses 200 mixed-dt ticks from 25 sequences; adjacent ticks are correlated, not a production SLO.',
                        'Whole-sequence p99 has only 25 samples and is exploratory, distinct from tick p99.',
                        'Other host workloads can affect wall time despite CPU affinity separation.',
                        'Repeated input templates are not independent task samples.',
                        'No measured hardware energy, production Hepta routing or shared-Encoder costs.']}
    destination=Path(args.child_output);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(row,indent=2)+'\n')
    print(json.dumps({'run':args.run,'mode':args.mode,'rows':args.batch,
                     'tick_p50_ms':row['tick_latency_ms_p50'],'tick_p99_ms':row['tick_latency_ms_p99'],
                     'sequence_p50_ms':row['whole_sequence_latency_ms_p50'],'tick_samples':row['timed_tick_samples'],
                     'peak_rss_mib':row['process_peak_rss_bytes']/2**20,
                     'actual_state_bytes_per_row':row['persistent_numeric_state_bytes_per_row'],
                     'formal':not args.preflight}),flush=True)


def matrix(args):
    if not args.preflight and (args.repetitions!=25 or args.warmups!=5):
        raise ValueError('Frozen formal protocol requires 25 sequences, 200 ticks and 5 warmup sequences')
    destination=ROOT/('benchmark_preflight' if args.preflight else 'benchmark_results')
    destination.mkdir(exist_ok=True)
    missing=[]
    for specification in args.runs:
        run_name,mode=specification.split(':',1)
        checkpoint=ROOT/args.group/run_name/f'seed_{args.seed}'/'model.pt'
        if not args.preflight and not (checkpoint.exists() and checkpoint.with_name('training.json').exists()):
            missing.append(specification);continue
        for batch in args.sizes:
            output=destination/'runs'/f'{run_name}_{mode}_seed{args.seed}_b{batch}.json'
            if output.exists() and not args.rerun:
                old=json.loads(output.read_text())
                expected_hash=sha(checkpoint) if checkpoint.exists() else None
                if (old['checkpoint']['checkpoint_sha256']==expected_hash and old.get('timed_sequences',0)>=args.repetitions
                    and old['formal']==(not args.preflight)
                    and old['source_sha256']['benchmark.py']==sha(Path(__file__).resolve())):
                    continue
            command=[sys.executable,str(Path(__file__).resolve()),'--child','--run',run_name,
                     '--mode',mode,'--batch',str(batch),'--seed',str(args.seed),'--group',args.group,
                     '--repetitions',str(args.repetitions),'--warmups',str(args.warmups),
                     '--microbatch',str(args.microbatch),'--cpu',str(args.cpu),'--child-output',str(output)]
            if args.preflight:command.append('--preflight')
            subprocess.run(command,check=True)
            completed=[json.loads(p.read_text()) for p in sorted((destination/'runs').glob('*.json'))]
            (destination/'scaling_results.json').write_text(json.dumps({'schema':'rrsnn.v2.cost-matrix.v1',
                'formal':not args.preflight,'results':completed,'latest_requested_runs':args.runs,
                'latest_missing_runs':missing},indent=2)+'\n')
    paths=sorted((destination/'runs').glob('*.json')) if (destination/'runs').exists() else []
    result={'schema':'rrsnn.v2.cost-matrix.v1','formal':not args.preflight,
            'results':[json.loads(p.read_text()) for p in paths],
            'latest_requested_runs':args.runs,'latest_requested_sizes':args.sizes,
            'latest_missing_runs':missing,'latest_request_complete':not missing,
            'benchmark_sha256':sha(Path(__file__).resolve())}
    (destination/'scaling_results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'completed_rows':len(paths),'missing':missing,'output':str(destination/'scaling_results.json')}),flush=True)


def implementation_control(args):
    torch=setup(args.cpu)
    import numpy as np
    model,provenance=get_policy(args.control_run,args.seed,args.group,args.preflight)
    if not model.is_density:raise ValueError('Implementation control requires a density checkpoint')
    numeric=copy.deepcopy(model)
    numeric.encoder.ablations=numeric.encoder.ablations|frozenset({'numerical_kernel'})
    assert all(torch.equal(value,numeric.state_dict()[key]) for key,value in model.state_dict().items())
    result={'schema':'rrsnn.v2.same-weights-semigroup-control.v1','seed':args.seed,
            'run_name':args.control_run,'checkpoint':provenance,'weights_identical':True,'results':{},
            'scope':'full finite-CTMC semigroup plus expected count: matrix exponential versus truncated uniformization; same spatial grid, Erlang phases, observation remap and Lambert-W control; no continuum/PDE equivalence claim; Gillespie sampler does not use either propagation implementation'}
    with torch.inference_mode():
        for name in args.control_splits:
            with np.load(ROOT/'data'/f'{name}.npz') as source:
                n=min(args.limit,len(source['x']));length=int(source['lengths'][:n].max())
                x=torch.from_numpy(source['x'][:n,:length].copy());dt=torch.from_numpy(source['dt'][:n,:length].copy())
                mask=torch.from_numpy(source['event_mask'][:n,:length].copy())
                valid=torch.from_numpy(source['valid'][:n,:length].copy());decision=torch.from_numpy(source['decision'][:n,:length].copy())
            a=model(x,dt,event_mask=mask);b=numeric(x,dt,event_mask=mask)
            ap=torch.softmax(a['logits'].masked_fill(~valid,-1e9),-1);bp=torch.softmax(b['logits'].masked_fill(~valid,-1e9),-1)
            row={'episodes':n,'maximum_steps':length,'input_sha256':sha(ROOT/'data'/f'{name}.npz'),
                 'max_abs_logits_error':float((a['logits']-b['logits']).abs().max()),
                 'max_abs_state_distribution_error':float((a['probabilities']-b['probabilities']).abs().max()),
                 'max_abs_count_error':float((a['spikes']-b['spikes']).abs().max()),
                 'legal_argmax_disagreements':int(((ap.argmax(-1)!=bp.argmax(-1))&decision).sum()),
                 'decision_count':int(decision.sum())}
            if name!='validation':
                from rrsnn_v2.evaluate import evaluate,load_scenarios,load_oracles
                scenarios=load_scenarios(name)[:n]
                oracles=load_oracles(name,scenarios) if (ROOT/'data'/f'{name}_oracle.npz').exists() else None
                ae=evaluate(model,scenarios,oracles,mode='density',seed=args.seed+910000)
                be=evaluate(numeric,scenarios,oracles,mode='density',seed=args.seed+910000)
                delta=np.asarray(be['episode_utility'])-np.asarray(ae['episode_utility'])
                row['closed_loop']={'paired_utility_difference_mean':float(delta.mean()),
                    'paired_utility_difference_max_abs':float(np.abs(delta).max()),
                    'episodes_with_changed_utility':int((np.abs(delta)>1e-10).sum()),
                    'both_ledgers_conserved':bool(ae['ledger_conservation'] and be['ledger_conservation']),
                    'budget_violations_total':ae['budget_violations']+be['budget_violations'],
                    'analytic_episode_utility':ae['episode_utility'],'uniformization_episode_utility':be['episode_utility']}
            result['results'][name]=row
    destination=ROOT/('benchmark_preflight' if args.preflight else 'benchmark_results')/'implementation_controls'
    destination.mkdir(parents=True,exist_ok=True)
    path=destination/f'{args.control_run}_seed{args.seed}.json'
    result['source_sha256']={name:sha(ROOT/name) for name in ['benchmark.py','density_model.py','policy.py']}
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'implementation_control':str(path),'results':result['results']}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',nargs='+',default=['rr_density_sampled:ctmc','lif:standard',
                         'ctrnn:standard','ctrnn_matched:standard','ctrnn_matched_cpu:standard'])
    parser.add_argument('--sizes',nargs='+',type=int,default=[64,256,1024,4096])
    parser.add_argument('--seed',type=int,default=101);parser.add_argument('--group',default='results')
    parser.add_argument('--repetitions',type=int,default=25);parser.add_argument('--warmups',type=int,default=5)
    parser.add_argument('--microbatch',type=int,default=-1,help='-1:256 for CTMC/density, full batch for baselines; 0:all rows')
    parser.add_argument('--cpu',type=int,default=7)
    parser.add_argument('--preflight',action='store_true');parser.add_argument('--rerun',action='store_true')
    parser.add_argument('--child',action='store_true');parser.add_argument('--run');parser.add_argument('--mode')
    parser.add_argument('--batch',type=int);parser.add_argument('--child-output')
    parser.add_argument('--control',action='store_true');parser.add_argument('--control-run',default='rr_density_sampled')
    parser.add_argument('--control-splits',nargs='+',default=['validation']);parser.add_argument('--limit',type=int,default=64)
    args=parser.parse_args()
    if args.child:child(args)
    elif args.control:implementation_control(args)
    else:matrix(args)


if __name__=='__main__':
    main()
