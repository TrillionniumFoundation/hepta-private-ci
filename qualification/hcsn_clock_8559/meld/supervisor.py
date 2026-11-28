"""Complete finite raw MELD study on one host, preserving source-only and cold-stage receipts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from encoder import ARMS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import panel_supervisor as publication

publication.BRANCH='research/hcsn-meld-original-modalities-8559'
publication.PREFIX='qualification/hcsn_meld_8559'
CORES=(36,38,40)
def sha(p):
    with p.open('rb') as h:return hashlib.file_digest(h,'sha256').hexdigest()
def save(path,body):
    tmp=path.with_suffix('.pending');tmp.write_text(json.dumps(body,indent=1)+'\n');os.replace(tmp,path)
def run(args,core=None):
    command=[sys.executable,'-u',*map(str,args)]
    if core is not None:command=['taskset','-c',str(core),*command]
    subprocess.run(command,check=True)
def main(root,base):
    root=root.resolve();os.chdir(root);src=root/'source'/'meld';data=root/'data';runs=root/'runs';runs.mkdir(exist_ok=True)
    for name in ['receipts','logs']:(root/name).mkdir(exist_ok=True)
    with (root/'study.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def stage(name,job):
            f=root/'receipts'/(name+'.json')
            if f.exists():return json.loads(f.read_text())['value']
            result=publication.retry(job,name);save(f,dict(value=result,recorded=time.time()));return result
        def push(files,message):return publication.publish(files,message,base,root)
        # Acquisition already started independently. A lagging download keeps its original file owner.
        while not (data/'ACQUIRED.json').exists():time.sleep(40)
        def prepare():
            t=time.perf_counter();run([src/'prepare.py',data,'--workers','3']);run([src/'pack_data.py',data])
            return dict(prep_wall_s=time.perf_counter()-t,input_hash=sha(data/'arrays/INPUTS.json'))
        stage('source-arrays',prepare)
        stage('preserve-inputs',lambda:push([data/'ACQUIRED.json',data/'arrays/INPUTS.json',data/'official/FILES.json',root/'receipts/source-arrays.json'],'Lock MELD input row IDs, file hashes, duplicate checks and split counts'))
        def score(r):
            folder=root/f'cold-{r}';run([src/'train.py','cold',data/'arrays',runs,r,'--out',folder],CORES[0])
            run([src/'score.py',data/'arrays',runs,folder,r,folder/'summary.json'],CORES[0])
            return push(sorted(folder.iterdir()),f'Publish independent MELD cold logits, causal channel checks and paired statistics, budget {r}')
        for rung in (30,180,720,1800):
            def train_joint():
                jobs=[(a,s) for s in (137,311,557) for a in ARMS]
                order=np.random.default_rng(42109+rung).permutation(len(jobs))
                def shard(ix):
                    for j in order[ix::len(CORES)]:
                        a,s=jobs[j];log=root/'logs'/f'{a}-{s}-{rung}.log'
                        with log.open('a') as h:
                            cmd=['taskset','-c',str(CORES[ix]),sys.executable,'-u',str(src/'train.py'),'fit',str(data/'arrays'),str(runs),str(rung),'--arm',a,'--seed',str(s)]
                            subprocess.run(cmd,stdout=h,stderr=subprocess.STDOUT,check=True)
                        print('completed',a,s,rung,flush=True)
                with ThreadPoolExecutor(len(CORES)) as pool:list(pool.map(shard,range(len(CORES))))
                entries=[];files=[]
                for a,s in jobs:
                    r=runs/f'{a}-{s}'/f'rung-{rung}.json';weight=r.parent/f'selected-{rung}.pt';obs=json.loads(r.read_text())
                    assert sha(weight)==obs['selected_sha256'];entries.append(dict(arm=a,seed=s,receipt_sha256=sha(r),selected_sha256=sha(weight)));files.extend([r,weight])
                seal=runs/f'seal-{rung}.json';save(seal,entries)
                return push([seal,*files],f'Seal all 18 raw three-modal encoder selections before test, budget {rung}')
            stage(f'seal-{rung}',train_joint)
            if rung==30:stage('cold-30',lambda:score(30))
        for rung in (180,720,1800):stage(f'cold-{rung}',lambda:score(rung))
        print('MELD MATRIX FINISHED',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('base');a=p.parse_args();os.nice(8);main(a.root,a.base)
