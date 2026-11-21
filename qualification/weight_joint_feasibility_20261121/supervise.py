"""Single-use process resource boundary; does not automatically retry."""
from pathlib import Path
import datetime
import json
import os
import resource
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def main():
    phase='reader' if sys.argv[1:]==['--reader'] else 'main'
    if sys.argv[1:] not in ([],['--reader']):raise ValueError('unknown argument')
    if not (ROOT/'PROTOCOL_FROZEN.json').exists():raise ValueError('freeze required')
    receipt_path=ROOT/f'{phase.upper()}_SUPERVISOR.json'
    if receipt_path.exists():raise ValueError('single attempt already supervised')
    if phase=='main':(ROOT/'attempt001').mkdir(exist_ok=False)
    elif not (ROOT/'attempt001/RESULTS.json').exists() or (ROOT/'attempt001/INDEPENDENT_REVIEW.json').exists():raise ValueError('reader requires original study and no previous review')
    cpu=120 if phase=='main' else 15;wallcap=180 if phase=='main' else 30
    def limits():
        os.sched_setaffinity(0,{7})
        resource.setrlimit(resource.RLIMIT_CPU,(cpu-1,cpu))
        resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    env=os.environ.copy()
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):env[name]='1'
    command=[sys.executable,str(ROOT/('run_study.py' if phase=='main' else 'verify_records.py'))]
    started=time.perf_counter();parent_cpu=time.process_time();before=resource.getrusage(resource.RUSAGE_CHILDREN)
    with (ROOT/f'{phase}.stdout.log').open('x') as stdout,(ROOT/f'{phase}.stderr.log').open('x') as stderr:
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,
            preexec_fn=limits,start_new_session=True)
        timed_out=False
        while process.poll() is None:
            if time.perf_counter()-started>=wallcap:
                timed_out=True;os.killpg(process.pid,signal.SIGKILL);break
            time.sleep(.1)
        exitcode=process.wait()
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    result=dict(schema='hepta-joint-study-supervisor-v1',phase=phase,command=command,
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),exit_code=exitcode,
        wall_timeout=timed_out,wall_seconds=time.perf_counter()-started,
        child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        child_peak_RSS_bytes=after.ru_maxrss*1024,supervisor_CPU_seconds=time.process_time()-parent_cpu,
        hard_limits=dict(CPU_seconds=cpu,wall_seconds=wallcap,address_space_bytes=536870912,affinity=[7],numeric_threads=1),
        automatic_retry=False)
    with receipt_path.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(result),flush=True)
    return exitcode if exitcode>=0 else 128-exitcode


if __name__=='__main__':sys.exit(main())
