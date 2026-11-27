"""Run finite pre-registered CPU cases; preserve completed cells and wait at external seal."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ARMS=('forward','shuffle','feature_only','tied_only','frozen_probe');SEEDS=(109,271,463)
HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('law_data',type=Path);p.add_argument('archive_target',type=Path);p.add_argument('--after',type=Path);p.add_argument('--cores',type=int,nargs=2,default=[2,4]);a=p.parse_args()
    w=a.work.resolve();a.archive_target.mkdir(exist_ok=True,parents=True);store=a.archive_target.resolve()
    env={**os.environ,'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','FULLSTACK_DATA':str(a.law_data.resolve())}
    def command(core,script,*arg,subenv=None):
        subprocess.run(['taskset','-c',str(core),sys.executable,str(HERE/script),*map(str,arg)],env=subenv or env,check=True)
    def exists(p):
        while not p.exists():time.sleep(12)
    if a.after:exists(a.after)
    exists(w/'frozen_code.json')
    if not (w/'qualification.json').exists():command(a.cores[0],'qualify.py',w/'qualification.json')
    if not (w/'prepared.json').exists():command(a.cores[0],'prepare_fit.py',w)
    if not (w/'law4.npz').exists():(w/'law4.npz').write_bytes((a.law_data/'law4.npz').read_bytes())
    plans=[(a0,s) for j,s in enumerate(SEEDS) for a0 in ARMS[j:]+ARMS[:j]]
    def lane(i):
        for arm,seed in plans[i::2]:
            if not (w/'fits'/f'{arm}-{seed}'/'done.json').exists():command(a.cores[i],'fit.py',w,arm,seed)
    with ThreadPoolExecutor(2) as e:list(e.map(lane,(0,1)))
    if not (w/'SEAL.json').exists():command(a.cores[0],'cold.py','seal',w)
    exists(w/'remote_seal_receipt.json')
    command(a.cores[0],'cold.py','prepare',w)
    def measure(i):command(a.cores[i],'cold.py','score',w,'--lane',i,'--lanes',2)
    with ThreadPoolExecutor(2) as e:list(e.map(measure,(0,1)))
    command(a.cores[0],'verify.py',w,w/'result-local.json')
    for k in ('evidence','recipes'):
        command(a.cores[0],'pack.py','pack',w,store,k)
        command(a.cores[0],'pack.py','restore',store,w/'decoded',k)
    de=w/'decoded';command(a.cores[0],'verify.py',de,w/'independent-local.json')
    assert (w/'independent-local.json').read_bytes()==(w/'result-local.json').read_bytes()
    replaydir=w/'replayed';replaydir.mkdir(exist_ok=True)
    reenv={**env,'FULLSTACK_DATA':str(de)}
    def rescore(i):command(a.cores[i],'cold.py','score',de,'--lane',i,'--lanes',2,'--destination',replaydir,subenv=reenv)
    with ThreadPoolExecutor(2) as e:list(e.map(rescore,(0,1)))
    command(a.cores[0],'replay.py',de,replaydir,subenv=reenv)
    (w/'local_replay_complete').touch()
    print('all local cases and replay complete',flush=True)
    exists(a.law_data/'cold_manifest.json')
    def base(i):
        if not (w/'bp'/((('literal','sdpa')[i])+'-verification.json')).exists():
            command(a.cores[i],'import_bp.py',w,a.law_data,('literal','sdpa')[i])
    with ThreadPoolExecutor(2) as e:list(e.map(base,(0,1)))
    command(a.cores[0],'import_bp.py',w,a.law_data,'merge')
    command(a.cores[0],'verify.py',w,w/'result-joint.json','--bp',w/'bp')
    command(a.cores[0],'pack.py','pack',w,store,'paired');command(a.cores[0],'pack.py','restore',store,de,'paired')
    command(a.cores[0],'verify.py',de,w/'independent-joint.json','--bp',de/'bp')
    assert (w/'independent-joint.json').read_bytes()==(w/'result-joint.json').read_bytes()
    (w/'joint_complete').touch()
    print('all paired literal and SDPA cases complete',flush=True)


if __name__=='__main__':main()
