"""Synthetic controller control; never imports or executes C2 numerical code."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


SOURCE = Path('/workspace/scratch/d741f7769aeb/worktrees/n256-c2/qualification/hcsn_c2_continuation_20261119/controller.py')
HERE = Path(__file__).parent
CASE = HERE/'attempt002'
CASE.mkdir()
shutil.copyfile(SOURCE, CASE/'controller.py')
toy = '''import argparse,json,os,signal,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--fit');a=p.parse_args()
root=Path(__file__).parent/'RUN_OUTPUT'/a.fit;root.mkdir()
start=float(os.environ['HCSN_PHASE_START'])
def finish(status):
    result={'status':status,'synthetic':True,'c2_calls':0,'torch_imports':0,
            'pid':os.getpid(),'affinity':sorted(os.sched_getaffinity(0)),
            'stop_request_present':(root/'STOP_REQUEST.json').exists(),
            'dispatch_elapsed_seconds':time.monotonic()-start}
    (root/'RESULT.json').write_text(json.dumps(result))
    raise SystemExit(0)
signal.signal(signal.SIGTERM,lambda s,f:finish('BUDGET_STOP'))
while True:
    for k in range(10000):
        v=k*k
    if a.fit=='fast' and time.monotonic()-start>.12:finish('TOY_COMPLETED')
    time.sleep(.01)
'''
(CASE/'runner.py').write_text(toy)
request = {'identity':'SYNTHETIC-CONTROLLER-CONTROL-001', 'original_root':str(CASE/'not-original-data'),
           'original_c2_program':str(CASE/'not-original-program'),
           'fits':[{'name':name,'new_identity':'synthetic-'+name} for name in ('fast','budget')],
           'budget':{'address_space_bytes_per_fit':4*1024**3, 'cleanup_grace_seconds':.5,
                     'concurrency':2, 'minimum_available_memory_bytes':0,
                     'minimum_output_disk_free_bytes':0, 'peak_rss_stop_bytes_per_fit':128*1024**2,
                     'scientific_wall_seconds_per_fit':.6,'threads_per_fit':1}}
(CASE/'REQUEST.json').write_text(json.dumps(request))
(CASE/'BINDINGS.json').write_text(json.dumps({'synthetic':True,'identity':request['identity']}))
files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
         (CASE/'controller.py',CASE/'runner.py',CASE/'REQUEST.json',CASE/'BINDINGS.json')}
(CASE/'FREEZE.json').write_text(json.dumps({'identity':request['identity'],'files':files}))
started = time.monotonic()
process = subprocess.run([sys.executable,str(CASE/'controller.py')],capture_output=True,text=True,timeout=6)
(CASE/'controller.stdout').write_text(process.stdout)
(CASE/'controller.stderr').write_text(process.stderr)
terminal = json.loads((CASE/'RUN_OUTPUT/TERMINAL.json').read_text())
costs = terminal['fits']
assert process.returncode == 0 and terminal['status']=='REVIEWABLE_TERMINALS'
assert len(costs)==2 and len({v['pid'] for v in costs.values()})==2
assert len({v['assigned_cpu'] for v in costs.values()})==2
assert costs['fast']['external_stop'] is None
assert costs['budget']['external_stop']['reason']=='scientific_wall_limit'
assert all(v['cpu_total_seconds']>0 and v['peak_rss_kib']>0 and not v['hard_killed'] for v in costs.values())
assert all(not Path('/proc/'+str(v['pid'])).exists() for v in costs.values())
assert all(v['exit_code']==0 and v['raw_wait_status']==0 for v in costs.values())
assert json.loads((CASE/'RUN_OUTPUT/budget/RESULT.json').read_text())['stop_request_present']
result = {'status':'SYNTHETIC_CONTROL_PASSED','source_sha256':files['controller.py'],
          'wall_seconds':time.monotonic()-started,'new_c2_or_model_calls':0,
          'actual_request_modified':False,'control_request_limits_do_not_apply_to_C2':True,
          'parallel_distinct_physical_cores':True,'both_exact_wait4_receipts':True,
          'budget_stop_signal_exit_and_durable_receipt':True,'both_children_reaped':True,
          'fits':costs}
(CASE/'CONTROL.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='fits'},sort_keys=True))
