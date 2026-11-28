"""Input-only stationary valuation and straight moving-wall population features."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from scipy.signal import lfilter
from scipy.special import logit

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from hx_reference import Parameters, StationaryFirm
from model import GRID,DT,MU,kernel,query,trace,HORIZONS,EPS

PHASE=np.arange(30,481,2); H=np.asarray(HORIZONS)
BS=np.repeat([0,4000,8000],3*len(PHASE)); CY=np.tile(np.repeat([0,1,2],len(PHASE)),3);PH=np.tile(PHASE,9)
A=(BS+CY*500+PH).astype(np.int32);AMP=BS//4000+1

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tables(path):
    if path.exists():
        with np.load(path) as z:return dict(z)
    p=Parameters();us=np.linspace(-1,1,81);base=StationaryFirm(p,1).boundary_closed()
    prices=[];walls=[]
    for u in us:
        f=StationaryFirm(p,np.exp(1.5*u));b=f.boundary_closed();walls.append(np.log(b/base))
        prices.append([f.equity_green(b*np.exp(x),b) for x in GRID])
    f=StationaryFirm(p,1);f1=np.array([f.first_passage(x)[0] for x in GRID])
    arrays=dict(us=us,price=np.asarray(prices),wall=np.asarray(walls),f1=f1)
    np.savez(path,**arrays);return arrays

def transition(u,b,step):
    old=np.r_[b[0],b[:-1]];d=MU-.7*.25*u
    if step:return kernel(GRID[None,:]+(old-b)[:,None],d)
    return kernel(np.broadcast_to(GRID,(len(u),len(GRID))),d-(b-old)/DT)

def make(x,center,sd,tab):
    raw=np.clip((x.astype(float)-center)/sd,-12,12);lag=[raw]
    for tau in (2,6,16,40,100):
        aa=np.exp(-2/tau);lag.append(lfilter([1-aa],[1,-aa],raw))
    u=np.tanh(.50*lag[0]+.35*lag[2]+.15*lag[3])
    b=np.interp(u,tab['us'],tab['wall']);mid=len(tab['us'])//2;db=(tab['wall'][mid+1]-tab['wall'][mid-1])/(tab['us'][mid+1]-tab['us'][mid-1])
    vals={}
    for name,wall,step in [('fixed',b*0.,False),('tangent',db*u,False),('step',b,True),('moving',b,False)]:
        mat=transition(u,wall,step);state,err=trace(mat)
        if err>1e-9:raise ArithmeticError('population mass')
        qs=query(mat,state);vals[name]=np.stack([logit(np.clip(qs[h][A],EPS,1-EPS)) for h in H],axis=1).astype(np.float32)
        if name=='moving':
            v0=u[A-1];pr=np.stack([np.interp(v0,tab['us'],tab['price'][:,k]) for k in range(len(GRID))],1)
            vals['dual']=np.column_stack([np.sum(state[A,:-1]*pr,axis=1),state[A,:-1]@tab['f1']]).astype(np.float32)
        del mat,state
    z=np.column_stack([v[A-1] for v in lag])
    old=u[A-1];all_features=[]
    for h in H:
        fu=np.stack([u[A+j] for j in range(h)],1);fr=np.stack([raw[A+j] for j in range(h)],1)
        zpath=np.column_stack([fu.mean(1),fu.min(1),fu.max(1),fu[:,-1]-old,fr.mean(1),fr.min(1),fr.max(1)])
        shared=np.column_stack([z,np.tanh(z),z*z,zpath,np.tanh(zpath),zpath*zpath,
                    AMP,CY,PH/500,np.sin(PH*(2*np.pi/500)),np.cos(PH*(2*np.pi/500)),np.full(len(A),np.log(h))])
        all_features.append(shared)
    vals['shared']=np.stack(all_features,1).astype(np.float32)
    return vals

def run(data,cache,table,expected):
    cache.mkdir(parents=True,exist_ok=True);tab=tables(table);last=time.monotonic()
    while True:
        done=0;handled=False
        for rec in sorted(data.glob('[0-9]*.json')):
            sid=rec.stem;receipt=json.loads(rec.read_text());org=data/f'{sid}.npz';finished=cache/f'{sid}.json'
            if not receipt['admitted']:continue
            if finished.exists():done+=1;continue
            assert digest(org)==receipt['npz_sha256']
            first=time.monotonic();outputs={};qas={}
            with np.load(org) as z:
                ref=z['x1_0'].astype(float);center=np.mean(ref[1600:3900]);sd=max(np.std(ref[:1500]),1e-8)
                for typ in ('1','2'):
                    x=z['x'+typ+'_0'];other=z['x'+typ+'_1'];equal=np.array_equal(x,other)
                    for rep in ([0] if equal else [0,1]):
                        signal=x if rep==0 else other;f=make(signal,center,sd,tab)
                        path=cache/f'{sid}-{typ}_{rep}.npz';np.savez_compressed(path,**f);outputs[f'{typ}_{rep}']={'file':path.name,'sha':digest(path)}
                    if equal:outputs[typ+'_1']=outputs[typ+'_0']
                    rms=[float(np.sqrt(np.mean((x[k:k+1499]-center)**2))) for k in (0,4000,8000)]
                    inactive=np.r_[x[1510:3990],x[5510:7990]]
                    qas[typ]=dict(repeats_identical=bool(equal),active_rms=rms,amplitude_ratios=(np.asarray(rms)/rms[0]).tolist(),
                        quiet_to_low_rms=float(np.std(inactive)/rms[0]),within_cycle_rel_l2=float(np.linalg.norm(x[0:500]-x[500:1000])/np.linalg.norm(x[0:500]-center)))
            summary=dict(sid=sid,source=digest(org),outputs=outputs,input_qa=qas,sec=time.monotonic()-first,table_sha=digest(table))
            finished.write_text(json.dumps(summary,indent=1)+'\n');print(sid,round(summary['sec'],2),flush=True)
            last=time.monotonic();handled=True;done+=1
        if done>=expected:return
        if not handled:
            if time.monotonic()-last>3600:raise RuntimeError('timed out waiting for complete sources')
            time.sleep(5)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('data','cache','table'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--expected',type=int,required=True);a=p.parse_args();run(a.data,a.cache,a.table,a.expected)
