"""Train true hidden projection matrices by residual-guided covariance subspaces."""
import argparse
from pathlib import Path
import numpy as np
from common import WIDTH,PEN,sha,usage,indices,calibrate,record,better,trdata,gate_features,pool,sufficient,ridge


def local_layer(x,y,people,table,kind,method,seed,classes):
    rng=np.random.default_rng(seed)
    x64=x.astype('f8')
    mean=x64.mean((0,1))
    centered=x64-mean
    d=centered.shape[-1]
    q=centered.reshape(-1,d)
    cov=q.T@q/len(q)
    penalty=.10*float(np.trace(cov))/d
    ew,ev=np.linalg.eigh(cov)
    whitener=(ev/np.sqrt(ew.clip(0.)+max(penalty,1.e-8)))@ev.T
    white=(centered@whitener).astype('f4')
    target=np.eye(classes,dtype='f4')[y]
    residual=target-target.mean(0)
    basis=np.zeros((d,0))
    pieces=[];traces=[]
    for block in range(4):
        if method=='random':
            cand=rng.normal(size=(d,4))
        else:
            rr=residual.copy()
            if method=='shuffled':
                for spk in np.unique(people):
                    pos=np.flatnonzero(people==spk)
                    rr[pos]=rr[rng.permutation(pos)]
            cand=np.concatenate([white[:,t,:].T@rr/len(x) for t in range(white.shape[1])],axis=1)
        cand-=basis@(basis.T@cand)
        if method=='random':
            directions=np.linalg.qr(cand)[0][:,:4]
        else:
            directions=np.linalg.svd(cand,full_matrices=False)[0][:,:4]
        directions-=basis@(basis.T@directions)
        directions=np.linalg.qr(directions)[0][:,:4]
        basis=np.concatenate([basis,directions],axis=1)
        w=whitener@directions
        rms=np.sqrt(np.maximum(np.diag(w.T@cov@w),1.e-10))
        pieces.append(w/rms)
        weights=np.concatenate(pieces,axis=1).astype('f4')
        bias=(-mean@weights).astype('f4')
        h=gate_features(x,weights,bias,table,kind)
        z=pool(h)
        a,b=ridge(sufficient(z,y,classes),.003)
        residual=target-(z@a+b)
        traces.append(dict(width=weights.shape[1],residual_mse=float(np.mean(residual**2)),
                           residual_norm=float(np.linalg.norm(residual)),w_norm=float(np.linalg.norm(weights))))
    return h,weights,bias,traces


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--arm',choices=('physical','smooth','random','shuffled','ridge'),required=True)
    ap.add_argument('--seed',type=int,required=True);args=ap.parse_args()
    (x,y,ppl),(xd,yd,pd),center,scale=trdata(args.data,'joint')
    table=dict(np.load(args.data/'law.npz'))
    kind='smooth' if args.arm=='smooth' else 'physical'
    method=args.arm if args.arm in ('random','shuffled') else 'supervised'
    state={'kind':np.array('ridge' if args.arm=='ridge' else kind),'center':center,'scale':scale}
    if args.arm=='ridge':
        f=x.reshape(len(x),-1);fd=xd.reshape(len(xd),-1);traces=[]
    else:
        h1,w,b,tr1=local_layer(x,y,ppl,table,kind,method,args.seed,20)
        state.update(w1=w,b1=b)
        h1dev=gate_features(xd,w,b,table,kind)
        h2,w,b,tr2=local_layer(h1,y,ppl,table,kind,method,args.seed+37,20)
        state.update(w2=w,b2=b)
        f=pool(h2);fd=pool(gate_features(h1dev,w,b,table,kind))
        traces=[tr1,tr2]
    stats=sufficient(f,y,20);best=None;log=[]
    for pen in sorted(PEN,reverse=True):
        a,b=ridge(stats,pen);scores=fd@a+b
        dev,t=calibrate(scores,yd,pd)
        result=dict(penalty=pen,dev=dev,temperature=t)
        log.append(result)
        if better(best,result):
            best=result;state.update(head=a,head_bias=b,temperature=np.float64(t))
    args.out.mkdir(parents=True,exist_ok=True)
    saved=args.out/'selected.npz';np.savez_compressed(saved,**state)
    record(args.out/'fit.json',dict(arm=args.arm,seed=args.seed,best=best,roster=log,training_steps=traces,
        n=len(x),dev_n=len(xd),checkpoint=sha(saved),test_label_access=False,**usage()))
    print(args.arm,args.seed,best['dev']['speaker_acc'],flush=True)
if __name__=='__main__':main()
