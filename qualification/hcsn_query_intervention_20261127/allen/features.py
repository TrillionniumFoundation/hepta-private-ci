"""One sweep per file. Held-out feature construction can run without event labels."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from scipy.signal import lfilter
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import SCALES,HORIZONS,kernels,query,trace
def standard(x,c,s):
    raw=(x.astype(float)-c)/s
    lag=[raw]
    for tau in (2,6,16,40,100):
        a=np.exp(-2/tau);lag.append(lfilter([1-a],[1,-a],raw))
    z=np.column_stack(lag)
    current=np.tanh(.50*lag[0]+.35*lag[2]+.15*lag[3])
    return raw,current,np.column_stack([z,np.tanh(z),np.minimum(z*z,36)]).astype(np.float32)
def free_summary(u,n):
    answer=[]
    for h in HORIZONS:
        future=np.stack([u[k:k+n] for k in range(h)],1);previous=np.r_[u[0],u[:n-1]]
        values=[future.mean(1),future.max(1),future.min(1),future[:,-1]-previous,np.max(abs(future-previous[:,None]),1)]
        stack=np.column_stack(values)
        answer.append(np.column_stack([stack,np.tanh(2*stack),stack**2]))
    return np.stack(answer,1).astype(np.float32)
def prepare(data,work,wait):
    work.mkdir(parents=True,exist_ok=True);last=time.monotonic()
    while True:
        files=sorted(data.glob('[0-9]*.json'));touched=False
        for receipt in files:
            sid=receipt.stem;source=data/(sid+'.npz');meta=json.loads(receipt.read_text())
            if not source.exists():continue
            if (work/(sid+'.json')).exists():continue
            assert hashlib.sha256(source.read_bytes()).hexdigest()==meta['npz_sha256']
            stats={};tick=time.monotonic()
            with np.load(source,allow_pickle=False) as z:
                noise1=np.concatenate([z['x1_0'],z['x1_1']]).astype(float)
                c,s=noise1.mean(),max(noise1.std(),1e-8)
                for sw in meta['sweeps']:
                    tag=sw['key'];xp=z['x'+tag];n=len(xp)-max(HORIZONS)
                    raw,u,base=standard(xp,c,s)
                    out={'base':base,'anchors':np.arange(100,n,dtype=np.int32),'free':free_summary(u,n)}
                    for law in ('literal','fixed','tangent'):
                        for i,scale in enumerate(SCALES):
                            _,m,unused=kernels(u,law,scale);del unused
                            states,e=trace(m)
                            if e>1e-9:raise RuntimeError('mass decay')
                            probs=query(m,states)
                            out[law+str(i)]=np.stack([probs[h] for h in HORIZONS],1).astype(np.float32)
                    path=work/(sid+'-'+tag+'.npz');np.savez_compressed(path,**out)
                    stats[tag]={'bins':len(xp),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            (work/(sid+'.json')).write_text(json.dumps({'specimen':sid,'source_sha256':meta['npz_sha256'],
                  'constructor_wall_seconds':time.monotonic()-tick,'current_noise1_center':c,'current_noise1_scale':s,'sweeps':stats},indent=1)+'\n')
            print('features',sid,round(time.monotonic()-tick,2),flush=True);touched=True;last=time.monotonic()
        if not wait or len(list(work.glob('[0-9]*.json')))>=24:break
        if not touched:
            if time.monotonic()-last>1800:raise RuntimeError('no new source receipts for 30 minutes')
            time.sleep(5)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);ap.add_argument('--wait',action='store_true')
    a=ap.parse_args();prepare(a.data,a.work,a.wait)
