"""Calibrate conditional finite-maturity walls and retain two equity values without sequence BP."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from scipy.optimize import least_squares
from smooth import residual,fit
from sensitivity import derivatives

BASE=np.array([.01,.04,.12,.16]);SCALE=np.array([.01,.01,.10,.10])
LOW=np.array([.0001,.016,.002,.002]);HIGH=np.array([.015,.09,.5,.5])
def forward(theta,seg,M):
    info,values=fit(theta[:2],theta[2:],seg,M,initial=(69.4,72.2))
    if not info['success']:raise ValueError('equilibrium did not converge')
    wall=np.array(info['walls']);equity=np.array(info['equity_at_100'])
    return np.r_[wall,equity],values
def observations(arr):
    query=[75.,90.,120.,140.]
    return np.stack([np.interp(query,arr['v'],row) for key in ('equity','debt') for row in arr[key]])
def clocked(fn):
    st=time.perf_counter();cpu=time.process_time();out=fn()
    return out,dict(wall_s=time.perf_counter()-st,cpu_s=time.process_time()-cpu)
def main(out):
    rows=[]
    for n in (1,2,4):
        seg=(70*n,12*n,80*n);M=48*n
        (original,arr),base_time=clocked(lambda:forward(BASE,seg,M))
        def jacobian():
            A,B=derivatives(original[:2],BASE,seg,M)
            walls=-np.linalg.solve(A,B)
            equities=[]
            for k in range(4):
                h=1e-4*SCALE[k];delta=np.zeros(4);delta[k]=h
                plus,_=forward(BASE+delta,seg,M);minus,_=forward(BASE-delta,seg,M)
                equities.append((plus[2:]-minus[2:])/(2*h))
            return np.vstack([walls,np.stack(equities,axis=1)])*SCALE
        J,jtime=clocked(jacobian)
        sv=np.linalg.svd(J,compute_uv=False)
        for movement in [(-.05,.05),(.10,0.),(0.,.10)]:
            target=original+np.r_[movement,0.,0.]
            candidates=dict(unchanged=(BASE,dict(wall_s=0.,cpu_s=0.)))
            for method,dim in [('wall_linear',2),('joint_linear',4)]:
                res,cost=clocked(lambda:BASE+SCALE*np.linalg.lstsq(J[:dim],(target-original)[:dim],rcond=1e-8)[0])
                candidates[method]=(res,cost)
            def joint():
                def f(v):
                    theta=BASE+SCALE*v
                    info,_=residual(target[:2],theta[:2],theta[2:],seg,M,save=True)
                    return np.r_[np.asarray(info['smooth_residual'])/5.,np.asarray(info['equity_at_100'])-target[2:]]
                answer=least_squares(f,np.zeros(4),bounds=((LOW-BASE)/SCALE,(HIGH-BASE)/SCALE),
                          max_nfev=120,ftol=1e-11,xtol=1e-11,gtol=1e-11,jac='3-point',diff_step=2e-5)
                return np.clip(BASE+SCALE*answer.x,LOW,HIGH)
            candidates['joint_finite']=clocked(joint)
            for name,(theta,clock) in candidates.items():
                admitted=bool(np.all(theta>=LOW) and np.all(theta<=HIGH))
                row=dict(size=n,method=name,theta=theta.tolist(),target_move=movement,target=target.tolist(),admissible=admitted,
                         candidate_wall_cpu=clock,base_setup=base_time,linear_preparation=jtime if 'linear' in name else None,
                         scaled_jacobian_singular_values=sv.tolist())
                if admitted:
                    (real,vals),replay=clocked(lambda:forward(theta,seg,M))
                    row.update(achieved=real.tolist(),residual=(real-target).tolist(),cold_replay=replay,
                               other_observable_change=(observations(vals)-observations(arr)).tolist())
                rows.append(row)
                print(n,name,movement,'admitted',admitted,'residual',row.get('residual'),flush=True)
            out.write_text(json.dumps(rows,indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();main(a.out)
