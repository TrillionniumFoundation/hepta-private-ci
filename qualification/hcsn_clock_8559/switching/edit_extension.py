"""Independent nonlinear inverse mapping for conditional walls and a wider multi-start retention test."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from edit import BASE,forward,observations
from smooth import residual

LOW=np.log([1e-6,1e-6,1e-5,1e-5]);HIGH=np.log([.12,.20,6.,6.])
def pack(t):return np.log([t[0],t[1]-t[0],t[2],t[3]])
def unpack(u):
    x=np.exp(u);x[1]+=x[0];return x
def main(out):
    rows=[]
    for n in (1,2,4):
        seg=(70*n,12*n,80*n);M=48*n
        baseline,barr=forward(BASE,seg,M)
        control,_=forward(np.array([.0101,.0405,.115,.17]),seg,M)
        for target_id,ms in enumerate([(-.05,.05),(.1,0.),(0.,.1),None]):
            wanted=baseline+np.r_[ms,0.,0.] if ms is not None else control
            starts=(BASE,np.array([.004,.06,.50,.50]),np.array([.002,.05,.02,1.0]),np.array([.01,.075,1.,.02]))
            for method in ('wall_inverse','joint_wide'):
                if ms is None and method=='wall_inverse':continue
                for k,origin in enumerate(starts[:1] if method=='wall_inverse' else starts):
                    free=2 if method=='wall_inverse' else 4
                    def law(z):
                        v=pack(BASE);v[:free]=z;return unpack(v)
                    def objective(z):
                        tt=law(z)
                        if free==2:return residual(wanted[:2],tt[:2],tt[2:],seg,M)/5.
                        val,_=residual(wanted[:2],tt[:2],tt[2:],seg,M,save=True)
                        return np.r_[np.array(val['smooth_residual'])/5.,np.array(val['equity_at_100'])-wanted[2:]]
                    result=least_squares(objective,pack(origin)[:free],bounds=(LOW[:free],HIGH[:free]),max_nfev=135,
                           jac='3-point',diff_step=4e-5,gtol=2e-9,xtol=1e-10,ftol=1e-10)
                    tt=law(result.x);ach,arr=forward(tt,seg,M);err=ach-wanted
                    row=dict(grid=n,method=method,target_id=target_id,requested=wanted.tolist(),origin=origin.tolist(),
                             solution=tt.tolist(),cost=float(result.cost),nfev=result.nfev,active_limits=result.active_mask.tolist(),
                             achieved=ach.tolist(),cold_error=err.tolist(),other_observable_change=(observations(arr)-observations(barr)).tolist())
                    rows.append(row);out.write_text(json.dumps(rows,indent=1)+'\n')
                    print(n,method,target_id,k,'error',err.tolist(),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();main(a.out)
