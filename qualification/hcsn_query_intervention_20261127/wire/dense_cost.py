"""Source-side live cost of evaluating the dense stream a tolerance sender inspects."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from scipy.special import expit,logit
from prepare import Panel,GRID,MU,RESET,EPS,HORIZONS,kernel

def run(pan,horizons):
    tic=time.monotonic();cpu=time.process_time()
    outputs=[];steps=0
    for k,r in enumerate(pan.data):
        drive=np.r_[r['forcing'][:,0],r['forcing'][-1,1:]];old=r['prev'][0];num=len(r['state'])
        bb=np.interp(np.r_[old,drive],pan.x,pan.lut);mat=kernel(GRID[None,:]+(bb[:-1]-bb[1:])[:,None],MU-pan.meta['scales'][k]*.25*drive)
        a=r['state'][:,:-1].copy();cal=pan.meta['calibrators'][k];w=np.array(cal['w']);res=[]
        for j in range(max(horizons)):
            a=np.einsum('ti,tij->tj',a,mat[j:j+num])
            if j==0:a+=r['state'][:,-1,None]*RESET
            if j+1 in horizons:
                raw=np.clip(1-a.sum(1),EPS,1-EPS);feat=np.column_stack([logit(raw),np.full(num,np.log(j+1))])
                res.append(expit((feat-cal['mean'])/cal['std']@w[1:]+w[0]).astype(np.float32))
        outputs.append(np.stack(res,1));steps+=max(horizons)*num
    wall=time.monotonic()-tic;cost=time.process_time()-cpu;vec=np.concatenate(outputs);ref=pan.all[:,[HORIZONS.index(x) for x in horizons]]
    return {'wall_s':wall,'cpu_s':cost,'projected_transitions_applied':steps,'queries':vec.size,'max_abs':float(abs(vec-ref).max())}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cache',type=Path);p.add_argument('out',type=Path);a=p.parse_args();pan=Panel(a.cache)
    record={str(h):[run(pan,h) for _ in range(5)] for h in ((2,6),tuple(HORIZONS))}
    a.out.write_text(json.dumps(record,indent=1)+'\n')
