"""Stationarity, transient response and continuous regenerative frequency under a clamped drive."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.special import log_ndtr

from verify import RESET,SIGMA,MU


def passage(x,t,mu):
    x=np.asarray(x,dtype=float);t=np.asarray(t,dtype=float)
    d=SIGMA*np.sqrt(t)
    return np.exp(np.logaddexp(log_ndtr((-x-mu*t)/d),-2*mu*x/SIGMA**2+log_ndtr((-x+mu*t)/d))).clip(0,1)


def cumulative(t,delay,mu):
    n=np.arange(1,int(np.ceil(t/delay))+1)
    tim=t-(n-1)*delay
    return float(passage(n*RESET,tim,mu).sum())


def invariant(M):
    z=np.eye(len(M))-M.T;z[-1]=1
    rhs=np.zeros(len(M));rhs[-1]=1
    v=np.linalg.solve(z,rhs)
    assert np.min(v)>-1e-12 and np.max(abs(v@M-v))<1e-12 and abs(v.sum()-1)<1e-12
    return v


def main(core):
    sys.path.insert(0,str(core.resolve()));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reachable'))
    from population import BoundaryPopulation
    from witness import Population
    import torch
    torch.set_num_threads(1);nominal=[]
    for n in (8,12):
        cell=BoundaryPopulation(1,1,n);pop=Population(cell)
        M=pop.matrix(0)[0];stationary=invariant(M)
        for b in np.linspace(-.16,.16,11):
            p=stationary@pop.matrix(-b)[0]
            trace={1:float(p[-1])}
            for j in range(2,2049):
                p=p@M
                if j in (4,16,64,256,1024,2048):trace[j]=float(p[-1])
            principal=cell.prices.p.P0+cell.prices.B0*np.expm1(b)/cell.prices.bp
            E,L=cell.priced_channels(torch.tensor([principal],dtype=torch.float64))
            A=stationary[:-1]
            nominal.append({'atoms':n,'log_boundary':float(b),'prev_equilibrium_to_new_boundary_flow':trace,'stationary_flow_per_tick':float(stationary[-1]),'stationary_equity':float(A@E.detach().numpy().ravel()),'stationary_loss':float(A@L.detach().numpy().ravel())})
    domain=[]
    for top in (1.30,2.60,3.90,5.20,6.50):
        from verify import kernels
        n=round(top/.055);grid=(np.arange(n)+.5)*top/n
        q,f,r=kernels(grid,.25);M=np.vstack([np.column_stack([q,f]),np.r_[r,0]])
        v=invariant(M)
        domain.append({'top':top,'atoms':n,'effective_spacing':top/n,'stationary_intensity_per_time':float(v[-1]/.25)})
    rr=[]
    shift=.15
    for u in (-.5,0,.10,MU/shift,.25,.5,1.,2.):
        mu=MU-shift*u
        if abs(mu)<1e-12:mu=0.
        h=1. if mu<=0 else float(np.exp(-2*mu*RESET/SIGMA**2))
        rr.append({'drive':u,'physical_mu':mu,'probability_of_ever_hitting':h,'expected_total_hits':None if mu<=0 else h/(1-h),'renewal_rate_limit':0. if mu>=0 else 1/(.25+RESET/abs(mu)),'expected_N_over_T':{t:cumulative(t,.25,mu)/t for t in (1,10,100,1000)}})
    return {'sigma':SIGMA,'published_log_mu':MU,'reset':RESET,'continuous_refractory':.25,'native':nominal,'domain':domain,'drift_extension':rr}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--core',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    d=main(a.core);a.out.write_text(json.dumps(d,indent=1)+'\n')
    print([(r['atoms'],r['stationary_flow_per_tick'],r['prev_equilibrium_to_new_boundary_flow'][1]) for r in d['native'] if abs(r['log_boundary'])>.155])
    print(d['domain']);print(d['drift_extension'][1])
