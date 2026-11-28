"""Across-arm round robin. Newly created checkpoints can resume independently after interruption."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from itertools import product
CLOCK=(30,120,600,2100,4200);ARMS=('literal','smooth','lif','sdpa');SEEDS=(2039,4729,8047)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('law',type=Path);p.add_argument('--cpu',type=int,default=5);a=p.parse_args()
    os.sched_setaffinity(0,{a.cpu})
    for rung in CLOCK:
        for j in range(4):
            for i,seed in enumerate(SEEDS):
                arm=ARMS[(i+j)%4];fp=a.work/'fits'/f'{arm}-{seed}'/'progress.json'
                if fp.exists() and rung in json.loads(fp.read_text())['clock_done']:continue
                subprocess.run([sys.executable,str(Path(__file__).with_name('train.py')),str(a.work),str(a.law),str(seed),arm,str(rung)],check=True)
    print('ALL 12 MODEL FAMILIES FINISHED; SEAL BEFORE INDEPENDENT SCORING',flush=True)
