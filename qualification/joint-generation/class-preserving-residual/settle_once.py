"""Wait the complete driver and its reaped children; finalize prospective caps."""
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT=pathlib.Path(__file__).resolve().parent
out=pathlib.Path(sys.argv[1])
if out.exists(): raise SystemExit('refuse existing run directory')
t=time.monotonic()
p=subprocess.Popen([sys.executable,'-I','-B',str(ROOT/'run_once.py'),str(out)])
pid,status,usage=os.wait4(p.pid,0)
p.returncode=os.waitstatus_to_exitcode(status)
total=usage.ru_utime+usage.ru_stime
record={'driver_exit_code':p.returncode,'driver_and_reaped_children_complete_cpu':total,
        'complete_wall_seconds':time.monotonic()-t,'complete_wait4':True,
        'settlement_report_process_cost':'separate unmeasured, not zero; no model/data computation',
        'historical_research_and_publication_cost':'separate unknown, not zero'}
if (out/'COST.json').exists():
    cost=json.loads((out/'COST.json').read_text())
    if 'complete_child_cpu' in cost and 'standalone_conservative_method_cpu' in cost:
        overhead=total-cost['complete_child_cpu']
        if overhead < -1e-6: raise RuntimeError('wait4 descendant accounting inconsistent')
        record['driver_complete_cpu']=max(0.,overhead)
        record['complete_standalone_conservative_method_cpu']={k:v+max(0.,overhead) for k,v in cost['standalone_conservative_method_cpu'].items()}
        record['complete_budget_pass']=(p.returncode==0 and total<=400 and record['complete_wall_seconds']<=600 and all(v<=60 for v in record['complete_standalone_conservative_method_cpu'].values()))
        result=json.loads((out/'science/RESULT.json').read_text())
        record['quality_gates_pass']=result['quality_gates_pass']
        record['study_pass']=record['complete_budget_pass'] and record['quality_gates_pass']
    else: record['complete_budget_pass']=False
else: record['complete_budget_pass']=False
out.mkdir(exist_ok=True)
(out/'FINAL_COST.json').write_text(json.dumps(record,indent=2,sort_keys=True,allow_nan=False)+'\n')
print(json.dumps(record),flush=True)
raise SystemExit(0 if p.returncode==0 and record['complete_budget_pass'] else 2)
