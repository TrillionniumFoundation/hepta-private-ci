"""Independent CPU-device matrix with a bounded worker per seed and validated public data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
CLOCK=(30,120,600,2100,4200)
ARMS=('literal','smooth','lif','sdpa')
SEEDS=(2039,4729,8047)


def run(root,cores):
    if len(set(cores))!=3 or not set(cores)<=os.sched_getaffinity(0):raise ValueError('select three distinct available CPU cores')
    root=root.resolve();w=root/'work';w.mkdir(exist_ok=True,parents=True)
    law=root/'law4.npz';logs=root/'logs';logs.mkdir(exist_ok=True)
    os.nice(10)
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1','HIP_VISIBLE_DEVICES':'','ROCR_VISIBLE_DEVICES':'','CUDA_VISIBLE_DEVICES':''}
    def call(cpu,name,args):
        print(time.strftime('%Y-%m-%d %H:%M:%SZ',time.gmtime()),name,args[0],flush=True)
        with (logs/(name+'.log')).open('a') as f:
            subprocess.run(['taskset','-c',str(cpu),sys.executable,*map(str,args)],check=True,stdout=f,stderr=subprocess.STDOUT,env=env)
    with (root/'device.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        material=root/'material';rs=material/'rsicd';ucm=material/'ucm';corpora=material/'corpora';data=w/'data'
        if not (data/'data.json').exists():
            with ThreadPoolExecutor(max_workers=2) as ex:
                f1=ex.submit(call,cores[0],'public-rs-ucm',[HERE.parent/'sources.py',rs,ucm]);f2=ex.submit(call,cores[1],'public-nwpu-sydney',[HERE/'acquire.py',corpora]);f1.result();f2.result()
            call(cores[0],'source-arrays',[HERE/'data.py',rs,ucm,corpora,data])
        expected=json.loads((HERE/'DATA.json').read_text());actual=json.loads((data/'data.json').read_text())
        for k in ('arrays','counts','raw_files','vocab'):assert expected[k]==actual[k],k
        device={'hostname':platform.node(),'cores':cores,'wall_start':time.time(),'logical_cpu_count':os.cpu_count(),'python':sys.version,'mode':'single-thread FP32 CPU, isolated seed/core'}
        (w/'device.json').write_text(json.dumps(device,indent=2)+'\n')
        if not (w/'linear.json').exists():call(cores[0],'linear',[HERE/'linear_scale.py',w])
        def matrix(pair):
            i,cpu=pair;sd=SEEDS[i]
            for rung in CLOCK:
                for j in range(4):
                    arm=ARMS[(i+j)%4];p=w/'fits'/f'{arm}-{sd}'/'progress.json'
                    if p.exists() and rung in json.loads(p.read_text())['clock_done']:continue
                    call(cpu,'train-'+str(sd),[HERE/'train.py',w,law,sd,arm,rung])
        with ThreadPoolExecutor(max_workers=3) as ex:list(ex.map(matrix,enumerate(cores)))
        # All remote runs include full process-birth timing from their first minibatch.
        (w/'early-clock-brackets.json').write_text('{}\n')
        call(cores[0],'cold',[HERE/'confirmation.py',w,law,'--seal'])
        call(cores[0],'cold',[HERE/'confirmation.py',w,law,'--confirm'])
        call(cores[0],'cold',[HERE/'recount.py',w])
        print('complete full separate-device matrix',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('--cores',nargs=3,type=int,required=True);a=ap.parse_args();run(a.root,a.cores)
