"""Floating comparison of quadrature-trained two-weight solutions; not a proof."""
import csv, json
import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.optimize import root
from numerical_checks import exact_branches, gradient, objective
from certificate import A,B

def rules():
    nodes=np.array([-1.,-2**-.5,0.,2**-.5,1.])
    weights=np.array([1/30,4/15,2/5,4/15,1/30])
    yield 'cc5',nodes,weights
    x,w=leggauss(5)
    yield 'gl5',x,w/2
    x,w=leggauss(17)
    yield 'gl17',x,w/2

def g_rule(v,x,w):
    z=x+(v[0]-1)*x*x+v[1]*x**3-.5*x**4
    gp=2*z+.2*(np.tanh(.5*(.4*z+.025))+np.tanh(.4*z-.025))
    return .9*np.array([w@(gp*x*x),w@(gp*x**3)])

def run():
    result=[]
    for name,x,w in rules():
        found=root(lambda v:g_rule(v,x,w),[1.36,-1.4],tol=1e-12)
        if not np.isfinite(found.x).all() or np.max(abs(g_rule(found.x,x,w)))>1e-9:
            raise RuntimeError(f'{name}: numerical solve failed')
        a,b=found.x
        result.append(dict(rule=name,a=float(a),b=float(b),
                           residual=float(max(abs(g_rule(found.x,x,w)))),
                           exact_population_float_cost=float(objective(found.x,80)),
                           exact_candidate_float_cost=float(objective([float(A),float(B)],80)),
                           numerically_observed_gap=float(objective(found.x,80)-objective([float(A),float(B)],80)),
                           certified=False))
    return result

if __name__=='__main__':
    d=run()
    with open('QUADRATURE_DIAGNOSTICS.csv','x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(d[0]));w.writeheader();w.writerows(d)
    print(json.dumps(d,indent=2))
