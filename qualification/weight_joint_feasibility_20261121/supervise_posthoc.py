"""One-shot wrappers for explicitly requested post-result read-only audits."""
from pathlib import Path
import json
import os
import resource
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
name=sys.argv[1]
if name not in ('alias','closed_dual'):raise ValueError('unknown posthoc audit')
cpu,wallcap=(2,10) if name=='alias' else (10,20)
receipt=ROOT/f'POSTHOC_{name.upper()}_SUPERVISOR.json'
if receipt.exists() or (ROOT/f'posthoc_{name}').exists():raise ValueError('no audit retry')
if not (ROOT/'POSTHOC_AUDIT_PROTOCOL.json').exists():raise ValueError('posthoc audit seal required')


def limits():
    os.sched_setaffinity(0,{7});resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu))
    resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912));resource.setrlimit(resource.RLIMIT_CORE,(0,0))


env=os.environ.copy()
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[key]='1'
command=[sys.executable,str(ROOT/('alias_audit.py' if name=='alias' else 'closed_dual_addendum.py'))]
before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.perf_counter();parentcpu=time.process_time()
with (ROOT/f'posthoc_{name}.stdout.log').open('x') as stdout,(ROOT/f'posthoc_{name}.stderr.log').open('x') as stderr:
    process=subprocess.Popen(command,cwd=ROOT,env=env,preexec_fn=limits,start_new_session=True,stdout=stdout,stderr=stderr)
    timeout=False
    while process.poll() is None:
        if time.perf_counter()-start>wallcap:timeout=True;os.killpg(process.pid,signal.SIGKILL);break
        time.sleep(.05)
    code=process.wait()
after=resource.getrusage(resource.RUSAGE_CHILDREN)
result=dict(phase=name,posthoc=True,exit_code=code,wall_timeout=timeout,
    child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
    wall_seconds=time.perf_counter()-start,supervisor_CPU_seconds=time.process_time()-parentcpu,
    peak_RSS_bytes=after.ru_maxrss*1024,CPU_limit=cpu,wall_limit=wallcap,address_space_limit=536870912,
    automatic_retry=False,optimizer_calls=0)
with receipt.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(result),flush=True)
sys.exit(code if code>=0 else 128-code)
