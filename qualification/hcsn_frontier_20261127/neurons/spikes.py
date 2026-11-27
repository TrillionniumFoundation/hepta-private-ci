"""Causal electrophysiology validation on EPFL/INCF recordings A, B, C."""
import argparse
import ctypes
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter
from scipy.special import expit
from sklearn.metrics import average_precision_score

ARMS=('literal','smooth','zero','lif','glm','rate')
PAIRS=((.60,1e-2),(.60,1e-4),(1.30,1e-2),(1.30,1e-4))
REGIONS={'train':slice(100,13000),'dev':slice(13100,15500),'cold':slice(15600,19000)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root):
    manifest={}
    for site in 'ABC':
        prefix='Challenge_'+site+'-'
        names=['current_soma','current_dend'] if site=='C' else ['current']
        vs='voltage_soma_allrep' if site=='C' else 'voltage_allrep'
        files=[root/(prefix+k+'.txt') for k in [*names,vs]]
        currents=np.stack([np.loadtxt(p,max_rows=380000).reshape(-1,20).mean(1) for p in files[:-1]],axis=1)
        v=np.loadtxt(files[-1],max_rows=380000);assert v.shape==(380000,{'A':13,'B':9,'C':7}[site])
        events=(v[1:]>0)&(v[:-1]<=0)
        y=np.concatenate([np.zeros_like(events[:1]),events],0).reshape(19000,20,-1).any(1)
        np.savez_compressed(root/(site+'.npz'),currents=currents,y=y)
        manifest[site]={p.name:{'size':p.stat().st_size,'sha256':digest(p)} for p in files}
    return manifest


def current_bank(data):
    prior=np.vstack([np.zeros_like(data[:1]),data[:-1]])
    cols=[]
    for tau in (2,6,16,40,100):
        a=np.exp(-2/tau);cols.append(lfilter([1-a],[1,-a],prior,axis=0))
    x=np.column_stack(cols)
    x=(x-x[REGIONS['train']].mean(0))/np.maximum(x[REGIONS['train']].std(0),1e-7)
    return x


def build_kernel(core):
    sys.path.insert(0,str(core.resolve()))
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reachable'))
    import torch
    from population import BoundaryPopulation
    from he_xiong import Published
    from witness import Population
    from compress import trans
    torch.set_num_threads(1)
    cell=BoundaryPopulation(1,1,atoms=12)
    p=cell.prices;p0=p.p.P0;grid=cell.grid.numpy();pop=Population(cell)
    step=1/4096
    ds=np.arange(-3072,3073)*step
    mats=np.vstack([trans(pop,ds[i:i+256]) for i in range(0,len(ds),256)])
    def lab(x,rel):
        old=cell.grid
        cell.grid=torch.as_tensor(x,dtype=torch.float64)
        with torch.inference_mode():
            e,l=cell.priced_channels(torch.as_tensor([p0*(1+rel)],dtype=torch.float64))
        cell.grid=old
        return np.column_stack([e.ravel().numpy(),l.ravel().numpy()])/20
    center=lab(grid,0);slope=2*(lab(grid,.25)-lab(grid,-.25))
    # Cap the price deviation smoothly about each nominal-principal tangent; preserve
    # derivative in x and principal at .18 and exact affine principal interpolation.
    def tangent(rel):
        ref=lab([.18],rel);ep=1e-5
        derivative=(lab([.18+ep],rel)-lab([.18-ep],rel))/(2*ep)
        return ref+np.tanh((grid[:,None]-.18)*derivative)
    smooth=tangent(0);ss=2*(tangent(.25)-tangent(-.25))
    rng=np.random.default_rng(349168);err=0
    for x in rng.uniform(-.60,.60,150):
        u=(x-ds[0])/step;i=int(u);tm=mats[i]+(u-i)*(mats[i+1]-mats[i])
        err=max(err,np.max(np.abs(tm-pop.matrix(x)[0])))
    meta={'delta_grid_rows':len(ds),'delta_grid_step':step,'random_matrix_max_abs':float(err),'price_anchor':.18,'clock_mapping':'2ms per dimensionless .25','extrapolation_limit':.75}
    return (mats,np.r_[pop.reset,0.],np.column_stack([center,slope]),np.column_stack([smooth,ss]),p.bp*p0/p.B0,step,ds[0]),meta


def features(lib,kernel,x,kind,scale):
    if kind=='glm':return x*scale
    if kind=='rate':return np.zeros((len(x),0))
    mats,reset,literal,smooth,ratio,step,start=kernel
    rng=np.random.default_rng(21903+x.shape[1])
    proj=rng.normal(0,1.,(x.shape[1],12))
    proj/=np.linalg.norm(proj,axis=0);proj[:,0]=0;proj[0,0]=1
    z=np.ascontiguousarray(x@proj*scale)
    out=np.zeros((len(x),12,4))
    price=np.ascontiguousarray(smooth if kind=='smooth' else literal)
    lib.reservoir(ARMS.index(kind),len(x),12,len(reset)-1,len(mats),start,step,ratio,z,mats,reset,price,out)
    assert np.isfinite(out).all()
    return out.reshape(len(x),-1)


def fit(x,y,ridge):
    part=REGIONS['train'];mean=x[part].mean(0);sd=x[part].std(0).clip(1e-7)
    z=(x-mean)/sd;z=np.column_stack([np.ones(len(z)),z]);t=z[part];rate=y[part].mean(1)
    def objective(w):
        eta=t@w;pen=w.copy();pen[0]=0
        return (float(np.mean(np.logaddexp(0,eta)-rate*eta)+.5*ridge*(pen@pen)),
                t.T@(expit(eta)-rate)/len(rate)+ridge*pen)
    w=np.zeros(t.shape[1]);w[0]=np.log(rate.mean()/(1-rate.mean()))
    sol=minimize(objective,w,jac=True,method='L-BFGS-B',options={'maxiter':220,'ftol':1e-11,'gtol':1e-7})
    p=expit(z@sol.x).clip(1e-9,1-1e-9)
    fit_state={'coef':sol.x.tolist(),'mean':mean.tolist(),'sd':sd.tolist(),'success':bool(sol.success),'iterations':int(sol.nit),'optimizer_message':str(sol.message)}
    return p,fit_state


def losses(p,y):
    return -(y*np.log(p[:,None])+(1-y)*np.log1p(-p[:,None]))


def main(args):
    root,out=args.data,args.out;out.mkdir(exist_ok=True,parents=True)
    files=prepare(root);kernel,accuracy=build_kernel(args.core)
    lib=ctypes.CDLL(str(args.lib.resolve()))
    dp=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    lib.reservoir.argtypes=[ctypes.c_int]*5+[ctypes.c_double]*3+[dp]*5
    lib.reservoir.restype=None
    all_scores={};selected={};timing={}
    for site in 'ABC':
        with np.load(root/(site+'.npz')) as raw:
            x=current_bank(raw['currents']);y=raw['y']
        table={};selected[site]={};timing[site]={}
        for kind in ARMS:
            records=[];candidates=[];feature_seconds=0;solver_seconds=0
            for scale in (.6,1.3) if kind!='rate' else (.6,):
                st=time.perf_counter();feat=features(lib,kernel,x,kind,scale);feature_seconds+=time.perf_counter()-st
                for ridge in (1e-2,1e-4) if kind!='rate' else (1e-2,):
                    st=time.perf_counter();pred,fitstate=fit(feat,y,ridge);solver_seconds+=time.perf_counter()-st
                    dev=REGIONS['dev'];v=float(losses(pred[dev],y[dev]).mean())
                    records.append(dict(scale=scale,ridge=ridge,dev_logloss=v,fit=fitstate))
                    candidates.append(pred)
            index=min(range(len(records)),key=lambda i:records[i]['dev_logloss'])
            selected[site][kind]={'candidate':index,'candidates':records}
            timing[site][kind]=dict(feature_s=feature_seconds,solver_s=solver_seconds)
            table[kind]=candidates[index]
        all_scores[site]=table
    payload={'dataset':files,'selection':selected,'timing':timing,'transition_table':accuracy,'source_sha256':{p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name('reservoir.cpp')]}}
    seal=out/'seal.json';seal.write_text(json.dumps(payload,indent=1)+'\n')
    report={}
    for site in 'ABC':
        with np.load(root/(site+'.npz')) as raw:y=raw['y'][REGIONS['cold']]
        preds={k:v[REGIONS['cold']] for k,v in all_scores[site].items()}
        np.savez_compressed(out/(site+'.npz'),y=y,**preds)
        loss={k:losses(v,y) for k,v in preds.items()}
        rng=np.random.default_rng(40954)
        block=np.arange(len(y))//250
        blocks=np.unique(block)
        ids=rng.integers(0,len(blocks),(5000,len(blocks)))
        counts=np.bincount(block)*y.shape[1]
        def boot(x):
            vals=np.bincount(block,weights=x.sum(1));draw=vals[ids].sum(1)/counts[ids].sum(1)
            return [float(x.mean()),*np.quantile(draw,[.025,.975]).tolist()]
        report[site]={'recorded_spikes':int(y.sum()),'duration_s':len(y)*.002,'repeats':y.shape[1],'blocks':len(blocks),'sha256':digest(out/(site+'.npz')),'arms':{},'literal_paired_difference':{k:boot(loss['literal']-loss[k]) for k in ARMS if k!='literal'}}
        for k,v in preds.items():
            wide=np.broadcast_to(v[:,None],y.shape); logloss=loss[k]
            report[site]['arms'][k]=dict(cross_entropy=float(logloss.mean()),brier=float(np.square(wide-y).mean()),ap=float(average_precision_score(y.ravel(),wide.ravel())),rate_bias_hz=float((v.mean()-y.mean())/.002),bits_per_spike=float((loss['rate']-logloss).sum()/np.log(2)/y.sum()))
    (out/'scores.json').write_text(json.dumps({'seal':digest(seal),'cells':report},indent=1)+'\n')
    for site,row in report.items(): print(site,{k:round(v['bits_per_spike'],4) for k,v in row['arms'].items()},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lib','data','out','core'):p.add_argument('--'+k,type=Path,required=True)
    main(p.parse_args())
