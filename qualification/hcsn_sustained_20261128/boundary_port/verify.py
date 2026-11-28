"""Certified near-zero transmission, finite edits and independent physical pricing."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import numpy as np
from scipy.optimize import brentq
from scipy.special import roots_legendre

from port import BASE,RESET,TREF,BRACKETS,drive,rate,port_gain,read_first_hit
from halfline import Stationary
from enclose import Dual,Rigorous,enclosing_numbers
from mpmath import iv


def local(roots):
    v=Dual("-.8",1)
    pv=Stationary(Rigorous,drive=v)
    rho=pv.B.d/pv.B.v
    report={}
    for i,name in ((0,"low"),(2,"high")):
        u=iv.mpf(roots[i]["inward_drift"])
        sv=pv.stationary(Dual(u))[0].d
        su=Stationary(Rigorous).stationary(Dual(u,1))[0].d
        wall=rho*iv.mpf(".36")*iv.mpf(".25")*u/(iv.mpf(".3")+iv.mpf(".25")*u)
        rp=iv.mpf(".3")/(iv.mpf(".3")+iv.mpf(".25")*u)**2
        report[name]=dict(su=su,sv=sv,J_v=-rp*sv/su,dy_deps=wall)
    sep=report["high"]["dy_deps"]-report["low"]["dy_deps"]
    output=dict(dlogB_dv=enclosing_numbers(rho),boundary_contrast_derivative=enclosing_numbers(sep))
    for name,info in report.items():
        part={k:enclosing_numbers(v) for k,v in info.items()}
        part["receiver_rate_contrast_derivative"]=enclosing_numbers(info["J_v"]*iv.mpf(".36")*sep)
        if part["receiver_rate_contrast_derivative"][0]<=0:raise ValueError(info)
        output[name]=part
    return output


def independent(reference,eps,kappa,src,rec):
    sys.path.insert(0,str(reference.parent))
    from closed_form import Contract,Prices
    # For each drive, both stationary quotes are affine in the total principal.
    # Precompute the two exact-endpoint scalar price curves, then integrate
    # the half-line occupation against them, fixing V's exponential tail
    # analytically as in the independent stationary check.
    n,w=roots_legendre(70)
    x=[];ww=[]
    for l,h in ((0.,.3),(.3,1.),(1.,3.),(3.,8.),(8.,16.),(16.,32.)):
        x.extend(l+(n+1)*(h-l)/2);ww.extend(w*(h-l)/2)
    x=np.array(x);ww=np.array(ww)
    def set_quote(v):
        p=Prices(replace(Contract(),principal=61.68*(1+.28*v)))
        e=np.array([p.equity(y) for y in x])-p.boundary*np.exp(x)
        losses=np.array([p.credit_loss(y) for y in x])
        return p.boundary,e,losses
    b0,e0,l0=set_quote(-.9);b1,e1,l1=set_quote(-.7)
    def mix(a,b,v):return a+(b-a)*(v+.9)/.2
    def residual(u,v):
        lam=u/(.23**2/2)
        mask=x<.3
        p=np.empty(len(x))
        p[mask]=-np.expm1(-lam*x[mask])
        p[~mask]=-np.expm1(-lam*.3)*np.exp(-lam*(x[~mask]-.3))
        p*=ww/(.3+.25*u)
        b=mix(b0,b1,v);e=mix(e0,e1,v);l=mix(l0,l1,v)
        eq=(p@e+b*np.expm1(.3)*lam/(lam-1)/(.3+.25*u))/20
        loss=(p@l)/20
        mean=p@x/p.sum()
        return u+.03355-.7*v+.6*np.tanh(eq)*(.3-mean)-4.1*np.tanh(loss)
    def nonlinear(z):
        return np.tanh(np.arctanh(-.8)+z)
    us=brentq(lambda u:residual(u,nonlinear(eps*.25/(.3/u+.25))),*BRACKETS[src])
    physical=nonlinear(eps*.25/(.3/us+.25))
    y=np.log(mix(b0,b1,physical)/mix(b0,b1,-.8))
    v2=nonlinear(kappa*y)
    ur=brentq(lambda u:residual(u,v2),*BRACKETS[rec])
    return us,y,ur,1/(.3/ur+.25)


def main(ref,root_file):
    roots=json.loads(root_file.read_text())
    output=dict(local=local(roots),finite=[])
    for e in (0.,.005,.025,.075):
        for active in (False,True):
            for src in ("low","high"):
                for rec in ("low","high"):
                    z=port_gain(e,1.,src,rec,active)
                    output["finite"].append(dict(eps=e,active=active,src=src,rec=rec,**z,
                         one_interval_hit=read_first_hit(z["reported_value"])))
    for name in ("low","high"):
        def gap(ep):return port_gain(ep,1.,"high",name)["receiver_rate"]-port_gain(ep,1.,"low",name)["receiver_rate"]
        h=1e-4
        deriv=(gap(-2*h)-8*gap(-h)+8*gap(h)-gap(2*h))/(12*h)
        output["local"][name]["independent_4th_order_difference"]=deriv
        interval=output["local"][name]["receiver_rate_contrast_derivative"]
        if abs(deriv-sum(interval)/2)>3e-8:raise RuntimeError("receiver derivative")
    output["cross_checks"]=[]
    for s in ("low","high"):
        for r in ("low","high"):
            z=port_gain(.025,1.,s,r)
            other=independent(ref,.025,1.,s,r)
            err=max(abs(x-y) for x,y in zip(other,[z["u"],z["reported_value"],z["receiver_u"],z["receiver_rate"]]))
            if err>2e-8:raise RuntimeError("cross-law mismatch")
            output["cross_checks"].append(dict(source=s,receiver=r,separate_source_u=other[0],
                separate_port=other[1],separate_receiver_u=other[2],separate_receiver_rate=other[3],max_absolute_error=err))
    return output

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("reference",type=Path)
    a.add_argument("sharp_roots",type=Path)
    z=a.parse_args()
    result=main(z.reference,z.sharp_roots)
    Path(__file__).with_name("verified.json").write_text(json.dumps(result,indent=2)+"\n")
    print(result["local"],result["cross_checks"])
