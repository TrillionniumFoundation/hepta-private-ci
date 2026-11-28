"""Independent cycle quadrature and an adaptive backward boundary-value solver."""
import argparse
import cmath
from dataclasses import replace
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.integrate import quad,solve_bvp
from scipy.optimize import brentq
from scipy.special import roots_legendre

from halfline import Stationary,Scalars
from stability import Transfer


def main(price_path):
    sys.path.insert(0,str(price_path.parent))
    from closed_form import Prices,Contract
    cell=Stationary()
    quote=Prices(replace(Contract(),principal=61.68*(1+.28*(-.8))))
    a,d=.3,.25
    cutoff=32.
    # Independent Gaussian quadrature of published point quotes; isolate B*exp(x)
    # analytically, so the unused tail of the residual has a uniform error bound.
    n,w=roots_legendre(64)
    nodes,ws=[],[]
    for lo,hi in ((0.,.3),(.3,1.),(1.,3.),(3.,8.),(8.,16.),(16.,cutoff)):
        nodes.extend((n+1)*(hi-lo)/2+lo)
        ws.extend(w*(hi-lo)/2)
    x=np.array(nodes); weights=np.array(ws)
    # Feynman-Kac representation bounds E-B exp x uniformly by B+sup|cash-δV|/r.
    equity=np.array([quote.equity(t) for t in x])
    loss=np.array([quote.credit_loss(t) for t in x])
    constant=-(1-quote.p.tax)*quote.p.coupon+quote.c/quote.q+quote.A-quote.par
    rec=quote.p.recovery*quote.boundary/quote.p.maturity-quote.c/quote.q
    bound_eq=quote.boundary+(abs(constant)+abs(quote.A)+abs(rec))/quote.p.r

    def independent(u):
        lam=u/(quote.var/2)
        dens=np.empty_like(x)
        mask=x<a
        dens[mask]=-np.expm1(-lam*x[mask])
        dens[~mask]=-np.expm1(-lam*a)*np.exp(-lam*(x[~mask]-a))
        cyc=(a+d*u)
        mass=a/cyc
        mean=float(sum(weights*dens*x)/cyc/mass)
        # E(x) and B exp(x) share the same leading term. Beyond twelve
        # log units direct floating-point subtraction discards digits only
        # in their bounded difference, downweighted by exp(-lambda*x).
        ee=float((sum(weights*dens*(equity-quote.boundary*np.exp(x)))
                   +quote.boundary*np.expm1(a)*lam/(lam-1))/(20*cyc))
        ll=float(sum(weights*dens*loss)/(20*cyc))
        tail=(-math.expm1(-lam*a))*math.exp(-lam*(cutoff-a))/(lam*cyc*20)*bound_eq
        return u+.03355-.7*(-.8)+.6*np.tanh(ee)*(a-mean)-4.1*np.tanh(ll),ee,ll,mean,tail

    roots=[]; checks=[]
    for lo,hi in ((.031,.06),(.1,.2),(.25,.4)):
        root=brentq(lambda u:independent(u)[0],lo,hi)
        raw=independent(root)
        closed=cell.stationary(root)
        roots.append(root)
        checks.append(dict(u=root,flux=1/(a/root+d),independent_E=raw[1],independent_L=raw[2],
                           independent_mean=raw[3],bounded_omitted_equity_tail=raw[4],
                           absolute_error_vs_closed=[abs(raw[1]-closed[2]),abs(raw[2]-closed[3]),abs(raw[3]-closed[4])]))
    u=roots[1]
    model=Transfer(cell,u)
    def solve_adjoint(freq,edge):
        # Solve sV=D V''-u V'+f, V(0)=exp(-sd)V(a).
        # Split at reset to impose the delayed value at an interior point.
        # The independent calculation uses three far cutoffs solely to
        # verify the infinite-domain analytic characteristic.
        m0,m1,mE,mL=model.weights
        def forcing(x):
            return m0+m1*x+mE*np.array([quote.equity(v) for v in x])+mL*np.array([quote.credit_loss(v) for v in x])
        def rhs(z,y):
            ans=[]
            for j,(o,l) in enumerate(((0.,a),(a,edge-a))):
                val,grad=y[2*j:2*j+2]
                f=forcing(o+l*z)
                ans.extend((l*grad,l*(freq*val+u*grad-f)/cell.D))
            return np.array(ans)
        far=(mE*quote.boundary*math.exp(edge)/(freq+u-cell.D)
             +m1*(edge/freq-u/freq**2)+(m0+mE*constant/quote.p.r)/freq)
        def bc(y0,y1):
            return [y0[0]-math.exp(-freq*d)*y0[2],y1[0]-y0[2],y1[1]-y0[3],y1[2]-far]
        mesh=np.linspace(0,1,129)
        sol=solve_bvp(rhs,bc,mesh,np.zeros((4,len(mesh))),tol=1e-7,max_nodes=12000)
        if not sol.success:
            raise RuntimeError(sol.message)
        lam=u/cell.D
        low=quad(lambda z:math.exp(-lam*z)*sol.sol(z/a)[0],0,a,epsabs=1e-11)[0]
        high=quad(lambda z:math.exp(-lam*(z-a))*sol.sol((z-a)/(edge-a))[2],a,edge,epsabs=1e-11)[0]
        response=lam*(low+math.expm1(-lam*a)*high)/(a+d*u)
        return dict(s=freq,truncation_for_independent_adjoint=edge,bvp=response,closed=model.response(freq),
                    difference=response-model.response(freq),nodes=len(sol.x))
    adjoint=[solve_adjoint(f,e) for f in (.48,.51) for e in (4.,6.,8.)]
    class Complex(Scalars):
        exp=staticmethod(cmath.exp)
        sqrt=staticmethod(cmath.sqrt)
        tanh=staticmethod(cmath.tanh)
    grid=np.geomspace(.0001,20,1200)
    finite_band=[]
    for u in roots:
        m=Transfer(Stationary(Complex),u)
        characteristic=1-np.array([m.response(1j*f) for f in grid])
        closest=np.argmin(abs(characteristic))
        finite_band.append(dict(u=u,n=len(grid),frequency_min=grid[0],frequency_max=grid[-1],
               min_modulus=abs(characteristic[closest]),at_angular_frequency=grid[closest],
               phase_change_over_pi=(np.unwrap(np.angle(characteristic))[-1]-np.unwrap(np.angle(characteristic))[0])/np.pi))
    if max(max(c["absolute_error_vs_closed"]) for c in checks)>1e-6:
        raise ValueError(checks)
    if max(abs(c["difference"]) for c in adjoint if c["truncation_for_independent_adjoint"]==8)>1e-6:
        raise ValueError(adjoint)
    return dict(renewal=checks,independent_delay_adjoint=adjoint,
                positive_real_mode=brentq(lambda f:model.response(f)-1,.48,.51),
                exploratory_finite_band_only=finite_band)

if __name__=="__main__":
    arg=argparse.ArgumentParser()
    arg.add_argument("reference",type=Path)
    a=arg.parse_args()
    result=main(a.reference)
    Path(__file__).with_name("verified.json").write_text(json.dumps(result,indent=2)+"\n")
    print(result)
