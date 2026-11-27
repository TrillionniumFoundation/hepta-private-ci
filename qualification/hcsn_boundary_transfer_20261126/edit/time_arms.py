"""Launch separate fresh training processes for fixed arms; compare against the saved seal."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('study',choices=('har','wisdm'))
parser.add_argument('data',type=Path)
parser.add_argument('out',type=Path)
parser.add_argument('--repeats',type=int,default=3)
args=parser.parse_args()
root=Path(__file__).parent
arms=['KEEP','inverse','same_BP','wide_BP','ridge']
if (args.out/'cold.json').exists():
    raise FileExistsError('Existing timing set; choose a fresh copy of the seal directory')
env=dict(os.environ,OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',OMP_NUM_THREADS='1')
rows=[]
for repeat in range(args.repeats):
    offset=(2*repeat)%len(arms)
    for arm in arms[offset:]+arms[:offset]:
        if args.study=='har':
            command=[sys.executable,str(root/'cold_har.py'),arm,str(args.data),str(args.out)]
        else:
            command=[sys.executable,str(root/'wisdm'/'run.py'),'cold',str(args.data),str(args.out),'--arm',arm]
        start=time.perf_counter()
        done=subprocess.run(command,capture_output=True,text=True,check=True,env=env)
        elapsed=time.perf_counter()-start
        row=json.loads(done.stdout)
        row.update(process_seconds=elapsed,repeat=repeat)
        rows.append(row)
        (args.out/'cold.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(row,flush=True)
