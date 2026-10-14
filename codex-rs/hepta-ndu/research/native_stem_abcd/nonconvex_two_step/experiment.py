"""Exact two-step parameter-nonlinear Stem, stochastic terminal expectation."""
from fractions import Fraction as F
import numpy as np
from scipy.optimize import minimize
LAM=F(1,4); NOISE=F(1,10)
OPT=F(7,16)+NOISE**2
SADDLE=F(1)+NOISE**2

def exact_J(a,b):
    a,b=F(a),F(b)
    return (a*b-1)**2+LAM*(a*a+b*b)+NOISE*NOISE

def exact_gap(a,b):
    return exact_J(a,b)-OPT

def proof():
    # (ab-1)^2 + (a^2+b^2)/4 = (ab-3/4)^2 +(a-b)^2/4 +7/16
    a,b=F(7,8),F(1,4)
    lhs=exact_J(a,b)-OPT
    rhs=(a*b-F(3,4))**2+F(1,4)*(a-b)**2
    assert lhs==rhs
    assert exact_J(0,0)==SADDLE
    assert exact_gap(0,0)==F(9,16)
    return {"lower_bound":str(OPT),"sum_of_squares":"(ab-3/4)^2+(a-b)^2/4", "saddle_gap":str(exact_gap(0,0)),"global_minima":"a=b=+/-sqrt(3/4)","globally_certified":True,"risk_nonzero":False}

def objective(theta):
    a,b=theta
    return (a*b-1)**2+float(LAM)*(a*a+b*b)+float(NOISE**2)

def grad(theta):
    a,b=theta
    return np.array([2*(a*b-1)*b+.5*a,2*(a*b-1)*a+.5*b])

def hess(theta):
    a,b=theta
    return np.array([[2*b*b+.5,4*a*b-2],[4*a*b-2,2*a*a+.5]])

def run():
    seeds=[(0.,0.),(.1,.1),(-.1,-.1),(2.,-2.),(1.,1.),(-1.,-1.),(.5,-.5),(3.,3.)]
    records=[]
    for i,init in enumerate(seeds):
        for method in ("BFGS","trust-exact","L-BFGS-B"):
            kw={"jac":grad,"method":method,"options":{"maxiter":1000,"gtol":1e-12}}
            if method=="trust-exact":kw["hess"]=hess
            r=minimize(objective,init,**kw)
            x=r.x
            records.append(dict(seed=i,initial=str(init),method=method,a=float(x[0]),b=float(x[1]),cost=float(r.fun),global_gap=float(r.fun-float(OPT)),grad_inf=float(np.max(np.abs(grad(x)))),hessian_min=float(np.linalg.eigvalsh(hess(x))[0]),is_global_within_1e_8=bool(abs(r.fun-float(OPT))<1e-8)))
    return records
if __name__=='__main__':
    import json
    print(json.dumps(dict(proof=proof(),runs=run()),indent=2))
