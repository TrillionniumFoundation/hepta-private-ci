"""Identically initialized signed-force receivers under two filtered boundary messages."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.linalg import solve_banded

from port import port_gain


def finite_volume(dx,dt,edge,stop,port,quote0,quote1,*,gain=1.):
    sigma=.23; D=sigma*sigma/2; a=.30; dead=.25
    n=round(edge/dx)-1
    if not (math.isclose(n*dx+dx,edge) and math.isclose(round(dead/dt)*dt,dead) and
            math.isclose(round(a/dx)*dx,a)):
        raise ValueError("resolve reset, wall and refractory interval on the chosen grid")
    x=dx*np.arange(1,n+1)
    def table(quote):
        return np.array([quote.equity(s) for s in x])/20,np.array([quote.credit_loss(s) for s in x])/20
    e0,l0=table(quote0);e1,l1=table(quote1)
    e_slope=(e1-e0)/.2
    l_slope=(l1-l0)/.2
    bprime=(quote1.boundary-quote0.boundary)/.2
    # Both receivers have exactly the same initially stationary continuum
    # density sampled on these nodes, identical refractory queue and q(0)=0.
    u=port_gain(0,0,"high","high")["receiver_u"]
    J=u/(a+u*dead)
    lam=u/D
    weights=np.empty_like(x)
    below=x<=a
    weights[below]=-np.expm1(-lam*x[below])
    weights[~below]=-np.expm1(-lam*a)*np.exp(-lam*(x[~below]-a))
    mass=weights*dx/(a+dead*u)
    pipe=np.full(round(dead/dt),J)
    band=np.zeros((3,n))
    escaped=0.; maxerr=0.; initial=mass.sum()+dt*sum(pipe)
    outputs={}
    inspect={round(t/dt):t for t in (.25,.5,1,2,5,10,20,40,80) if t<=stop}
    for j in range(round(stop/dt)):
        tm=(j+.5)*dt
        r=math.exp(-tm)
        q=port*(1-r)
        v=math.tanh(math.atanh(-.8)+gain*q)
        wb=quote0.boundary+bprime*(v+.9)
        move=(bprime/wb)*(1-v*v)*gain*port*r
        alive=mass.sum()
        avg=(mass@x)/alive
        eq=mass@(e0+(v+.9)*e_slope)
        loss=mass@(l0+(v+.9)*l_slope)
        velocity=.03355-.7*v+.6*math.tanh(max(eq,0))*(a-avg)-4.1*math.tanh(max(loss,0))-move
        peclet=velocity*dx/D
        if abs(peclet)<1e-7:
            up=D/dx**2*(1+peclet/2+peclet**2/12)
            down=D/dx**2*(1-peclet/2+peclet**2/12)
        else:
            up=velocity/(dx*(-math.expm1(-peclet)))
            down=velocity/(dx*math.expm1(peclet))
        band[0,1:]=-dt*down;band[2,:-1]=-dt*up;band[1]=1+dt*(up+down)
        slot=j%len(pipe)
        mass[round(a/dx)-1]+=dt*pipe[slot]
        mass=solve_banded((1,1),band,mass,overwrite_b=True,check_finite=False)
        flux=down*mass[0]
        pipe[slot]=flux
        escaped+=dt*up*mass[-1]
        error=abs(mass.sum()+dt*pipe.sum()+escaped-initial)
        maxerr=max(maxerr,error)
        if j+1 in inspect:
            outputs[str(inspect[j+1])]=float(flux)
    return dict(flux=outputs,upper_escape=float(escaped),maximum_mass_balance_error=float(maxerr),
                initial_total=float(initial))


def main(reference):
    sys.path.insert(0,str(reference.parent))
    from closed_form import Prices,Contract
    quote0,quote1=[Prices(replace(Contract(),principal=61.68*(1+.28*v))) for v in (-.9,-.7)]
    data=[]
    sources=[port_gain(.025,1.,s,"high") for s in ("low","high")]
    expected=sources[1]["receiver_rate"]-sources[0]["receiver_rate"]
    for dx,dt,edge in ((.03,.0125,3.),(.015,.00625,3.),(.0075,.003125,3.),(.0075,.003125,4.5),(.00375,.003125,4.5)):
        raw=[finite_volume(dx,dt,edge,80.,s["reported_value"],quote0,quote1) for s in sources]
        gap={k:raw[1]["flux"][k]-raw[0]["flux"][k] for k in raw[0]["flux"]}
        data.append(dict(dx=dx,dt=dt,edge=edge,raw=raw,high_minus_low=gap,
                         last_gap_difference_from_exact=gap["80"]-expected))
    if abs(data[-1]["last_gap_difference_from_exact"])>2e-6:
        raise ArithmeticError(data[-1])
    cut1=finite_volume(.03,.0125,3.,5.,sources[0]["reported_value"],quote0,quote1,gain=0.)
    cut2=finite_volume(.03,.0125,3.,5.,sources[1]["reported_value"],quote0,quote1,gain=0.)
    if cut1!=cut2:raise ArithmeticError("disconnected transient has a source side channel")
    return dict(source_gain=.025,full_signed_receiver="same high stationary parent",wire_filter_time=1.,
                exact_steady_gauss_resolvent_contrast=expected,grids=data,cut_wire_equal=cut1==cut2)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("reference",type=Path)
    args=ap.parse_args()
    result=main(args.reference)
    Path(__file__).with_name("transient.json").write_text(json.dumps(result,indent=2)+"\n")
    print([(x["dx"],x["last_gap_difference_from_exact"],x["raw"][1]["upper_escape"]) for x in result["grids"]])
