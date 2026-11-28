"""A monotone time-lattice policy for a deterministic announced intensity change."""
import argparse
import json
import time
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import sys

import numpy as np
from scipy.special import log_ndtr, ndtr

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hx_reference import Parameters, StationaryFirm

TIMES=(0.,1/32,1/16,1/8,1/4,1/2,1.)
SITES=(65.,75.,100.,125.)
REGIMES=((1,1),(4,4),(1,4),(4,1),(1,2))


def maturity_price(firm, assets, remaining):
    """Stationary conditional debt values at all nonnegative residual maturities."""
    p=firm.params
    tau=np.atleast_1d(remaining).astype(float)[:,None]
    b=firm.boundary_closed()
    x=np.maximum(0.,np.log(assets/b))[None,:]
    scale=p.volatility*np.sqrt(np.maximum(tau,1e-30))
    def n(y):
        return (-x+y*p.volatility**2*tau)/scale
    ff=ndtr(n(-firm.a))+np.exp(-2*firm.a*x+log_ndtr(n(firm.a)))
    gg=np.exp((-firm.a+firm.z_hat)*x+log_ndtr(n(-firm.z_hat)))
    gg+=np.exp((-firm.a-firm.z_hat)*x+log_ndtr(n(firm.z_hat)))
    value=firm.c/firm.q+np.exp(-firm.q*tau)*(firm.p-firm.c/firm.q)*(1.-ff)
    value+=(p.recovery*b/p.maturity-firm.c/firm.q)*gg
    value=np.where(tau<=0,firm.p,value)
    return np.where(assets[None,:]<=b,p.recovery*assets[None,:]/p.maturity,value)


@lru_cache(maxsize=24)
def terminal(n, post, offset):
    p=Parameters()
    dt=1./n
    dx=p.volatility*np.sqrt(2*dt)
    j=np.arange(int(np.floor(np.log(18./75.)/dx)),int(np.ceil(np.log(600./75.)/dx))+1)
    v=75.*np.exp((j+offset)*dx)
    firm=StationaryFirm(p,post)
    b=firm.boundary_closed()
    debt=maturity_price(firm,v,np.arange(n+1)*dt)
    equity=np.array([firm.equity_green(asset,b) for asset in v])
    return v,debt,equity


def expected(y, lo, hi, stay, up, down, out):
    """Trinomial expectation over one step; linear-in-asset ghost extrapolation."""
    out[:]=stay*y
    out[...,1:]+=down*y[...,:-1]
    out[...,:-1]+=up*y[...,1:]
    out[...,0]+=down*lo
    out[...,-1]+=up*hi
    return out


def march(n, pre, post, offset=0., store=False):
    started=time.monotonic()
    p=Parameters();dt=1./n
    before=StationaryFirm(p,pre);after=StationaryFirm(p,post)
    v,terminal_d,terminal_e=terminal(n,post,offset)
    dx=np.log(v[1]/v[0]);mean=before.mu*dt
    second=(p.volatility**2*dt+mean**2)/dx**2
    up,down=(second+mean/dx)/2.,(second-mean/dx)/2.
    stay=1.-up-down;assert min(up,down,stay)>0
    rdiscount=np.exp(-p.rate*dt);qdiscount=np.exp(-before.q*dt)
    annuity=-np.expm1(-before.q*dt)/before.q
    equity_annuity=-np.expm1(-p.rate*dt)/p.rate
    recovery=p.recovery*v/p.maturity
    operating=p.payout*v-(1.-p.tax_benefit)*p.coupon-before.p
    d=terminal_d.copy();e=terminal_e.copy()
    work_d=np.empty_like(d);work_e=np.empty_like(e)
    rows=[];mismatch=[]
    alive_record=[];issue_record=[];equity_record=[]
    trace=float('inf')
    for k in range(n+1):
        alive=e>0.
        if not alive.any() or alive.all() or (np.diff(alive.astype(int))<0).any():
            raise RuntimeError('Unexpected stopping region at step '+str(k))
        if store:
            alive_record.append(alive.copy());issue_record.append(d[-1].copy());equity_record.append(e.copy())
        first=np.flatnonzero(alive)[0]
        if k in {round(n*t) for t in TIMES}:
            rows.append(dict(years_before=k/n,grid_barrier_interval=v[first-1:first+1].tolist(),
                         assets=list(SITES),equity=np.interp(np.log(SITES),np.log(v),e).tolist(),
                         full_issue=np.interp(np.log(SITES),np.log(v),d[-1]).tolist(),
                         current_stationary_boundary=before.boundary_closed(),
                         frozen_decision_disagreement=v[alive != (v>before.boundary_closed())].tolist()))
        if k==n:break
        # Debt j at the current date rolls into debt j-1 one step later. The incumbent
        # zero-maturity claim receives recovery if the firm defaults on that date.
        lo=d[:-1,0]+(d[:-1,1]-d[:-1,0])*(np.exp(-dx)-1)/(np.exp(dx)-1)
        hi=d[:-1,-1]+(d[:-1,-1]-d[:-1,-2])*(np.exp(dx)-1)/(1.-np.exp(-dx))
        dd=expected(d[:-1],lo,hi,stay,up,down,work_d[1:])
        dd*=qdiscount
        dd+=before.c*annuity
        issue=dd[-1]
        lo_e=e[0]+(e[1]-e[0])*(np.exp(-dx)-1)/(np.exp(dx)-1)
        hi_e=e[-1]+(e[-1]-e[-2])*(np.exp(dx)-1)/(1.-np.exp(-dx))
        cont=expected(e,lo_e,hi_e,stay,up,down,work_e)
        cont*=rdiscount
        cont+=(operating+issue)*equity_annuity
        new_alive=cont>0
        cont[~new_alive]=0.
        work_d[0]=before.p
        work_d[:,~new_alive]=recovery[~new_alive]
        d,work_d=work_d,d;e,work_e=work_e,e
    ret=dict(n=n,pre=pre,post=post,offset=offset,p_up=up,p_down=down,p_stay=stay,
             state_count=len(v),grid_dx=dx,rows=rows,wall_s=time.monotonic()-started)
    cache={}
    if store:
        cache=dict(v=v,alive=np.asarray(alive_record),issue=np.asarray(issue_record),
                   equity=np.asarray(equity_record),up=up,down=down,step=dt,pre=pre,post=post,n=n)
    return ret,cache


def stationary_at_sites():
    values={}
    for i in (1,2,4):
        f=StationaryFirm(Parameters(),i);b=f.boundary_closed()
        values[str(i)]=dict(boundary=b,equity=[f.equity_green(v,b) for v in SITES],
              issue=maturity_price(f,np.array(SITES),[1.])[0].tolist())
    return values


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--levels',type=int,nargs='+',default=[64,128,256,512])
    ap.add_argument('--offset',type=float,default=0.);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    report=dict(parameters=asdict(Parameters()),sites=SITES,stationary=stationary_at_sites(),runs=[])
    for n in a.levels:
        for pre,post in REGIMES:
            run,cache=march(n,pre,post,a.offset,store=(n==256 and a.offset==0. and (pre,post) in [(1,4),(1,1)]))
            report['runs'].append(run)
            if cache:np.savez_compressed(a.out/f'policy_{n}_{pre}_{post}.npz',**cache)
            (a.out/'grid.json').write_text(json.dumps(report,indent=1,allow_nan=False)+'\n')
            print(n,pre,post,round(run['wall_s'],2),flush=True)
