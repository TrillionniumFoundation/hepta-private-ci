"""Feature calculation for genuinely simultaneous sender and receiver populations."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from scipy.signal import lfilter
from scipy.special import logit

DIR=Path(__file__).resolve().parent;sys.path.insert(0,str(DIR.parent))
from model import GRID,DT,MU,EPS,kernel,reset_vector
from hx_reference import StationaryFirm,Parameters
RESET=reset_vector()
def sig(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def enow(x,tau):
    a=np.exp(-1./tau);return lfilter([1-a],[1,-a],x,axis=-1)
def price_basis(path):
    with np.load(path) as z:return dict(z)
def b_at(x,law,tab):
    if law=='fixed':return np.zeros_like(x)
    u=tab['us'];w=tab['wall'];i=len(u)//2
    if law=='tangent':return x*(w[i+1]-w[i-1])/(u[i+1]-u[i-1])
    return np.interp(x,u,w)
def many_kernels(u,old,law,tab):
    shape=u.shape;shift=b_at(u,law,tab)-b_at(old,law,tab)
    drift=MU-.7*.25*u.ravel()-shift.ravel()/DT
    q=kernel(np.broadcast_to(GRID,(len(drift),len(GRID))),drift)
    return q.reshape(*shape,len(GRID),len(GRID))
def build(packet,tab):
    with np.load(packet) as r:
        count=r['source_count'];ns=len(r['source_unit_ids']);nd=len(r['target_unit_ids']);left=r['left'];right=r['right'];a=r['anchors'];hs=r['horizons']
        baseline=r['target_baseline_count'].astype(float)/(30*nd)
    source=count.astype(float)/ns;raw=np.clip((source-source[:,:40].mean())/max(source[:,:40].std(),.01),-6,6)
    traces=[raw]+[enow(raw,t) for t in (1,3,7,15)];z=.5*raw+.3*traces[2]+.2*traces[3]
    known=right-.35*left;u=np.tanh(.65*z+.7*known[:,None]*(np.arange(raw.shape[1])>=50))
    records=[]
    for l in range(0,len(raw),16):
        sl=slice(l,l+16);U=u[sl];zi=z[sl];c=known[sl];B=len(U)
        fu=np.tanh(.65*zi[:,a-1,None]*np.exp(-np.arange(1,max(hs)+1)[None,None,:]/4)+.7*c[:,None,None])
        prev=np.concatenate([U[:,:1],U[:,:-1]],axis=1)
        batch={};old=U[:,a-1]
        for law in ('fixed','tangent','literal'):
            mats=many_kernels(U[:,:a.max()],prev[:,:a.max()],law,tab)
            active=np.repeat(RESET[None,:],B,0);f=np.zeros(B);states=[]
            for j in range(a.max()+1):
                if j in a:states.append(np.column_stack([active,f]))
                if j<a.max():
                    surv=np.einsum('bi,bij->bj',active,mats[:,j]);loss=active.sum(1)-surv.sum(1);active=surv+f[:,None]*RESET;f=np.maximum(0.,loss)
            del mats
            states=np.stack(states,1);active=states[:,:,:-1].copy();f=states[:,:,-1];pp=[]
            for j in range(max(hs)):
                inp=fu[:,:,j];mat=many_kernels(inp,old if j==0 else fu[:,:,j-1],law,tab)
                active=np.einsum('bai,baij->baj',active,mat)
                if j==0:active+=f[:,:,None]*RESET
                if j+1 in hs:pp.append(logit(np.clip(1-active.sum(-1),EPS,1-EPS)))
            batch[law]=np.stack(pp,axis=-1).astype(np.float32)
            if law=='literal':
                prices=np.stack([np.interp(old,tab['us'],tab['price'][:,k]) for k in range(len(GRID))],axis=-1)
                batch['dual']=np.stack([np.sum(states[:,:,:-1]*prices,-1),states[:,:,:-1]@tab['f1']],axis=-1).astype(np.float32)
        records.append(batch)
    output={k:np.concatenate([d[k] for d in records]) for k in records[0]}
    trace=np.stack([v[:,a-1] for v in traces]+[z[:,a-1]-z[:,a-3],z[:,a-1]-z[:,a-6]],axis=-1)
    output['smooth']=np.concatenate([trace,np.tanh(trace),trace**2],axis=-1).astype(np.float32)
    output['baseline']=baseline.astype(np.float32);output['left']=left;output['right']=right;output['anchors']=a;output['horizons']=hs
    meta=dict(source_center=float(source[:,:40].mean()),source_scale=float(max(source[:,:40].std(),.01)),trials=len(raw))
    return output,meta
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('data',type=Path);ap.add_argument('out',type=Path);ap.add_argument('price',type=Path);args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True);tab=price_basis(args.price);last=time.monotonic()
    while True:
        sources=sorted(args.data.glob('P*.json'));done=0
        for path in sources:
            dd=json.loads(path.read_text());receipt=args.out/path.name
            if receipt.exists():done+=1;continue
            info={};start=time.monotonic()
            for name,part in dd['populations'].items():
                packet=args.data/part['packet'];assert sig(packet)==part['sha256']
                data,metadata=build(packet,tab);dest=args.out/part['packet'];np.savez_compressed(dest,**data);info[name]=dict(sha=sig(dest),**metadata)
            receipt.write_text(json.dumps({'session':dd['key'],'input_sha':sig(path),'features':info,'sec':time.monotonic()-start},indent=1)+'\n')
            done+=1;last=time.monotonic();print(dd['key'],list(info),round(time.monotonic()-start,2),flush=True)
        if done==39:break
        if time.monotonic()-last>2700:raise RuntimeError('incomplete session source acquisition')
        time.sleep(3)
