"""Record one complete read-only audit process; never overwrite an execution."""
from pathlib import Path
import hashlib
import json
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone

base=Path(__file__).resolve().parent
sources=[base/'review_delta.py',base/'bindings.json',base/'build_bindings.py',Path(__file__).resolve(),base.parent/'final-curation-independent-review-v1/review_final_curation_v1.py']
def ident(path):
    raw=path.read_bytes();return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
before={str(p):ident(p) for p in sources}
command=[sys.executable,'-B',str(base/'review_delta.py'),'--repository',str(base.parent/'hcsn-repo'),'--expected-manifest-sha256','bc8721b37d4a69c28a25a028dd6375ebbeaaa41111bafc97a22b7239609f5bc6','--bindings',str(base/'bindings.json'),'--output',str(base/'execution')]
started=datetime.now(timezone.utc).isoformat();wall=time.monotonic();cpu=resource.getrusage(resource.RUSAGE_CHILDREN)
with (base/'stdout.log').open('xb') as out,(base/'stderr.log').open('xb') as err:
    result=subprocess.run(command,stdout=out,stderr=err,check=False)
spent=time.monotonic()-wall;after_cpu=resource.getrusage(resource.RUSAGE_CHILDREN)
after={str(p):ident(p) for p in sources}
receipt={'schema':'independent-final-curation-delta-execution-v2','started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),'argv':command,'returncode':result.returncode,'whole_waited_process_wall_seconds':spent,'waited_child_cpu_seconds':after_cpu.ru_utime+after_cpu.ru_stime-cpu.ru_utime-cpu.ru_stime,'training_performed':False,'numerical_oracle_rerun':False,'native_runtime_reobserved':False,'source_before':before,'source_after':after,'sources_unchanged':before==after,'stdout':ident(base/'stdout.log'),'stderr':ident(base/'stderr.log')}
with (base/'EXECUTION.json').open('x') as f:f.write(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:receipt[k] for k in ['returncode','whole_waited_process_wall_seconds','waited_child_cpu_seconds','sources_unchanged']}))
print((base/'stdout.log').read_text())
sys.exit(result.returncode)
