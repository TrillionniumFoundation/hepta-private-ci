"""Independent inference implementation and paired speaker-level metrics from sealed weights."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from scipy.special import softmax

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def npzd(path):
    with np.load(path,allow_pickle=False) as d:return dict(d)
def time_pair():return np.array([time.process_time(),time.perf_counter()])
def evaluate_cell(drive, table):
    grid=table['fields'].astype('float64');center=table['center'].astype('float64');k=float(table['k'])
    n,T,width=drive.shape
    m=np.full((n,width),.18);prev=np.zeros_like(m);fb=np.zeros_like(m)
    prices=[]
    for index in range(T):
        value=np.tanh(drive[:,index]+fb);bound=np.log1p(k*value)
        pos=np.maximum(0,np.minimum(1.2,m+prev-bound))
        s=(value+1)*((grid.shape[0]-1)/2);r=pos*((grid.shape[1]-1)/1.2)
        i=np.minimum(np.floor(s).astype(int),grid.shape[0]-2)
        j=np.minimum(np.floor(r).astype(int),grid.shape[1]-2)
        a=(s-i)[...,None];b=(r-j)[...,None]
        fields=((1-a)*(1-b)*grid[i,j]+(1-a)*b*grid[i,j+1]
                +a*(1-b)*grid[i+1,j]+a*b*grid[i+1,j+1])
        prices.append(np.concatenate([bound[...,None],fields[...,:3]],axis=-1))
        m=fields[...,3];prev=bound;fb=.15*np.tanh(fields[...,:2]-center[:2]).sum(-1)
    return np.stack(prices,axis=1)
def predict(raw,p,m,table,correction):
    outputs=[]
    for start in range(0,len(raw),128):
        x=np.clip((raw[start:start+128]-p['xm'])/p['xs'],-6,6)
        h=(evaluate_cell(x@m[0],table)[...,0]-p['km'])/p['ks']
        o=evaluate_cell(h@m[1],table).reshape(len(h),-1)
        z=(o-p['hm'])@p['head']+p['bias']
        if correction is not None:
            z+=((x.reshape(len(x),-1)-correction['mean'])/correction['scale'])@correction['w']
        outputs.append(z)
    return np.vstack(outputs)

def cold(a):
    seal=json.loads(a.seal.read_text())
    for name,dig in seal['candidates'].items():assert sha(a.models/name)==dig
    assert sha(a.law)==seal['physical_table']
    for name in ('A','B'):
        f=a.fresh/(name+'.npz');assert sha(f)==seal['fresh'][f.name]
    assert sha(a.prior/'old_test.npz')==seal['data']['old_test.npz']
    a.out.mkdir(parents=True,exist_ok=True)
    reference={}
    for key,path in [('old',a.prior/'old_test.npz'),('A',a.fresh/'A.npz'),('B',a.fresh/'B.npz')]:
        with np.load(path) as f:
            for k in ('y','speaker','record'):reference[key+'_'+k]=f[k]
    np.savez_compressed(a.out/'targets.npz',**reference)
    methods=('keep','joint','receiver','bp','lora','ridge','wrong')
    for arch in ('literal','smooth'):
        for seed in (271,577,911):
            fold=a.models/f'{arch}_{seed}';records={};times={}
            for name in methods:
                for b in ((0,) if name=='keep' else (3,15,60)):
                    t=time_pair();p=npzd(fold/'parent.npz');tab=npzd(a.law if arch=='literal' else fold/'smooth.npz')
                    m=[p['encoder'],p['W']];corr=None
                    if name!='keep':
                        data=npzd(fold/f'{name}_{b}.npz')
                        if name=='ridge':corr=data
                        else:m=[data['sender'],data['receiver']]
                    ident=f'{name}_{b}';times[ident]={}
                    for key,path in [('old',a.prior/'old_test.npz'),('A',a.fresh/'A.npz'),('B',a.fresh/'B.npz')]:
                        with np.load(path) as f:x=f['x'].astype('float64')
                        records[ident+'_'+key]=predict(x,p,m,tab,corr)
                        if key=='A':times[ident]['through_A']=(time_pair()-t).tolist()
                    times[ident]['both']=(time_pair()-t).tolist()
            np.savez_compressed(a.out/f'{arch}_{seed}.npz',**records)
            (a.out/f'{arch}_{seed}.json').write_text(json.dumps(times,indent=2)+'\n')
    (a.out/'complete.json').write_text(json.dumps({p.name:sha(p) for p in a.out.iterdir() if p.name!='complete.json'},indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('models','prior','law','fresh','seal','out'):p.add_argument(n,type=Path)
    cold(p.parse_args())
