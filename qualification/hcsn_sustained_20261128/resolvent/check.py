"""Cross-check the closed resolvent prices against independent adaptive integration."""
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.integrate import quad,solve_ivp

from closed_form import Contract,Prices
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"paper_check"))
try:
    from hx_reference import hit
except ModuleNotFoundError:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"paper"))
    from hx_reference import hit


def run():
    g=np.random.default_rng(78604)
    contracts=[Contract(premium=s) for s in (0.,1e-10,.01,.02,.04)]
    for _ in range(25):
        contracts.append(Contract(r=g.uniform(.04,.12),payout=g.uniform(.012,.038),sigma=g.uniform(.17,.34),
             recovery=g.uniform(.38,.75),tax=g.uniform(.15,.32),coupon=g.uniform(4.8,8.),
             principal=g.uniform(48,76),maturity=g.uniform(.6,1.8),premium=g.uniform(0,.055)))
    err={k:0. for k in ("boundary","equity","bond","credit_loss","first_hit","discounted_hit","smooth_cash_moment")}
    def record(k,d):err[k]=max(err[k],abs(float(d)))
    rows=[]
    for p in contracts:
        law=Prices(p)
        q=law.q;c=law.c;par=law.par;eta=law.eta
        def h(x,discount):return hit(x,p.maturity,law.mu,p.sigma,discount)
        I=lambda rate:quad(lambda x:math.exp(-eta*x)*h(x,rate),0,np.inf,epsabs=2e-13,epsrel=2e-12)[0]
        f0,g0=I(0),I(q)
        B=(((1-p.tax)*p.coupon+par-c/q)/eta-law.A*(1/eta-f0)+c/q*g0)/(p.payout/(eta-1)+p.recovery*g0/p.maturity)
        record("boundary",law.boundary-B)
        def debt(x):return c/q+law.A*(1-h(x,0))+(p.recovery*B/p.maturity-c/q)*h(x,q)
        def ode(x,y):
            cf=p.payout*B*math.exp(x)-(1-p.tax)*p.coupon+debt(x)-par
            return y[1],2*(p.r*y[0]-law.mu*y[1]-cf)/law.var
        sol=solve_ivp(ode,(0,.9),(0.,0.),dense_output=True,rtol=3e-12,atol=1e-13)
        assert sol.success
        for x in (0.,.0001,.01,.18,.4,.7,.9):
            record("equity",law.equity(x)-sol.sol(x)[0]);record("bond",law.bond(x)-debt(x))
            record("credit_loss",law.credit_loss(x)-(c/q+law.A-debt(x)))
            record("first_hit",law.hit(x)-h(x,0));record("discounted_hit",law.hit(x,q)-h(x,q))
        record("smooth_cash_moment",law.cash_integral(eta,0,math.inf))
        if len(rows)<5:
            x=math.log(100/law.boundary)
            rows.append(dict(premium=p.premium,B=law.boundary,equity=law.equity(x),loss=law.credit_loss(x),F=law.hit(x),G=law.hit(x,q)))
    if max(err.values())>2e-8:raise ValueError(err)
    return dict(contracts=len(contracts),points_per_contract=7,absolute_errors=err,table=rows)


if __name__=="__main__":
    v=run();s=json.dumps(v,indent=2)+"\n"
    Path(__file__).with_name("verified.json").write_text(s)
    print(s)
