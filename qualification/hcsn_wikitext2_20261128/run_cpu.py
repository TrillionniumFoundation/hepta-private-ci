import argparse
import os
from pathlib import Path
import subprocess
import sys

ap=argparse.ArgumentParser();ap.add_argument('seed',type=int);ap.add_argument('--first-core',type=int,default=1);args=ap.parse_args()
root=Path(__file__).resolve().parent
env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
workers=[]
for i,kind in enumerate(('hx','sdpa','smooth','lif')):
    slot=root/'results'/f'{kind}-{args.seed}.log'
    with slot.open('x') as dest:
        p=subprocess.Popen(['taskset','-c',str(args.first_core+i),sys.executable,'src/train.py','.',kind,str(args.seed)],cwd=root,env=env,stdout=dest,stderr=subprocess.STDOUT)
    workers.append(p)
codes=[p.wait() for p in workers]
if any(codes):raise RuntimeError(codes)
