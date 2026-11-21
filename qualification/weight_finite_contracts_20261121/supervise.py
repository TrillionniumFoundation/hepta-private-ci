"""Single audit+reader within a shared finite resource budget; no retries."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def read(path):return json.loads(Path(path).read_bytes())


def write(path,value):
    with Path(path).open('x') as f:json.dump(value,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')


def main():
    # A 60s inherited hard ceiling lets the two children lower their own
    # ceilings to 40s and 15s. Parent software aborts at 4s; after children exit
    # its hard ceiling is lowered to 5s. No child may raise a parent's hard cap.
    resource.setrlimit(resource.RLIMIT_CPU,(4,60))
    os.sched_setaffinity(0,{8})
    limits=read(ROOT/'PROTOCOL_FROZEN.json')['resources']
    out=ROOT/'attempt001';out.mkdir(exist_ok=False)
    started=time.perf_counter();phases=[];failed=False
    env=os.environ.copy()
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        env[key]='1'
    def run(label,filename,cpu):
        code=('import os,resource,runpy;'
              'os.sched_setaffinity(0,{8});'
              f'resource.setrlimit(resource.RLIMIT_CPU,({cpu-1},{cpu}));'
              'resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912));'
              'resource.setrlimit(resource.RLIMIT_CORE,(0,0));'
              f'runpy.run_path({str(ROOT/filename)!r},run_name="__main__")')
        before=resource.getrusage(resource.RUSAGE_CHILDREN);wall=time.perf_counter()
        # Parent CPU is monitored at each polling boundary as well as its
        # kernel soft limit. Each child sets limits before importing NumPy.
        with (out/(label+'.stdout.log')).open('x') as stdout,(out/(label+'.stderr.log')).open('x') as stderr:
            proc=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
            timeout=False
            while proc.poll() is None:
                if time.perf_counter()-started>=120 or time.process_time()>=4:
                    timeout=True;os.killpg(proc.pid,signal.SIGKILL);break
                time.sleep(.05)
            exitcode=proc.wait()
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        result=dict(phase=label,exit_code=exitcode,timeout=timeout,wall_seconds=time.perf_counter()-wall,
                    child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                    child_peak_RSS_bytes=after.ru_maxrss*1024,CPU_hard_seconds=cpu,
                    address_space_bytes=536870912,affinity=[8],numeric_threads=1,automatic_retry=False)
        write(out/(label.upper()+'_SUPERVISOR.json'),result);phases.append(result)
        return exitcode==0 and not timeout
    if run('audit','audit_receipts.py',40):
        failed=not run('reader','verify_records.py',15)
    else:failed=True
    resource.setrlimit(resource.RLIMIT_CPU,(4,5))
    total_children=sum(p['child_CPU_seconds'] for p in phases)
    own=time.process_time();within=total_children+own<=60 and time.perf_counter()-started<=120
    status='PASS' if not failed and within else 'STOP_FAILED_OR_BUDGET'
    result=dict(schema='hepta.finite-contract-resource-receipt.v1',status=status,
        created_at_UTC=datetime.datetime.now(datetime.timezone.utc).isoformat(),phases=phases,
        measured_child_CPU_seconds=total_children,supervisor_CPU_seconds_until_receipt=own,
        measured_total_CPU_seconds_until_receipt=total_children+own,wall_seconds=time.perf_counter()-started,
        hard_budget_CPU_seconds=60,hard_budget_wall_seconds=120,budget_checked=within,
        supervisor_final_receipt_emission_CPU_seconds=None,
        excluded_costs=['protocol/code authoring','freeze metadata/source hashing','tool-service latency','external native/scientific execution or compilation','final supervisor receipt-emission tail'],
        excluded_costs_are_not_zero=True,automatic_retry=False,
        full_history_serving_reuse_benefit=0,resource_choice='KEEP_EXISTING_PATHS_AND_STOP_NEW_FULL_HISTORY_CACHE',
        general_NDU='KEEP_ORIGINAL_AND_STOP')
    write(ROOT/'TOTAL_RESOURCE_RECEIPT.json',result)
    ndu=dict(schema='hepta.finite-reuse-ndu.v1',queue_sha256=read(ROOT/'PROTOCOL_FROZEN.json')['queue_sha256'],
        decision_locked_before_cost_read=read(ROOT/'PROTOCOL_FROZEN.json')['prospective_CPU_resource_choice'],
        finite_CPU_choice='KEEP_EXISTING_PATHS_AND_STOP_NEW_FULL_HISTORY_CACHE',general_NDU='KEEP_ORIGINAL_AND_STOP',
        audit_status=status,zero_incremental_computations_avoided=True,
        measured_new_qualification_CPU_seconds=total_children+own,
        finite_workload_net_saving_at_most_seconds=-(total_children+own),
        inequality_scope='observed new qualification expense minus zero avoided computations; excludes unmeasured positive overhead',
        missing_future_contract=read(ROOT/'PROTOCOL_FROZEN.json')['missing_future_contract'],
        production_adoption=False,model_quality_improvement_claim=False,
        baseline_existing_operator_hits_not_counted_as_new_saving=True,
        break_even_calls=None,break_even_reason='no committed repeated full-history demand or measured incremental saving per such call')
    write(out/'NDU_TRACE.json',ndu)
    print(json.dumps(dict(status=status,CPU_seconds=total_children+own,wall_seconds=result['wall_seconds'],resource_choice=ndu['finite_CPU_choice'])))
    return 0 if status=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
