"""Fixed83 then137, each in a fresh owned Python process; never retry either.

One dedicated systemd cgroup:1GiB,oneCPU,64tasks,360CPU/600activewall.
Per-parent180CPU/300wall. The outer630sec lifetime includes bounded cleanup,
not permission for further model work. Preparation/download costs are separate.
"""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
SEEDS = (83,137)
SLOTS = ('RERUN_PROGRAM_025','RERUN_PROGRAM_100','COPY_SOURCE_DELTA_025',
         'COPY_SOURCE_DELTA_100','BP_TASK_4','BP_TASK_16')
CAPS = dict(forwards=66, body_ticks=396, paired_queries=2228, backwards=34, optimizer_steps=32,
    analytic_solves=4, trace_linear_replays=12, scalar_inverse_targets=48, root_cells=196608,
    root_bisections=3840, root_interval_evaluations=196608, root_point_evaluations=397104,
    lagrange_iterations=512, proposal_directions=6)


def save(path, value):
    with path.open('x') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def cgroup():
    entries = [line.split(':',2) for line in Path('/proc/self/cgroup').read_text().splitlines()]
    unified = [row[2] for row in entries if row[:2]==['0','']]
    if len(unified)!=1 or unified[0]=='/' or '..' in Path(unified[0]).parts:
        raise ValueError('one dedicated cgroup-v2 service is required')
    root = (Path('/sys/fs/cgroup')/unified[0].lstrip('/')).resolve()
    if not root.is_relative_to('/sys/fs/cgroup'):
        raise ValueError('cgroup root escape')
    memory,tasks = ((root/key).read_text().strip() for key in ('memory.max','pids.max'))
    quota,period = (root/'cpu.max').read_text().split()
    if (memory=='max' or not 0<int(memory)<=1073741824 or tasks=='max' or not 0<int(tasks)<=64 or
            quota=='max' or not 0<int(quota)<=int(period)):
        raise ValueError('required dedicated memory/task/CPU limits absent or too loose')
    return root,dict(path=str(root),memory_max=int(memory),tasks_max=int(tasks),cpu_quota=int(quota),cpu_period=int(period))


def cpu_usage(root):
    return int(dict(line.split() for line in (root/'cpu.stat').read_text().splitlines())['usage_usec'])


def exclusive_supervisor(root):
    # Never send signals to a reaped PID or borrow another owner's cgroup.
    # Original pinned model/source uses no subprocesses. Any unexpected
    # remaining process/sub-cgroup makes further parent launch inadmissible.
    process_ids = sorted(int(x) for x in (root/'cgroup.procs').read_text().split())
    children = [path.name for path in root.iterdir() if path.is_dir()]
    if process_ids != [os.getpid()] or children:
        raise ValueError('dedicated cgroup is not exclusively the supervisor')
    return dict(process_ids=process_ids,child_cgroups=children)


def stop_owned_unreaped_child(pid):
    try:
        os.killpg(pid,signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:
            pass


def last_record(path):
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if len(raw)>4194304:
        raise ValueError('call ledger exceeds fixed read cap')
    incomplete = 0
    for line in reversed(raw.splitlines()):
        try:
            return dict(record=json.loads(line),incomplete_trailing_lines=incomplete)
        except (json.JSONDecodeError,UnicodeDecodeError):
            incomplete += 1
    return dict(record=None,incomplete_trailing_lines=incomplete)


def check_sources(binding,helper,core):
    for directory,group in ((HERE,'adapter_files'),(helper,'helper_files'),(core,'core_files')):
        for name,item in binding[group].items():
            raw = (directory/name).read_bytes()
            if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
                raise ValueError('frozen executable source identity differs: '+name)


def main():
    if len(sys.argv)!=6:
        raise SystemExit('supervise.py BINDING HELPER CORE PREPARED NEW_OUTPUT')
    binding_path,helper,core,prepared,output = (Path(value).resolve() for value in sys.argv[1:])
    output.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    binding = json.loads(binding_path.read_text())
    result = dict(schema='hepta.boundary-transfer-public-supervisor.v1',status='NOT_STARTED',
        parent_order=list(SEEDS),planned_candidate_slots_total=12,
        parents=[dict(seed=seed,status='NOT_STARTED',planned_slots=list(SLOTS),retry_permitted=False) for seed in SEEDS],
        processes_started=0,retries=0,global_caps=CAPS,cpu_seconds_limit=360,wall_seconds_limit=600,
        per_parent_cpu_seconds_limit=180,per_parent_wall_seconds_limit=300,
        actual_counts={name:0 for name in CAPS},counts_complete=True,unknown_parent_counts=[],
        counts_semantics='Known reported started-operation counts and returned internal-primitive counts; lower bounds if counts_complete is false.',
        new_heldout=False,native_owner=False,production=False,
        setup_cost_in_separate_receipt=True,conversational_planning_cost='UNAVAILABLE_NOT_MEASURED_ZERO')
    pid,waited,root,cpu_before = None,False,None,None
    failure = None
    try:
        if binding['status']!='FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW' or binding['parent_order']!=list(SEEDS):
            raise ValueError('unreviewed binding or changed parent order')
        check_sources(binding,helper,core)
        receipt = json.loads((prepared/'PREPARED.json').read_text())
        if receipt['binding_sha256'] != hashlib.sha256(binding_path.read_bytes()).hexdigest():
            raise ValueError('prepared inputs use a different binding')
        root,limits = cgroup()
        custody = exclusive_supervisor(root)
        available = sorted(os.sched_getaffinity(0))
        if not available:
            raise ValueError('no allowed CPU')
        os.sched_setaffinity(0,{available[0]})
        cpu_before = cpu_usage(root)
        result.update(status='STARTED',cgroup=limits,cpu_affinity=[available[0]],initial_custody=custody)
        save(output/'START.json',result)
        for index,seed in enumerate(SEEDS):
            if time.monotonic()-started>=600 or (cpu_usage(root)-cpu_before)/1e6>=360:
                raise RuntimeError('global budget exhausted before next predeclared parent')
            check_sources(binding,helper,core)
            exclusive_supervisor(root)
            parent_start,parent_cpu = time.monotonic(),cpu_usage(root)
            stdout = (output/('parent%d.stdout'%seed)).open('xb')
            stderr = (output/('parent%d.stderr'%seed)).open('xb')
            waited = False
            pid = os.fork()
            if pid==0:
                try:
                    os.setsid()
                    resource.setrlimit(resource.RLIMIT_CPU,(180,181))
                    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
                    os.dup2(stdout.fileno(),1)
                    os.dup2(stderr.fileno(),2)
                    env = dict(os.environ)
                    env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',
                               CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1')
                    args = [sys.executable,str(HERE/'parent_runner.py'),str(binding_path),str(helper),str(core),
                            str(prepared/('parent%d'%seed)),str(seed),str(output/('parent%d'%seed))]
                    os.execve(sys.executable,args,env)
                except BaseException:
                    os._exit(127)
            item = result['parents'][index]
            item.update(status='STARTED',child_pid=pid,fresh_process=True,planned_slots=list(SLOTS))
            result['processes_started'] += 1
            save(output/('parent%d_STARTED.json'%seed),item)
            stdout.close()
            stderr.close()
            stopped = None
            while True:
                ended,status,usage = os.wait4(pid,os.WNOHANG)
                if ended:
                    waited=True
                    break
                global_wall,parent_wall = time.monotonic()-started,time.monotonic()-parent_start
                current_cpu = cpu_usage(root)
                global_cpu,parent_consumed = (current_cpu-cpu_before)/1e6,(current_cpu-parent_cpu)/1e6
                if stopped is None and (global_wall>=600 or global_cpu>=360 or parent_wall>=300 or parent_consumed>=180):
                    stopped = ('GLOBAL_WALL' if global_wall>=600 else 'GLOBAL_CPU' if global_cpu>=360 else
                               'PARENT_WALL' if parent_wall>=300 else 'PARENT_CPU')
                    stop_owned_unreaped_child(pid)
                time.sleep(.2)
            code = os.waitstatus_to_exitcode(status)
            item.update(child_exit_code=code,stop_reason=stopped,wait4_reaped=True,
                user_seconds=usage.ru_utime,system_seconds=usage.ru_stime,max_rss_kib=usage.ru_maxrss,
                cgroup_cpu_seconds=(cpu_usage(root)-parent_cpu)/1e6,wall_seconds=time.monotonic()-parent_start,
                last_complete_call_record=last_record(output/('parent%d'%seed)/'calls.jsonl'))
            pid=None
            item['post_parent_custody']=exclusive_supervisor(root)
            path = output/('parent%d'%seed)/'RESULT.json'
            if path.is_file():
                if path.stat().st_size>2097152:
                    raise ValueError('parent result exceeds fixed read cap')
                raw = path.read_bytes()
                experiment = json.loads(raw)
                item.update(status=experiment['status'],result_sha256=hashlib.sha256(raw).hexdigest())
                counts = experiment['counts']
                if counts is None:
                    counts = {key:0 for key in CAPS}
                    result['counts_complete']=False
                    result['unknown_parent_counts'].append(dict(seed=seed,reason='NO_TYPED_CALL_LEDGER',unknown_not_zero=True))
                rerun=experiment.get('rerun_status',{})
                if (experiment['status']!='PARENT_COMPLETED' or rerun.get('fit_internal_iteration_counts_complete') is False or
                        rerun.get('root_internal_counts_complete') is False):
                    result['counts_complete']=False
                    result['unknown_parent_counts'].append(dict(seed=seed,reason='ABORTED_OR_UNRETURNED_INTERNAL_OPERATIONS',unknown_not_zero=True))
                if set(counts)!=set(CAPS) or any(type(v) is not int or v<0 for v in counts.values()):
                    raise ValueError('parent typed counters differ')
                for name,value in counts.items():
                    result['actual_counts'][name] += value
                    if result['actual_counts'][name]>CAPS[name]:
                        raise ValueError('aggregate operation budget exceeded')
                if ((code==0)!=(experiment['status']=='PARENT_COMPLETED') or
                        experiment.get('integrity_errors') or experiment.get('failed_phase')=='SOURCE_QUALIFICATION'):
                    item['global_stop_required']=True
            else:
                item.update(status='UNKNOWN_PARTIAL_EXECUTION',global_stop_required=True)
                result['counts_complete']=False
                witness=item['last_complete_call_record']
                if witness and witness['record']:
                    item['partial_count_witness']=witness['record'].get('counts')
                    counts=item['partial_count_witness']
                    if not isinstance(counts,dict) or set(counts)!=set(CAPS) or any(type(v) is not int or v<0 for v in counts.values()):
                        raise ValueError('partial operation witness counter schema differs')
                    for name,value in counts.items():
                        result['actual_counts'][name]+=value
                        if result['actual_counts'][name]>CAPS[name]:
                            raise ValueError('aggregate known partial count exceeds frozen cap')
                result['unknown_parent_counts'].append(dict(seed=seed,reason='NO_FINAL_PARENT_RESULT',
                    partial_lower_bound=item.get('partial_count_witness'),unknown_not_zero=True))
            save(output/('parent%d_COMPLETED_OR_FAILED.json'%seed),item)
            if item.get('global_stop_required') or stopped and stopped.startswith('GLOBAL_'):
                raise RuntimeError('unknown execution or global integrity/resource failure; no further parent launch')
            check_sources(binding,helper,core)
        result['status']='COMPLETED_FIXED_PARENT_SEQUENCE'
        result['all_planned_slots_retained_in_denominator']=True
    except BaseException as error:
        failure=error
        result.update(status='ABORTED_FIXED_SEQUENCE',error=repr(error),planned_denominators_unchanged=True)
        if pid is not None and not waited:
            stop_owned_unreaped_child(pid)
            _,status,usage=os.wait4(pid,0)
            result['cleanup_child_exit_code']=os.waitstatus_to_exitcode(status)
            result['cleanup_wait4_reaped']=True
    finally:
        result['wall_seconds']=time.monotonic()-started
        for item in result['parents']:
            if item['status']=='STARTED':
                result['counts_complete']=False
                result['unknown_parent_counts'].append(dict(seed=item['seed'],reason='OUTER_FAILURE_DURING_OWNED_CHILD',
                    unknown_not_zero=True,static_caps_retained=True))
        if root is not None:
            result['aggregate_cgroup_cpu_seconds']=None if cpu_before is None else (cpu_usage(root)-cpu_before)/1e6
            result['cgroup_memory_events']=(root/'memory.events').read_text().splitlines()
            try:
                result['final_custody']=exclusive_supervisor(root)
            except BaseException as error:
                result['final_custody_unknown']=repr(error)
                failure=failure or error
                result['status']='ABORTED_FIXED_SEQUENCE'
        save(output/'OUTER_RESULT.json',result)
    if failure is not None:
        raise failure


if __name__=='__main__':
    main()
