"""Create an immutable new software-test snapshot; never execute an actual C2 audit."""
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time

base=Path('/workspace/scratch/c385a7439f8e')
source=base/'c2-terminal-bootstrap-recovery-v2'
out=base/'c2-terminal-bootstrap-recovery-validation-attempt-03'
out.mkdir(); snapshot=out/'source';snapshot.mkdir()
names=['bootstrap.py','os_processes.py','test_bootstrap.py','auditor-core.zip']
def identities(root):
    return {n:{'bytes':(root/n).stat().st_size,'sha256':hashlib.sha256((root/n).read_bytes()).hexdigest()} for n in names}
for n in names:shutil.copyfile(source/n,snapshot/n)
before=identities(snapshot)
(out/'SOURCE-BEFORE.json').write_text(json.dumps(before,indent=2)+'\n')
argv=[sys.executable,'-B','-m','unittest','test_bootstrap','-v']
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='')
def limits():resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,256*1024**2))
started=time.monotonic();timed_out=False
with (out/'stdout').open('xb') as so,(out/'stderr').open('xb') as se:
    child=subprocess.Popen(argv,cwd=snapshot,env=env,stdout=so,stderr=se,start_new_session=True,preexec_fn=limits)
    while True:
        pid,status,usage=os.wait4(child.pid,os.WNOHANG)
        if pid:break
        if time.monotonic()-started>=30 and not timed_out:
            timed_out=True;os.killpg(child.pid,signal.SIGKILL)
        time.sleep(.01)
    child.returncode=os.waitstatus_to_exitcode(status)
wall=time.monotonic()-started;after=identities(snapshot)
report={'schema':'new-bootstrap-recovery-software-validation-v2','status':'passed' if child.returncode==0 and before==after and not timed_out else 'failed',
    'argv':argv,'cwd':str(snapshot),'PID':child.pid,'returncode':child.returncode,'timed_out':timed_out,
    'source_before':before,'source_after':after,'source_unchanged':before==after,
    'whole_child_wall_seconds':wall,'wait4_child_CPU_seconds':usage.ru_utime+usage.ru_stime,
    'wait4_peak_RSS_bytes':usage.ru_maxrss*1024,'limits':{'wall_seconds':30,'address_space_bytes':256*1024**2},
    'stdout':{'bytes':(out/'stdout').stat().st_size,'sha256':hashlib.sha256((out/'stdout').read_bytes()).hexdigest()},
    'stderr':{'bytes':(out/'stderr').stat().st_size,'sha256':hashlib.sha256((out/'stderr').read_bytes()).hexdigest()},
    'production_C2_inputs_read':False,'model_or_E_access':False,'actual_audit_or_training_executed':False,
    'original_lost_14_test_receipt_recreated':False,'scope':'New stdlib software checks with explicit metadata mocks and two actual short non-model children. Complete test-child wall/wait4 includes those nested costs; no double addition.'}
(out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report));raise SystemExit(child.returncode)
