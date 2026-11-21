"""One subprocess, bounded resources, no retry; record actual child cost."""
import datetime
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
if (ROOT/'attempt001_supervisor.json').exists():raise ValueError('supervision already attempted')
env=dict(os.environ)
env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
start=time.perf_counter();before=resource.getrusage(resource.RUSAGE_CHILDREN)
with (ROOT/'attempt001.stdout.log').open('x') as stdout,(ROOT/'attempt001.stderr.log').open('x') as stderr:
    child=subprocess.Popen([sys.executable,str(ROOT/'experiment.py'),'--protocol',str(ROOT/'PROTOCOL_FROZEN.json'),
        '--output',str(ROOT/'attempt001')],stdout=stdout,stderr=stderr,env=env,cwd=ROOT)
    timeout=False
    try:code=child.wait(timeout=610)
    except subprocess.TimeoutExpired:
        timeout=True;child.kill();code=child.wait()
after=resource.getrusage(resource.RUSAGE_CHILDREN)
record=dict(exit_code=code,supervisor_timeout=timeout,no_retry=True,
    child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
    enclosed_wall_seconds=time.perf_counter()-start,child_peak_RSS_bytes=after.ru_maxrss*1024,
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    science_limit_CPU_seconds=300,science_limit_wall_seconds=600,
    original_sources_written=False,live_application_actions=False)
with (ROOT/'attempt001_supervisor.json').open('x') as stream:json.dump(record,stream,indent=2);stream.write('\n')
print(json.dumps(record));sys.exit(0 if code==0 else 1)
