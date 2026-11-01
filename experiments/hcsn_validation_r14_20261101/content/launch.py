"""Serial scientific workers, with full child-process receipts and failures."""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def run(output, phase):
    protocol=json.loads((output/'PROTOCOL.json').read_text())
    receipts=output/'receipts';receipts.mkdir(exist_ok=True)
    jobs=[(task,seed,mode) for task in protocol['tasks'] for seed in protocol['seeds'] for mode in protocol['modes']]
    begin=time.process_time();wall=time.perf_counter()
    complete=[]
    for task,seed,mode in jobs:
        name=f'{phase}_{task}_s{seed}_{mode}'
        if (receipts/(name+'.json')).exists():
            raise FileExistsError('Attempt already has a receipt: '+name)
        module='study' if phase=='train' else 'evaluate'
        command=[sys.executable,'-B','-m','experiments.hcsn_validation_r14_20261101.content.'+module,
            'train' if phase=='train' else 'one','--output',str(output),'--task',task,'--seed',str(seed),'--mode',mode]
        env=dict(os.environ)
        env.update(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
        start=time.perf_counter()
        with (receipts/(name+'.stdout')).open('xb') as out,(receipts/(name+'.stderr')).open('xb') as err:
            child=subprocess.Popen(command,stdout=out,stderr=err,env=env)
            _,status,usage=os.wait4(child.pid,0)
            code=os.waitstatus_to_exitcode(status);child.returncode=code
        record=dict(command=command,exit_code=code,cpu_seconds=usage.ru_utime+usage.ru_stime,
            wall_seconds=time.perf_counter()-start,max_rss_bytes=int(usage.ru_maxrss*(1 if sys.platform=='darwin' else 1024)),
            energy_joules=None,energy_status='unavailable',scope='complete scientific child; internal phases nested')
        (receipts/(name+'.json')).write_text(json.dumps(record,indent=2)+'\n')
        complete.append(record)
        print(json.dumps(dict(job=name,exit_code=code,cpu_seconds=record['cpu_seconds'])),flush=True)
        if code:raise RuntimeError('Worker failed; evidence retained: '+name)
    (receipts/(phase+'_TOTAL.json')).write_text(json.dumps(dict(jobs=len(complete),
        full_child_cpu_seconds=sum(r['cpu_seconds'] for r in complete),
        coordinator_cpu_seconds=time.process_time()-begin,wall_seconds=time.perf_counter()-wall,
        runtime=platform.python_version(),energy_joules=None),indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['train','evaluate'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.output,args.phase)
