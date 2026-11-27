"""First-hit and renewal references for an absorbing drift-diffusion with resetting."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.special import ndtr

SIGMA=.23
MU=.08-.02-.5*SIGMA**2
RESET=.30


def cdf(x,t):
    if t<=0:return 0.
    d=SIGMA*np.sqrt(t)
    return ndtr((-x-MU*t)/d)+np.exp(-2*MU*x/SIGMA**2)*ndtr((-x+MU*t)/d)


def renewal(t,delay):
    result=0.
    for n in range(1,1000):
        term=cdf(n*RESET,t-(n-1)*delay)
        result+=term
        if term<1e-20:return result
    raise ValueError('insufficient reference terms')


def kernels(grid,dt):
    drift=MU*dt;scale=SIGMA*np.sqrt(dt);x=grid[:,None]
    cuts=np.r_[0,(grid[1:]+grid[:-1])/2]
    w=np.exp(-2*MU*x/SIGMA**2)
    cumulative=ndtr((cuts-x-drift)/scale)-w*ndtr((cuts+x-drift)/scale)
    q=np.diff(np.column_stack([cumulative,1-w]),axis=1).clip(min=0)
    hit=cdf(grid,dt)
    if abs(q.sum(1)+hit-1).max()>2e-13:raise ValueError('transition mass error')
    initial=np.zeros(len(grid))
    right=np.searchsorted(grid,RESET)
    weight=(RESET-grid[right-1])/(grid[right]-grid[right-1])
    initial[right]=weight;initial[right-1]=1-weight
    return q,hit,initial


def run(grid,dt,T,delays):
    q,f,reset=kernels(grid,dt);steps=int(round(T/dt))
    actual=float(1-(reset@np.linalg.matrix_power(q,steps)).sum())
    one=float(cdf(RESET,T));discrete_initial=float(reset@cdf(grid,T))
    report={'first_hit':actual,'exact_first':one,'exact_first_for_discrete_initial':discrete_initial,'first_error':actual-one,'counts':{}}
    for label,n in delays:
        m=reset.copy();pending=np.zeros(n)
        num=0.;mass_error=0
        for s in range(steps):
            flow=m@f;num+=flow
            if n:
                slot=s%n;released=pending[slot];pending[slot]=flow
            else:released=flow
            m=m@q+released*reset
            mass_error=max(mass_error,abs(m.sum()+pending.sum()-1))
        exact=renewal(T,n*dt)
        report['counts'][label]={'delay':n*dt,'exact_same_delay':exact,'exact_zero_delay':renewal(T,0),'actual':float(num),'error_same_delay':float(num-exact),'total_mass_error':float(mass_error)}
    return report


def main(out):
    results=[]
    for n in (8,12,24,48,96):
        grid=np.linspace(.015,1.30,n)
        for dt in (.25,.125,.0625,.03125,.015625):
            for t in (1.,2.):
                r=run(grid,dt,t,[('one_tick',1),('fixed_quarter',round(.25/dt))])
                results.append(dict(family='native_endpoints',n=n,top=1.30,dt=dt,T=t,**r))
    for n in (8,12):
        grid=np.linspace(.015,1.30,n)
        for exp in (7,9,12,16):
            dt=2.**(-exp)
            for t in (1.,2.):
                # Very many small steps: power gives the exact finite-model no-hit probability.
                r=run(grid,dt,t,[])
                results.append(dict(family='fixed_grid_time_only',n=n,top=1.30,dt=dt,T=t,**r))
    for top in (1.3,2.6):
        for n,dt in ((24,.125),(48,.0625),(96,.03125),(192,.015625),(384,.0078125)):
            grid=(np.arange(n)+.5)*top/n
            for t in (1.,2.):
                r=run(grid,dt,t,[('one_tick',1),('fixed_quarter',round(.25/dt)),('instant',0)])
                results.append(dict(family='midpoint_coupled',n=n,top=top,dt=dt,T=t,**r))
    obj={'sigma':SIGMA,'mu':MU,'reset':RESET,'rows':results}
    out.write_text(json.dumps(obj,indent=1)+'\n')
    for r in results:
        if r['T']==2 and ((r['family']=='midpoint_coupled' and r['top']==2.6) or (r['family']=='native_endpoints' and r['dt']==.25 and r['n']<=12) or (r['family']=='fixed_grid_time_only' and r['n']==12)):
            print(r['family'],r['n'],r['dt'],r['first_hit'],r['exact_first'],r['counts'].get('fixed_quarter',{}).get('error_same_delay'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);main(p.parse_args().out)
