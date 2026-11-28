"""Independent complex boundary-value checks near the closest imaginary-axis margins."""
import argparse
import cmath
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import numpy as np
from scipy.integrate import quad,solve_bvp
from scipy.interpolate import CubicSpline

from halfline import Stationary,Scalars
from stability import Transfer


def run(path):
    sys.path.insert(0,str(path.parent))
    from closed_form import Prices, Contract
    class Complex(Scalars):
        exp=staticmethod(cmath.exp)
        sqrt=staticmethod(cmath.sqrt)
        tanh=staticmethod(cmath.tanh)
    p=Stationary(Complex)
    quote=Prices(replace(Contract(),principal=61.68*(1+.28*(-.8))))
    x=np.linspace(0,18,3601)
    equity=CubicSpline(x,[quote.equity(y) for y in x])
    loss=CubicSpline(x,[quote.credit_loss(y) for y in x])
    roots=json.loads(Path(__file__).with_name("sharp_roots.json").read_text())
    cases=[]
    for j,w in [(0,.145),(0,.257),(2,.145),(2,1.0)]:
        u=float(roots[j]["inward_drift"][0])
        tr=Transfer(p,u)
        s=1j*w
        a,d=.30,.25
        lam=u/(quote.var/2)
        c0,cx,ce,cl=[float(q.real) for q in tr.weights]
        const=-(1-quote.p.tax)*quote.p.coupon+quote.c/quote.q+quote.A-quote.par
        def forcing(x):return c0+cx*x+ce*equity(x)+cl*loss(x)
        test=[]
        for edge in (8.,12.,18.):
            def rhs(t,y):
                parts=[]
                for k,(lo,span) in enumerate(((0,a),(a,edge-a))):
                    value,deriv=y[2*k:2*k+2]
                    parts.extend([span*deriv,span*(s*value+u*deriv-forcing(lo+span*t))/(quote.var/2)])
                return np.array(parts)
            far=ce*quote.boundary*np.exp(edge)/(s+u-quote.var/2)+cx*(edge/s-u/s**2)+(c0+ce*const/quote.p.r)/s
            def bc(ya,yb):
                return [ya[0]-np.exp(-s*d)*ya[2],yb[0]-ya[2],yb[1]-ya[3],yb[2]-far]
            grid=np.linspace(0,1,151)
            def real_rhs(t,y):
                val=rhs(t,y[:4]+1j*y[4:])
                return np.vstack((val.real,val.imag))
            def real_bc(ya,yb):
                val=np.array(bc(ya[:4]+1j*ya[4:],yb[:4]+1j*yb[4:]))
                return np.r_[val.real,val.imag]
            sol=solve_bvp(real_rhs,real_bc,grid,np.zeros((8,len(grid))),tol=5e-7,max_nodes=12000)
            if not sol.success:raise RuntimeError(sol.message)
            def initial_part(x):return np.exp(-lam*x)*(sol.sol(x/a)[0]+1j*sol.sol(x/a)[4])
            def tail_part(x):return np.exp(-lam*(x-a))*(sol.sol((x-a)/(edge-a))[2]+1j*sol.sol((x-a)/(edge-a))[6])
            l=quad(initial_part,0,a,complex_func=True)[0]
            h=quad(tail_part,a,edge,complex_func=True)[0]
            val=lam*(l+math.expm1(-lam*a)*h)/(a+d*u)
            exact=tr.response(s)
            test.append(dict(cutoff=edge,response=[val.real,val.imag],absolute_difference=abs(val-exact),
                             mesh_points=len(sol.x)))
        if test[-1]["absolute_difference"]>1e-5:
            raise ValueError(test)
        cases.append(dict(root=j,omega=w,analytic=[exact.real,exact.imag],separate_numerical_results=test))
    return dict(method="adaptive complex boundary-value problem; increasing numerical far cutoff on cross-check only",
                scenarios=cases)
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("reference",type=Path)
    v=ap.parse_args()
    results=run(v.reference)
    Path(__file__).with_name("outer_verified.json").write_text(json.dumps(results,indent=2)+"\n")
    print([(c["root"],c["omega"],c["separate_numerical_results"][-1]["absolute_difference"]) for c in results["scenarios"]])
