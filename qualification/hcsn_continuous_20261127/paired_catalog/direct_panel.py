"""Sequential, resumable, single-CPU direct panel with interleaved configurations."""
import time,subprocess,sys,os,json
from pathlib import Path
from common import ROOT
HERE=Path(__file__).resolve().parent
def main():
    rounds=[(24,.03),(48,.03),(48,.15)]
    begin=time.monotonic();log=ROOT/'direct_jobs.jsonl'
    for width,l2 in rounds:
        for name in ['linear','literal','smooth','random']:
            seeds=[113,229,367] if name=='random' else [113]
            for seed in seeds:
                mark=ROOT/'fitted'/f'{name}-w{width}-r{l2}-s{seed}.json'
                if mark.exists():continue
                now=time.monotonic()
                result=subprocess.run([sys.executable,str(HERE/'construct.py'),name,str(width),str(l2),str(seed)],env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
                with log.open('a') as f:f.write(json.dumps({'arm':name,'width':width,'l2':l2,'seed':seed,'wall':time.monotonic()-now,'code':result.returncode})+'\n')
                if result.returncode:raise SystemExit(result.returncode)
    print('total',time.monotonic()-begin,flush=True)
if __name__=='__main__':main()
