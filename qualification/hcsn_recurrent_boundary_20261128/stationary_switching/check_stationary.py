"""Independent continuous-path first-hit and bond pricing test of the switching walls."""
import json
from pathlib import Path
import time
import numpy as np
from scipy.special import ndtr,log_ndtr
from stationary import Economy,Contract,probe
from closed_form import Prices
from dataclasses import replace


def hit_cdf(x,t,mu,sigma):
    width=sigma*np.sqrt(t)
    return ndtr((-x-mu*t)/width)+np.exp(-2*mu*x/sigma**2+log_ndtr((-x+mu*t)/width))


def simulation(economy,wall,V,initial,N,seed):
    """Brownian bridges for survival; sample the time conditional on a hit independently.

    The endpoint is retained only when a path survives the segment. On paths hitting
    this wall, its hitting time is redrawn from the exact truncated first-hit law.
    """
    p=economy.p
    rng=np.random.default_rng(seed)
    state=np.full(N,initial)
    log_asset=np.full(N,np.log(V))
    elapsed=np.zeros(N); discount=np.ones(N); accrued=np.zeros(N)
    hit=np.zeros(N,dtype=bool)
    pending=np.arange(N)
    nstrip=0
    while len(pending):
        ix=pending
        s=state[ix]
        wait=np.full(len(ix),np.inf)
        positive=economy.rates[s]>0
        wait[positive]=rng.exponential(1/economy.rates[s[positive]])
        remaining=p.maturity-elapsed[ix]
        dt=np.minimum(wait,remaining)
        x=log_asset[ix]-np.log(wall[s])
        if np.min(x)<=0:raise ValueError("absorbed start should have already left the active set")
        z=x+economy.mu*dt+p.sigma*np.sqrt(dt)*rng.normal(size=len(ix))
        crossing=(z<=0)|(rng.uniform(size=len(ix))<np.exp(np.minimum(0.,-2*x*z/(p.sigma**2*dt))))
        duration=dt.copy()
        if crossing.any():
            xc,tc=x[crossing],dt[crossing]
            quantile=rng.uniform(size=len(xc))*hit_cdf(xc,tc,economy.mu,p.sigma)
            lo,hi=np.zeros(len(tc)),tc.copy()
            for _ in range(40):
                mid=(lo+hi)/2
                low=hit_cdf(xc,mid,economy.mu,p.sigma)<quantile
                lo=np.where(low,mid,lo)
                hi=np.where(low,hi,mid)
            duration[crossing]=(lo+hi)/2
        q=economy.q[s]
        accrued[ix]+=discount[ix]*economy.c*(-np.expm1(-q*duration))/q
        discount[ix]*=np.exp(-q*duration)
        elapsed[ix]+=duration
        ids=ix[crossing]
        hit[ids]=True
        accrued[ids]+=discount[ids]*p.recovery*wall[s[crossing]]/p.maturity
        mature=(~crossing)&(wait>=remaining)
        ids=ix[mature]; accrued[ids]+=discount[ids]*economy.par
        jump=(~crossing)&(~mature)
        ids=ix[jump]
        log_asset[ids]=np.log(wall[s[jump]])+z[jump]
        state[ids]=1-s[jump]
        strip=log_asset[ids]<=np.log(wall[state[ids]])
        failed=ids[strip]; hit[failed]=True
        accrued[failed]+=discount[failed]*p.recovery*np.exp(log_asset[failed])/p.maturity
        nstrip+=len(failed)
        pending=ids[~strip]
    return dict(paths=N,bond=float(accrued.mean()),bond_se=float(accrued.std(ddof=1)/np.sqrt(N)),
                hit=float(hit.mean()),hit_se=float(hit.std(ddof=1)/np.sqrt(N)),
                jump_strip_hits=nstrip)


def run():
    entry={}
    start=time.perf_counter()
    grids=(96,192,384,768,1536)
    schemes={"fixed":(0.,0.),"permanent_down":(.7,0.),"returning":(.7,.35)}
    probes=[82.,90.,115.]
    for n in grids:
        table={}
        for label,rates in schemes.items():
            solver=Economy(n=n,substeps=n,rates=rates)
            policy=solver.equilibrium()
            assert abs(policy.smooth_fit).max()<5e-7 and policy.equity.min()>=-1e-8
            assert policy.first_hit.min()>-1e-7 and policy.first_hit.max()<1+1e-7
            assert max(policy.stop_residual)<0.
            table[label]=dict(walls=policy.barriers.tolist(),equity=probe(policy,"equity",probes).tolist(),
                              hit=probe(policy,"first_hit",probes).tolist(),bond=probe(policy,"debt",probes).tolist(),
                              stop_residual=policy.stop_residual.tolist(),smooth_fit=policy.smooth_fit.tolist())
        entry[str(n)]=table
    p=Contract()
    analytic={}
    for s,q in enumerate((.01,.05)):
        price=Prices(replace(p,premium=q))
        x=np.log(np.asarray(probes)/price.boundary)
        want=dict(wall=price.boundary,equity=[price.equity(t) for t in x],
                  bond=[price.bond(t) for t in x],hit=[price.hit(t) for t in x])
        observed=entry["1536"]["fixed"]
        errors={a:float(np.max(np.abs(np.array(want[a])-observed[a][s]))) for a in ("equity","bond","hit")}
        errors["wall"]=abs(want["wall"]-observed["walls"][s])
        assert max(errors.values())<.02
        analytic[str(s)]=dict(direct=want,absolute_differences=errors)
    eco=Economy(n=1536,substeps=1536)
    pol=eco.equilibrium()
    expanded=Economy(n=1920,substeps=1536,length=4.375).equilibrium()
    border=float(abs(expanded.barriers-pol.barriers).max())
    assert border<.01
    boots=[]
    for s in (0,1):
        for i,v in enumerate(probes):
            d=simulation(eco,pol.barriers,v,s,300000,126501+100*s+i)
            d.update(state=s,asset=v)
            for k,attr in (("bond","debt"),("hit","first_hit")):
                expected=float(probe(pol,attr,v)[s])
                d[k+"_pde"]=expected
                d[k+"_z"]=(d[k]-expected)/d[k+"_se"]
                assert abs(d[k+"_z"])<5
            boots.append(d)
    # A uniform regime-cost array must reduce to one state for arbitrary switching rates.
    identical=Economy(n=384,substeps=384,premia=(.01,.01)).equilibrium(start=(67.,67.))
    symmetry=max(float(np.max(abs(x[0]-x[1]))) for x in (identical.barriers,identical.equity,identical.debt,identical.first_hit))
    assert symmetry<1e-7
    return dict(probes=probes,rates=schemes,contract=p.__dict__,grids=entry,stationary_formula=analytic,
                monte_carlo=boots,identical_regime_symmetry=symmetry,expanded_domain_wall_error=border,
                elapsed_seconds=time.perf_counter()-start)


if __name__=="__main__":
    result=run()
    Path(__file__).with_name("verified.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(dict(last=result["grids"]["1536"],mc=result["monte_carlo"],
                          extent=result["expanded_domain_wall_error"]),indent=1))
