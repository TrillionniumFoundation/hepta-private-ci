"""Compile fixed He-Xiong parameters to a C1 neural kernel in float64.

The original analytic formulas are offline references. Runtime interpolation
is an explicitly measured numerical approximation, not a new analytic solution.
"""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
from scipy.interpolate import PchipInterpolator, CubicHermiteSpline
from scipy.special import ndtr

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from analytic import HXModel, Parameters
from analytic.hx_model import exp_cdf, exp_phi


def first_hit_derivative(model,x):
    """Analytic derivative dF/dx of Eq.(9), at horizon maturity."""
    x=np.asarray(x)
    a,s=model.a,model.s
    return (-exp_phi(0.,-x/s-a*s)/s
            -2*a*exp_cdf(-2*a*x,-x/s+a*s)
            -exp_phi(-2*a*x,-x/s+a*s)/s)


def patch_constants(model,epsilon_scaled=.02):
    epsilon=epsilon_scaled*model.s
    value=float(model.first_hit(epsilon,model.p.maturity)[0])
    derivative=float(first_hit_derivative(model,epsilon))
    loss=1-value
    ratio=-epsilon*derivative/loss
    if not (loss>0 and 0<=ratio<=3):
        raise ValueError("Chosen first-hit patch is not certified monotone")
    # Fpatch(t)=1-A*t^2-B*t^3, t=x/epsilon.
    A=3*loss+epsilon*derivative
    B=-2*loss-epsilon*derivative
    return dict(epsilon=epsilon,epsilon_scaled=epsilon_scaled,
                value=value,derivative=derivative,A=A,B=B,monotonicity_ratio=ratio)


def reference_gates(z,params=Parameters(),epsilon_scaled=.02):
    """Full-formula reference, including the stated neural risk modification."""
    m=HXModel(params)
    p=patch_constants(m,epsilon_scaled)
    z=np.asarray(z,dtype=np.float64)
    distance=m.s*np.abs(z)
    original=m.first_hit(distance,m.p.maturity)[0]
    t=np.minimum(distance/p["epsilon"],1.)
    patched=np.where(distance<p["epsilon"],1-p["A"]*t*t-p["B"]*t*t*t,original)
    risk=np.where(z<0,.5*patched,1-.5*patched)
    safe=m.s*np.maximum(-z,0)
    value=m.equity(safe)
    call=np.where(z<0,value/(value+m.boundary),0.)
    return risk,call


def build_table(params=Parameters(),nodes=4097,epsilon_scaled=.02,distance_limit=8.):
    """Return numeric ndarray pytree; fixed financial parameters are metadata only.

    Coefficients are computed in float64. Runtime may cast the numeric pytree to
    float32; gradients then train states and neural parameters, not financial theta.
    """
    if nodes<65 or distance_limit<=0:
        raise ValueError("Need at least 65 nodes and positive distance limit")
    model=HXModel(params)
    patch=patch_constants(model,epsilon_scaled)
    s=model.s
    call_limit=np.log1p(distance_limit/s)
    tc=np.linspace(0,call_limit,nodes)
    xc=s*np.expm1(tc)
    equity=model.equity(xc)
    if np.min(equity)<-1e-8:
        raise ValueError("Negative equity prevents the bounded Call normalization")
    ac=equity/(equity+model.boundary)
    call_pchip=PchipInterpolator(tc,ac)
    slopes=call_pchip.derivative()(tc)
    slopes[0]=0.
    call_spline=CubicHermiteSpline(tc,ac,slopes)
    risk_limit=max(16.,2*abs(model.a*s)+12.)
    ur=np.linspace(epsilon_scaled,risk_limit,nodes)
    xr=s*ur
    fr=model.first_hit(xr,params.maturity)[0]
    risk_pchip=PchipInterpolator(ur,fr)
    risk_slopes=risk_pchip.derivative()(ur)
    risk_slopes[0]=patch["derivative"]*s
    risk_spline=CubicHermiteSpline(ur,fr,risk_slopes)
    # Runtime tails match the implemented spline's value and physical slope.
    call_slope=slopes[-1]/(s+distance_limit)
    call_tail_rate=call_slope/(1-ac[-1])
    risk_tail_rate=-risk_slopes[-1]/fr[-1] if fr[-1]>1e-300 else 0.
    if min(call_tail_rate,risk_tail_rate)<0:
        raise ValueError("Tail extension would violate monotonicity")
    table={"call_coeff":call_spline.c,"call_step":np.asarray(tc[1]),
           "call_limit":np.asarray(call_limit),"call_distance_limit":np.asarray(distance_limit),
           "call_end":np.asarray(ac[-1]),"call_tail_rate":np.asarray(call_tail_rate),
           "risk_coeff":risk_spline.c,"risk_step":np.asarray(ur[1]-ur[0]),
           "risk_limit":np.asarray(risk_limit),"risk_end":np.asarray(fr[-1]),
           "risk_tail_rate":np.asarray(risk_tail_rate),"diffusion_scale":np.asarray(s),
           "epsilon_scaled":np.asarray(epsilon_scaled),"patch_A":np.asarray(patch["A"]),
           "patch_B":np.asarray(patch["B"]),"boundary":np.asarray(model.boundary)}
    return table


def save_table(path,table,params=Parameters()):
    path=Path(path)
    np.savez_compressed(path,**table)
    record=dict(financial_parameters=asdict(params),fixed_parameters=True,
                file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                numeric_bytes=sum(v.nbytes for v in table.values()))
    path.with_suffix(".json").write_text(json.dumps(record,indent=2)+"\n")
    return record
