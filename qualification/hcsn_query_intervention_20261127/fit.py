"""Select all senders on two allowed historical partitions; cold scoring is separate."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from scipy.special import expit
from model import (FOLD,HORIZONS,PENALTIES,SCALES,SUPERVISED,EPS,boundary,design,inputs,
                   kernels,logistic,predict,query,score,target,time_anchors,trace)

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def fit(data,out):
    out.mkdir(exist_ok=True,parents=True);receipts={};tr=time_anchors('train');dv=time_anchors('dev')
    for site in 'ABC':
        p=data/(site+'.npz')
        with np.load(p) as z: x=z['currents'];y=z['y'][:FOLD['dev'][1]+max(HORIZONS)].copy()
        start=time.monotonic();u,features,norm=inputs(x);train_y=target(y,tr,SUPERVISED);dev_y=target(y,dv,SUPERVISED)
        rec={'source_sha256':digest(p),'repeats':y.shape[1],'input_bins':len(u),'methods':{},'transport_checks':[],'candidates':{},'train_cost':{}}
        train_idx=np.arange(FOLD['train'][0],FOLD['train'][1])
        def consider(name,key,raw,tfit,extras=None):
            xx=design(raw,tr,SUPERVISED);xd=design(raw,dv,SUPERVISED)
            for pen in PENALTIES:
                tick=time.monotonic();model=logistic(xx,train_y,pen)
                pp=predict(model,xd).reshape(dev_y.shape);ll,bb=score(pp,dev_y)
                row={'law_setting':str(key),'calibration_penalty':pen,'dev_log_loss':float(ll.mean()),'dev_brier':float(bb.mean()),
                     'feature_seconds':tfit,'calibration_seconds':time.monotonic()-tick}
                rec['candidates'].setdefault(name,[]).append(row)
                best=rec['methods'].get(name)
                if best is None or row['dev_log_loss']<best['dev_log_loss']:
                    rec['methods'][name]={**row,'calibrator':model,**(extras or {})}
                    ordered=np.array([raw[k] for k in HORIZONS])
                    np.savez_compressed(out/(site+'-'+name+'-raw.npz'),raw=ordered)
        for law in ('literal','tangent','fixed'):
            for scale in SCALES:
                tic=time.monotonic();b,m,flat=kernels(u,law,scale);states,err=trace(m)
                preparation=time.monotonic()-tic
                rec['transport_checks'].append({'law':law,'scale':scale,'mass_error':err})
                for condition in ('query','flat'):
                    tick=time.monotonic();raw=query(m,states,None if condition=='query' else flat)
                    consider(law+'_'+condition,scale,raw,preparation+time.monotonic()-tick)
                del m,flat,states
        b=boundary(u,'literal');prior=np.r_[b[0],b[:-1]];n=len(u)-max(HORIZONS)
        consider('boundary_only','previous_logB',{h:expit(prior[:n]) for h in HORIZONS},0.)
        for pen in PENALTIES:
            tick=time.monotonic()
            single=logistic(features[train_idx],y[train_idx].mean(1),pen)
            hazard=predict(single,features).clip(EPS,1-EPS)
            cumulative=np.r_[0.,np.cumsum(np.log1p(-hazard))]
            raw={h:-np.expm1(cumulative[h:h+n]-cumulative[:n]) for h in HORIZONS}
            consider('smooth_hazard',pen,raw,time.monotonic()-tick,{'hazard':single})
        rec['selection_wall_seconds']=time.monotonic()-start
        rec['selected_raw']={n:digest(out/(site+'-'+n+'-raw.npz')) for n in rec['methods']}
        receipts[site]=rec
        print(site,{m:round(r['dev_log_loss'],6) for m,r in rec['methods'].items()},flush=True)
    (out/'SEAL.json').write_text(json.dumps(receipts,indent=2,allow_nan=False)+'\n')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();fit(a.data,a.out)
