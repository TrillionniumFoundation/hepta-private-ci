"""One-shot total5CPU boundary, including the permitted original H recovery."""
from pathlib import Path
import json,os,resource,signal,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
receipt=ROOT/'CONTINUATION_ONLY_SUPERVISOR.json'
assert not receipt.exists() and not (ROOT/'posthoc_continuation_only').exists()
assert (ROOT/'CONTINUATION_ONLY_PROTOCOL.json').exists()
def limits():
    os.sched_setaffinity(0,{7});resource.setrlimit(resource.RLIMIT_CPU,(5,5))
    resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
env=os.environ.copy()
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):env[k]='1'
start=time.perf_counter();pc=time.process_time();before=resource.getrusage(resource.RUSAGE_CHILDREN)
with (ROOT/'continuation_only.stdout.log').open('x') as o,(ROOT/'continuation_only.stderr.log').open('x') as e:
    p=subprocess.Popen([sys.executable,str(ROOT/'continuation_only.py')],cwd=ROOT,env=env,stdout=o,stderr=e,preexec_fn=limits,start_new_session=True)
    timeout=False
    while p.poll() is None:
        if time.perf_counter()-start>10:timeout=True;os.killpg(p.pid,signal.SIGKILL);break
        time.sleep(.05)
    code=p.wait()
after=resource.getrusage(resource.RUSAGE_CHILDREN)
r=dict(exit_code=code,wall_timeout=timeout,wall_seconds=time.perf_counter()-start,
    child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
    supervisor_CPU_seconds=time.process_time()-pc,peak_RSS_bytes=after.ru_maxrss*1024,
    CPU_hard_seconds=5,wall_hard_seconds=10,address_space_bytes=536870912,
    original_H_recovery_charged_inside_cap=True,no_retry=True)
with receipt.open('x') as f:json.dump(r,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(r));sys.exit(code if code>=0 else 128-code)
