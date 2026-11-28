"""Finite wall-only study, with independently scoped branch and three concurrent CPU cores."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from law import ARMS
import panel_supervisor as publication
from train import SEEDS,RUNGS,digest,atomic_json
publication.BRANCH='research/hcsn-wall-only-shd-8559'
publication.PREFIX='qualification/hcsn_wall_only_shd_8559'
CORES=(22,24,26)
def main(root,data,sha):
    root=root.resolve();data=data.resolve();src=root/'source/vector/panel.py';os.chdir(root)
    for d in ['runs','receipts','logs']:(root/d).mkdir(exist_ok=True)
    runs=root/'runs'
    with (root/'fit.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def push(files,comment):return publication.publish(files,comment,sha,root)
        jobs=[(a,s) for s in SEEDS for a in ARMS]
        def order_and_seal(r):
            order=np.random.default_rng(39024+r).permutation(len(jobs))
            def shard(n):
                for ix in order[n::len(CORES)]:
                    a,s=jobs[ix];p=root/'logs'/f'{a}-{s}-{r}.log'
                    with p.open('a') as h:
                        subprocess.run(['taskset','-c',str(CORES[n]),sys.executable,'-u',str(src),'fit',str(data),str(runs),str(r),'--arm',a,'--seed',str(s)],
                                       stdout=h,stderr=subprocess.STDOUT,check=True)
                    print('trained',a,s,r,flush=True)
            with ThreadPoolExecutor(len(CORES)) as ex:list(ex.map(shard,range(len(CORES))))
            rows=[];files=[]
            for a,s in jobs:
                d=runs/f'{a}-{s}';rec=d/f'rung-{r}.json';weight=d/f'selected-{r}.pt'
                v=json.loads(rec.read_text());assert digest(weight)==v['selected_hash']
                rows.append(dict(arm=a,seed=s,receipt_sha256=digest(rec),selected_sha256=digest(weight)));files.extend([rec,weight])
            manifest=runs/f'seal-{r}.json';atomic_json(manifest,rows)
            return push([manifest,*files],f'Seal 15 continuous scalar-only and comparator models before cold scoring, rung {r}')
        def score(r):
            out=root/f'cold-{r}'
            subprocess.run(['taskset','-c',str(CORES[0]),sys.executable,'-u',str(src),'cold',str(data),str(runs),str(r),'--out',str(out)],check=True)
            return push(sorted(out.iterdir()),f'Preserve all cold SHD logits and causal boundary ablations for rung {r}')
        for r in RUNGS:
            publication.mark(root,f'sealed-{r}',lambda:publication.retry(lambda:order_and_seal(r),'fit or preserve'))
            if r==30:publication.mark(root,'early-30',lambda:publication.retry(lambda:score(r),'early cool'))
        for r in RUNGS[1:]:publication.mark(root,f'cold-{r}',lambda:publication.retry(lambda:score(r),'independent cold'))
        print('SHD WALL-ONLY STUDY FINISHED',flush=True)
if __name__=='__main__':
    os.nice(8);main(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
