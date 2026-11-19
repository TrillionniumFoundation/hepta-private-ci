"""Frozen, bounded comparison of Erlang phases with a deterministic delay law."""

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import struct
import subprocess
import sys
import time


HERE = Path(__file__).parent
ROOT = HERE.parents[1]
THREADS = ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')


def write(path, report):
    temporary = path.with_suffix('.part.json')
    temporary.write_text(json.dumps(report, sort_keys=True, allow_nan=False)+'\n')
    temporary.replace(path)


def frozen():
    freeze = json.loads((HERE/'ERLANG_FREEZE.json').read_text())
    actual = {name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in freeze['files']}
    if actual != freeze['files']:
        raise ValueError('frozen source/configuration identity changed')
    return actual


def structure(law, stages, marks):
    """Independent adjacency/flux check before any candidate matrix exponential."""
    n, lam, nu = stages+1, float(law.rate.detach()), float(law.stage_rate.detach())
    expected = [[0.]*n for _ in range(n)]
    expected[0][0], expected[0][1] = -lam, lam
    for row in range(1,n):
        expected[row][row] = -nu
        expected[row][0 if row == stages else row+1] = nu
    actual = law.generator.detach().tolist()
    if actual != expected or any(math.fsum(row) != 0 for row in actual):
        raise ValueError('row generator differs from the independent active/phase cycle')
    if law.firing.detach().tolist() != [lam]+[0.]*stages or law.occupation_weight.tolist() != [1.]+[0.]*stages:
        raise ValueError('hit/occupation must observe active state only')
    initial_derivative = [[weight*x for x in actual[0]] for weight in marks]
    if initial_derivative != [[-weight*lam,weight*lam]+[0.]*(stages-1) for weight in marks]:
        raise ValueError('initial probability/signed flux directions')
    return {'adjacency_and_exact_row_sums':True,'nonnegative_off_diagonal':all(
                value >= 0 for i,row in enumerate(actual) for j,value in enumerate(row) if i != j),
            'hit_enters_first_phase':True,'last_phase_returns_to_active':True,
            'initial_channel_derivatives':initial_derivative,
            'generator_nonzero_entries':[[i,j,v] for i,row in enumerate(actual) for j,v in enumerate(row) if v],
            'generator_shape':[n,n], 'generator_fp64_sha256':hashlib.sha256(
                struct.pack('<'+'d'*(n*n),*(x for row in actual for x in row))).hexdigest()}


def child(config, target, stages, output, cpu_limit):
    limits = config['limits']
    resource.setrlimit(resource.RLIMIT_AS,(limits['address_space_bytes'],)*2)
    resource.setrlimit(resource.RLIMIT_CPU,(cpu_limit,cpu_limit+1))
    report = {'status':'started','phase':'imports','target':str(target),'stages':stages,
              'source_sha256_before':frozen(),'rlimit_as':list(resource.getrlimit(resource.RLIMIT_AS)),
              'rlimit_cpu':list(resource.getrlimit(resource.RLIMIT_CPU)),
              'thread_environment':{key:os.environ.get(key) for key in THREADS}}
    write(output,report)
    started, cpu = time.perf_counter(),time.process_time()
    try:
        import mpmath as mp
        import torch
        from .erlang_refractory import physics, initial, advance
        from .study_longtime import renewal_reference
        torch.set_num_threads(1); torch.set_num_interop_threads(1)
        report.update(torch=torch.__version__,mpmath=mp.__version__,python=sys.version,
                      platform=platform.platform(),torch_threads=torch.get_num_threads(),
                      torch_interop_threads=torch.get_num_interop_threads(),dtype='float64',
                      target_fraction=str(target),target_fp64_hex=float(target).hex(),
                      rate_fp64_hex=float(config['rate']).hex(),initial_mark_fp64_hex=[float(x).hex() for x in config['marks']],
                      delay_mean_fraction=config['delay_mean'],phase='structural_check')
        rate = torch.tensor(config['rate'],dtype=torch.float64,requires_grad=True)
        law = physics(rate,stages,Fraction(config['delay_mean']),config['discount'])
        report['structure'] = structure(law,stages,config['marks'])
        reference = renewal_reference(target,config['rate'],80)
        report['deterministic_reference_80_digits'] = dict(zip(
            ('values_probability','values_content','gradients_probability','gradients_content'),reference))
        with mp.workdps(80):
            report['erlang_release_before_half_mean'] = str(mp.gammainc(stages,0,mp.mpf(stages)/2)/mp.factorial(stages-1))
        report.update(phase='forward',quantity_order=['hit_count','active','refractory'],
                      physics_tensor_bytes_by_field=law.tensor_bytes(),physics_tensor_bytes=sum(law.tensor_bytes().values()))
        write(output,report)
        work = {'explicit_exponentials':0,'largest_matrix':0,'augmented_input_bytes':[]}
        start = initial(rate.new_tensor(config['marks']),stages)
        before,cp = time.perf_counter(),time.process_time()
        state = advance(start,law,target,work)
        waiting = state.phase.sum(1)
        values = torch.stack((state.hits,state.active[:,0]+state.upper,waiting),1)
        forward_wall,forward_cpu = time.perf_counter()-before,time.process_time()-cp
        report.update(phase='backward',values=values.detach().tolist(),forward_seconds=forward_wall,
                      forward_cpu_seconds=forward_cpu,work=work,state_tensor_bytes_by_field=state.tensor_bytes(),
                      state_tensor_bytes=sum(state.tensor_bytes().values()),
                      complete_state={name:getattr(state,name).detach().tolist() for name in state.tensor_bytes()},
                      probability_and_signed_balance_errors=(values[:,1]+values[:,2]-rate.new_tensor(config['marks'])).detach().tolist(),
                      probability_minimum=float(torch.cat((state.active[0],state.phase[0])).detach().min()),
                      signed_proportionality_max_error=float((torch.cat((state.active,state.phase),1)[1]-
                           config['marks'][1]*torch.cat((state.active,state.phase),1)[0]).detach().abs().max()),
                      peak_rss_after_forward_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        write(output,report)
        before,cp = time.perf_counter(),time.process_time()
        scalars = values.flatten().unbind()
        gradient = torch.stack([torch.autograd.grad(value,rate,retain_graph=i<len(scalars)-1)[0]
                                for i,value in enumerate(scalars)]).reshape(2,3)
        backward_wall,backward_cpu = time.perf_counter()-before,time.process_time()-cp
        expected = rate.new_tensor([[float(x) for x in row] for row in reference])
        report.update(status='completed',phase='complete',gradients=gradient.detach().tolist(),
                      value_signed_errors=(values.detach()-expected[:2]).tolist(),
                      gradient_signed_errors=(gradient.detach()-expected[2:]).tolist(),
                      maximum_value_absolute_error=float((values.detach()-expected[:2]).abs().max()),
                      maximum_gradient_absolute_error=float((gradient.detach()-expected[2:]).abs().max()),
                      backward_seconds=backward_wall,backward_cpu_seconds=backward_cpu,backward_scalar_calls=len(scalars),
                      all_values_and_gradients_finite=bool(torch.isfinite(values).all() and torch.isfinite(gradient).all()),
                      other_statistics_independently_verified=False,
                      original_complete_kernel_imported='qualification.hcsn_currentstate.differentiable' in sys.modules)
    except Exception as error:
        report.update(status='failed',error=repr(error))
    finally:
        report.update(child_measured_wall_seconds=time.perf_counter()-started,
                      child_measured_cpu_seconds=time.process_time()-cpu,
                      peak_rss_native_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      source_sha256_after=frozen())
        write(output,report)
    print(json.dumps({key:report[key] for key in ('status','phase','target','stages')}),flush=True)


def run(config, output):
    output.mkdir(parents=True,exist_ok=False)
    started,cpu = time.perf_counter(),time.process_time()
    initial_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    limits = config['limits']
    report = {'schema':'hcsn-erlang-state-compression-diagnostic-v1','config':config,
              'source_sha256_before':frozen(),'cases':[],'old_gates_changed':False,
              'scientific_scope':'Fixed-law Erlang approximation changes the refractory distribution; not exact deterministic compression.',
              'state_bytes_scope':'All original State tensor observables plus all phases, counting repeated references; excludes Python/autograd/allocator.',
              'physics_bytes_scope':'All declared Physics tensors, separately counted from dynamic state.',
              'forward_scope':'Two matrix exponentials and all state/query quantities with gradients; excludes imports, structure, reference, construction, serialization.',
              'backward_scope':'Six scalar autograd calls on the same graph; backend internal exponentials not counted.',
              'rss_scope':'Fresh child lifetime Linux KiB including imports, reference, forward and backward.',
              'archived_deterministic_cost_reference':{'path':'evidence/longtime-20261119/attempt001/REPORT.json',
                  'sha256':hashlib.sha256((HERE/'evidence/longtime-20261119/attempt001/REPORT.json').read_bytes()).hexdigest(),
                  'same_execution_batch':False}}
    write(output/'REPORT.json',report)
    for index,(target,stages) in enumerate((t,k) for t in config['times'] for k in config['stages']):
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        spent = time.process_time()-cpu+usage.ru_utime+usage.ru_stime-initial_usage.ru_utime-initial_usage.ru_stime
        remaining_cpu = limits['total_cpu_seconds']-spent-2
        remaining_wall = limits['total_wall_seconds']-(time.perf_counter()-started)-1
        cpu_limit = min(18,math.floor(remaining_cpu)-1)
        wall_limit = min(limits['case_wall_seconds'],remaining_wall)
        item = {'index':index,'target':target,'stages':stages,'cpu_soft_limit':cpu_limit,'full_process_wall_limit':wall_limit}
        if cpu_limit < 1 or wall_limit < 1:
            report['cases'].append({**item,'status':'censored_not_started','reason':'total campaign resource limit'})
            continue
        path = output/f'case-{index:03d}.json'
        env = {**os.environ,**{key:'1' for key in THREADS},'PYTHONHASHSEED':'0'}
        command = [sys.executable,'-m','qualification.hcsn_currentstate.study_erlang','--child',target,
                   '--stages',str(stages),'--cpu-limit',str(cpu_limit),'--output',str(path)]
        child_start = time.perf_counter()
        process = subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try:
            stdout,stderr = process.communicate(timeout=max(.001,wall_limit-(time.perf_counter()-child_start)))
        except subprocess.TimeoutExpired:
            process.kill(); stdout,stderr = process.communicate()
            item.update(status='censored_wall',reason='fresh-process wall limit')
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        item.update(full_process_wall_seconds=time.perf_counter()-child_start,
                    fresh_process_cpu_seconds=after.ru_utime+after.ru_stime-usage.ru_utime-usage.ru_stime,
                    returncode=process.returncode,stdout=stdout,stderr=stderr)
        if path.exists():
            receipt = json.loads(path.read_text())
            item.update(child_result=path.name,child_result_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),last_observed_phase=receipt['phase'])
            item.setdefault('status',receipt['status'] if process.returncode == 0 else 'censored_process_exit')
        else:
            item.setdefault('status','failed_no_child_receipt')
        report['cases'].append(item); write(output/'REPORT.json',report)
        print(json.dumps({key:item[key] for key in ('index','target','stages','status','full_process_wall_seconds')}),flush=True)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(wall_seconds=time.perf_counter()-started,total_cpu_seconds=time.process_time()-cpu+
                  usage.ru_utime+usage.ru_stime-initial_usage.ru_utime-initial_usage.ru_stime,
                  source_sha256_after=frozen())
    write(output/'REPORT.json',report)


if __name__ == '__main__':
    config = json.loads((HERE/'ERLANG_CONFIG.json').read_text())
    parser = argparse.ArgumentParser(); parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--child',choices=config['times']); parser.add_argument('--stages',type=int,choices=config['stages'])
    parser.add_argument('--cpu-limit',type=int); args = parser.parse_args()
    if args.child:
        child(config,Fraction(args.child),args.stages,args.output,args.cpu_limit)
    else:
        run(config,args.output.resolve())
