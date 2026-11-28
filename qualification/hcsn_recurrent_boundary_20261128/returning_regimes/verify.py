"""Independent path recursion, finite-difference tangents and mesh sensitivity."""
from functools import lru_cache
import json
import math
from pathlib import Path
import time
import numpy as np
from scipy.integrate import quad, solve_ivp
from lattice import Contract, Prices, replace, solve


def direct_recursion(model, steps, years, rates):
    """Slow scalar recursion, ODE transition weights and first-hit density integrals."""
    p = Contract()
    premia = (.01, .05)
    assets = model.assets
    dt = p.maturity / steps
    par, coupon = p.principal/p.maturity, p.coupon/p.maturity
    mu = p.r-p.payout-p.sigma**2/2
    widths = np.diff(np.log(assets))
    dx = widths.mean()
    moments = ((p.sigma**2*dt + (mu*dt)**2)/dx**2, mu*dt/dx)
    travel = ((-1, (moments[0]-moments[1])/2), (0, 1-moments[0]),
              (1, (moments[0]+moments[1])/2))
    prices = [Prices(replace(p, premium=l)) for l in premia]
    Q = np.array([[-rates[0], rates[0]], [rates[1], -rates[1]]])
    def kernel(s, discounted):
        def f(t, y):
            w = y[:2]
            return np.r_[w@Q-(p.r+np.asarray(premia))*w*discounted, coupon*w.sum()]
        final = solve_ivp(f, [0, dt], np.r_[np.eye(2)[s], 0.], rtol=2e-13, atol=5e-15,
                          method="DOP853").y[:, -1]
        return final[:2], final[2]
    plain = [kernel(s, False)[0] for s in range(2)]
    discounted = [kernel(s, True) for s in range(2)]
    def expected(i, probs, function):
        return sum(float(probs[z])*w*function(z, min(max(i+j, 0), len(assets)-1))
                   for z in range(2) for j,w in travel)
    @lru_cache(None)
    def endpoint(s,i,j):
        B, v, q = prices[s].boundary, assets[i], p.r+premia[s]
        if v <= B:
            return (p.recovery*v/p.maturity, 1.)
        if j == 0:
            return (par, 0.)
        x, t = math.log(v/B), j*dt
        def density(u):
            return x/(p.sigma*math.sqrt(2*math.pi*u**3))*math.exp(-(x+mu*u)**2/(2*p.sigma**2*u))
        f = quad(density,0,t,epsabs=1e-13)[0]
        g = quad(lambda u: math.exp(-q*u)*density(u),0,t,epsabs=1e-13)[0]
        return (coupon/q+math.exp(-q*t)*(par-coupon/q)*(1-f)
                +(p.recovery*B/p.maturity-coupon/q)*g, f)
    H = round(years/dt)
    @lru_cache(None)
    def issue(n,s,i,j):
        return discounted[s][1]+expected(i,discounted[s][0],lambda z,k: bond(n+1,z,k,j-1))
    @lru_cache(None)
    def continuation(n,s,i):
        if n == H:
            return prices[s].equity(math.log(assets[i]/prices[s].boundary))
        cash = issue(n,s,i,steps)-par-(1-p.tax)*p.coupon
        return (assets[i]*(1-math.exp(-p.payout*dt)) + cash*(1-math.exp(-p.r*dt))/p.r
                + math.exp(-p.r*dt)*expected(i,plain[s],lambda z,k:max(0.,continuation(n+1,z,k))))
    @lru_cache(None)
    def bond(n,s,i,j):
        if n==H:
            return endpoint(s,i,j)[0]
        if continuation(n,s,i)<=0:
            return p.recovery*assets[i]/p.maturity
        return par if j==0 else issue(n,s,i,j)
    @lru_cache(None)
    def hit(n,s,i,j):
        if n==H:
            return endpoint(s,i,j)[1]
        if continuation(n,s,i)<=0:
            return 1.
        return 0. if j==0 else expected(i,plain[s],lambda z,k:hit(n+1,z,k,j-1))
    indices = [0,*range(len(assets)//2-3, len(assets)//2+4),len(assets)-1]
    errs = []
    for s in range(2):
        for i in indices:
            desired = [max(0.,continuation(0,s,i)), bond(0,s,i,steps), hit(0,s,i,steps)]
            got = [model.equity[s,i],model.bond[s,i],model.hit[s,i]]
            errs.append(np.abs(np.asarray(desired)-got))
    return dict(tested=len(errs),max_absolute=dict(zip(("equity","debt","hit"),map(float,np.max(errs,axis=0)))))


def describe(panel):
    def values(a):
        return [float(np.interp(90.,panel.assets,row)) for row in a]
    return dict(walls=panel.walls.tolist(), grid_brackets=panel.grid_brackets.tolist(),
                equity_at_90=values(panel.equity), hit_at_90=values(panel.hit),
                loss_at_90=values(panel.loss))


def check():
    started = time.perf_counter()
    small = solve(steps=6, years=.5, rates=(.7,.35), log_half_width=1.)
    slow = direct_recursion(small,6,.5,(.7,.35))
    assert max(slow["max_absolute"].values())<5e-10
    # All derivative predictions are compared against re-solving, including decisions.
    rates=(.7,.35)
    n=48
    parent=solve(steps=n,rates=rates)
    eps=1e-5
    plus,minus=[solve(steps=n, rates=(rates[0]+d,rates[1]), gradients=False) for d in (eps,-eps)]
    err={}
    for name in ("wall","equity","loss","hit"):
        attr="walls" if name=="wall" else name
        reference = (getattr(plus,attr)-getattr(minus,attr))/(2*eps)
        actual = getattr(parent,name+"_gradient")
        err[name]=dict(max_absolute=float(np.max(np.abs(actual-reference))),
                       relative_to_peak=float(np.max(np.abs(actual-reference))/max(1.,np.max(np.abs(reference)))))
    assert np.array_equal(plus.policy, minus.policy) and np.array_equal(parent.policy,minus.policy)
    assert max(y["relative_to_peak"] for y in err.values())<5e-6
    same = solve(steps=48, premia=(.01,.01))
    sym = {key:float(np.max(np.abs(getattr(same,key)[0]-getattr(same,key)[1])))
           for key in ("walls","equity","loss","hit")}
    assert max(sym.values())<5e-10
    large=solve(steps=n,log_half_width=3.5,gradients=False)
    expanded_diff = [max(abs(x-y) for x,y in zip(describe(large)[k],describe(parent)[k]))
                     for k in ('walls','equity_at_90','loss_at_90','hit_at_90')]
    assert max(expanded_diff)<1e-8
    table = {}
    for resolution in (24,48,96,192,384):
        table[resolution]={}
        for arm,transitions in (("stationary",(0.,0.)),("irreversible",(.7,0.)),("returning",rates)):
            panel=solve(steps=resolution,rates=transitions, gradients=False)
            assert panel.hit.min()>=-1e-10 and panel.hit.max()<=1+1e-10
            assert np.min(panel.equity)>=0 and np.min(panel.loss)>-2e-6
            table[resolution][arm]=describe(panel)
    return dict(parameters=dict(contract=Contract().__dict__,premia=[.01,.05],rates=rates,
                                contract_horizon=1.,switching_horizon=2.,asset_probe=90.,
                                permanent_state_after_horizon=True),
                slow_reference=slow, contact_stable_for_finite_difference=True, fd_eps=eps,
                grid_gradient_error=err, d_walls_d_upward_rate_at_48=parent.wall_gradient.tolist(),
                equal_regime_symmetry_error=sym, expanded_domain_max_difference=expanded_diff,
                stationary_continuous_walls=[Prices(replace(Contract(),premium=q)).boundary for q in (.01,.05)],
                resolution_table=table, elapsed_s=time.perf_counter()-started)


if __name__=="__main__":
    result=check()
    Path(__file__).with_name("verified.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="resolution_table"},indent=2))
    print(json.dumps(result["resolution_table"][384],indent=2))
