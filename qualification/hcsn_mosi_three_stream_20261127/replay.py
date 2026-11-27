"""Replay every archived test score directly from the restored selected model parameters."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('restored',type=Path);p.add_argument('law',type=Path);p.add_argument('out',type=Path);p.add_argument('--cores',type=int,nargs='+',default=[2,4]);a=p.parse_args()
    restored=a.restored.resolve();files=sorted((restored/'models').glob('*.json'));a.out.mkdir(exist_ok=True,parents=True);scores=a.out/'scores';scores.mkdir(exist_ok=True)
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    def worker(i):
        values=[]
        for file in files[i::len(a.cores)]:
            r=json.loads(file.read_bytes());key=file.stem
            cmd=['taskset','-c',str(a.cores[i]),sys.executable,str(Path(__file__).with_name('cold.py')),'score',str(restored/'models'),str(restored/'data'),str(a.law.resolve()),str(restored/'law_check.json'),str(restored/'SEAL.json'),str(scores),str(r['width']),r['arm'],str(r['seed'])]
            output=scores/(key+'.npz')
            if not output.exists():subprocess.run(cmd,env=env,stdout=subprocess.DEVNULL,check=True)
            orig=restored/'cold'/(key+'.npz');body=digest(output)==digest(orig)
            with np.load(output) as x,np.load(orig) as y:
                assert set(x.files)==set(y.files)
                for name in x.files:assert np.array_equal(x[name],y[name]),(key,name)
                counts=sum(x[k].size for k in x.files if k not in ('video','clip','y','donors'))
            values.append((key,{'prediction_entries':counts,'byte_identical_npz':body,'recorded_sha256':digest(orig),'replay_sha256':digest(output)}))
            print('replayed',key,counts,body,flush=True)
        return values
    with ThreadPoolExecutor(len(a.cores)) as ex:
        records=dict(item for group in ex.map(worker,range(len(a.cores))) for item in group)
    out={'fits':len(records),'values_exactly_replayed':sum(v['prediction_entries'] for v in records.values()),'identical_npz_packages':sum(v['byte_identical_npz'] for v in records.values()),'results':records}
    (a.out/'REPLAY.json').write_text(json.dumps(out,indent=1,sort_keys=True)+'\n');print('all',out['fits'],out['values_exactly_replayed'],out['identical_npz_packages'])


if __name__=='__main__':main()
