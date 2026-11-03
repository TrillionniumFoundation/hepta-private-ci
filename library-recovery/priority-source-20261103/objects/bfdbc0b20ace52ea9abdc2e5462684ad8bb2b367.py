"""Independent finite-difference check for the simplified stopping ODE only.

Original coupled He-Xiong rollover equations are NOT represented here.
We solve a *fixed* candidate boundary b and a truncated asset interval;
this is a cross-check of the analytic expression and smooth pasting, not
an independent search for the endogenously optimal exercise boundary.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.linalg import solve_banded
from simplified_stopping import SimpleStopping, evaluate


def solve(p:SimpleStopping,upper_ratio:float=35.0,n:int=500,
          right_bc:str='analytic_value'):
    p.validate()
    if upper_ratio<=2 or not isinstance(n,int) or n<32 or n>10000:
        raise ValueError('invalid grid')
    b=float(evaluate(p,1.0)['boundary'])
    v=np.linspace(b, b*upper_ratio,n+1)
    dx=v[1]-v[0]
    # Evaluate source PDE at interior nodes.
    r,d,s,k=p.r,p.payout,p.sigma,p.cost
    vi=v[1:-1]
    a=.5*s*s*vi*vi/(dx*dx)
    drift=(r-d)*vi/(2*dx)
    lo=a-drift
    middle=-2*a-r
    hi=a+drift
    rhs= k-d*vi
    # Boundary b: exact value matching. High-V boundary condition is an
    # asymptotic approximation E(V)~V-K/r with known finite-V bias.
    gamma=float(evaluate(p,1.0)['gamma'])
    boundary_correction=(b/gamma)*np.power(b/v[-1],gamma)
    if right_bc == 'analytic_value':
        right=v[-1]-k/r+boundary_correction
    elif right_bc == 'leading_asymptote':
        right=v[-1]-k/r
    else:
        raise ValueError('unknown right_bc')
    rhs[-1]-=hi[-1]*right
    ab=np.zeros((3,n-1))
    ab[0,1:]=hi[:-1]
    ab[1,:]=middle
    ab[2,:-1]=lo[1:]
    internal=solve_banded((1,1),ab,rhs)
    numerical=np.concatenate(([0.0],internal,[right]))
    # Analytic value E(V)=V-K/r + (b/g)*(b/V)**g.
    analytic=v-k/r+(b/gamma)*np.power(b/v,gamma)
    analytic[0]=0.0
    err=float(np.max(np.abs(numerical-analytic)))
    bd_deriv=(-3*numerical[0]+4*numerical[1]-numerical[2])/(2*dx)
    return {'n':n,'upper_ratio':upper_ratio,'right_bc':right_bc,
            'max_abs_error':err,
            'relative_error_vs_asset_scale':float(err/max(v[-1],1e-300)),
            'boundary_derivative_numeric':float(bd_deriv),
            'boundary_derivative_analytic':0.0,
            'exact_dirichlet_right_correction':float(analytic[-1]-right),
            'scope':'independent truncated-domain FD for simple stopping ODE'}
