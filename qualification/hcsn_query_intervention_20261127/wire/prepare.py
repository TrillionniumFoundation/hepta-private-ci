"""Frozen published EPFL forecasts plus reconstructed causal population states at each test anchor."""
import argparse
from pathlib import Path
import hashlib
import json
import sys
import time
import numpy as np
from scipy.special import expit,logit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model import GRID,DT,MU,EPS,HORIZONS,kernel,inputs,reset_vector
from hx_reference import Parameters,StationaryFirm

SIZE=3390;CHOICES=(2,6);RESET=reset_vector()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def prepare(out):
    out.mkdir(parents=True,exist_ok=True);t=time.monotonic();cpu=time.process_time()
    params=Parameters();xs=np.linspace(-1,1,1001);base=StationaryFirm(params,1).boundary_closed()
    lut=np.array([np.log(StationaryFirm(params,np.exp(1.5*u)).boundary_closed())-np.log(base) for u in xs])
    seal=json.loads((ROOT/'SEAL.json').read_text());allrec=[];scales=[];models=[]
    for site in ('A','B','C'):
        orig=ROOT/'input'/(site+'.npz');measured=ROOT/'measured'/(site+'.npz')
        with np.load(orig) as z:drive=inputs(z['currents'])[0];event=z['y']
        with np.load(measured) as z:anch=z['anchors'];forecast=z['literal_query'];targets=z['y_count'];n=int(z['trial_count'])
        assert len(anch)==SIZE and np.array_equal(anch,np.arange(anch[0],anch[0]+SIZE))
        model=seal[site]['methods']['literal_query'];scale=float(model['law_setting']);scales.append(scale);models.append(model['calibrator'])
        b=np.interp(drive,xs,lut);last_b=np.r_[b[0],b[:-1]]
        state=np.r_[RESET,0.];states=np.zeros((len(drive),len(state)))
        for start in range(0,len(drive),256):
            idx=np.arange(start,min(start+256,len(drive)))
            qs=kernel(GRID[None,:]+(last_b[idx]-b[idx])[:,None],MU-scale*.25*drive[idx])
            for j,q in zip(idx,qs):
                states[j]=state;live=state[:-1]@q
                fired=state[:-1].sum()-live.sum();state=np.r_[live+state[-1]*RESET,max(0.,fired)]
        forcing=np.stack([drive[anch+j] for j in range(max(HORIZONS))],axis=1)
        np.savez(out/f'{site}.npz',state=states[anch],prev=drive[anch-1],forcing=forcing,probs=forecast,count=targets,rep=n,spike=event[anch])
        allrec.append(dict(site=site,source_sha=sha(orig),archive_sha=sha(measured),slots=SIZE,trials=n))
    np.savez(out/'lut.npz',x=xs,y=lut)
    meta=dict(sources=allrec,scales=scales,calibrators=models,initial_base=base,state_construction_s=time.monotonic()-t,
              state_construction_cpu_s=time.process_time()-cpu)
    (out/'meta.json').write_text(json.dumps(meta,indent=1)+'\n')
class Panel:
    def __init__(self,folder):
        self.folder=folder;self.meta=json.loads((folder/'meta.json').read_text())
        with np.load(folder/'lut.npz') as z:self.x=z['x'];self.lut=z['y']
        self.data=[]
        for site in ('A','B','C'):
            with np.load(folder/(site+'.npz')) as z:self.data.append(dict(z))
        self.all=np.concatenate([r['probs'] for r in self.data]);self.pair=self.all[:,[1,3]]
        self.obs=np.concatenate([r['count']/int(r['rep']) for r in self.data]);self.params=Parameters()
    def dynamic(self,i,h,given=None):
        site,j=divmod(i,SIZE);r=self.data[site];d=r['forcing'][j,:h] if given is None else np.asarray(given,dtype=float)
        prev=r['prev'][j];scale=self.meta['scales'][site];chain=np.r_[prev,d]
        if given is None:b=np.interp(chain,self.x,self.lut)
        else:
            b=np.array([np.log(StationaryFirm(self.params,np.exp(1.5*u)).boundary_closed()/self.meta['initial_base']) for u in chain])
        qs=kernel(GRID[None,:]+(b[:-1]-b[1:])[:,None],MU-scale*.25*d)
        before=r['state'][j];a=before[:-1].copy()
        for t,q in enumerate(qs):
            a=a@q
            if t==0:a+=before[-1]*RESET
        raw=np.clip(1-a.sum(),EPS,1-EPS);cal=self.meta['calibrators'][site]
        x=(np.array([logit(raw),np.log(h)])-cal['mean'])/cal['std'];w=np.array(cal['w'])
        return np.float32(expit(x@w[1:]+w[0]))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();prepare(a.out)
