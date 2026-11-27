"""One-shot ordered sequence of registered seed jobs. Preserve completed checkpoints outside the volatile data disk."""
import json,subprocess,sys,os,time,shutil,hashlib
from pathlib import Path
from common import ROOT
HERE=Path(__file__).resolve().parent
def main(kind,skipfirst=False):
    durable=HERE/'selected';durable.mkdir(exist_ok=True)
    for seed in [113,229,367]:
        name=f'{kind}-{seed}';dst=ROOT/'neural_fitted'
        mark=dst/(name+'.json')
        if skipfirst and seed==113:continue
        if not mark.exists():
            result=subprocess.run([sys.executable,str(HERE/'neural.py'),kind,str(seed)],env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            if result.returncode:raise SystemExit(result.returncode)
        doc=json.loads(mark.read_bytes());p=dst/(name+'.pt');assert hashlib.sha256(p.read_bytes()).hexdigest()==doc['sha256']
        for f in (p,mark):
            temp=durable/(f.name+'.tmp');shutil.copyfile(f,temp);temp.replace(durable/f.name)
        print('retained',name,flush=True)
if __name__=='__main__':main(sys.argv[1],len(sys.argv)>2)
