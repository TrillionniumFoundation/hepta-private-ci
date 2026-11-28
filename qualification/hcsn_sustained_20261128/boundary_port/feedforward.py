"""Common-reset half-line access with one predetermined scalar current waveform."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import numpy as np
from scipy.special import log_ndtr,ndtr,roots_legendre
from port import port_gain

a,d,D=.3,.25,.23**2/2
beta=1.1


def f_hit(n,t,u):
    b=n*a
    return b*np.exp(-(b-u*t)**2/(4*D*t))/np.sqrt(4*np.pi*D*t**3)


def F_hit(n,t,u):
    t=np.asarray(t);n=np.asarray(n)
    live=t>0
    ts=np.where(live,t,1.0)
    b=n*a
    std=np.sqrt(2*D*ts)
    out=ndtr((u*ts-b)/std)+np.exp(u*b/D+log_ndtr((-b-u*ts)/std))
    return np.where(live,out,0.)


def refractory(t,u):
    n=np.arange(1,int(t/d)+2)
    return np.sum(F_hit(n,t-(n-1)*d,u)-F_hit(n,t-n*d,u))


def flux(t,u):
    n=np.arange(1,int(t/d)+2)
    used=t-(n-1)*d
    ok=used>0
    return np.sum(f_hit(n[ok],used[ok],u))


def active_density(t,x,u):
    table=np.zeros_like(x)
    for n in range(int(t/d)+1):
        s=t-n*d
        if s<=0:continue
        first=np.abs(x-a)+n*a
        second=x+(n+1)*a
        expo=-u*(x-(n+1)*a)/(2*D)-u*u*s/(4*D)-first**2/(4*D*s)
        kernel=np.exp(expo)*(-np.expm1(-(second-first)*(second+first)/(4*D*s)))/np.sqrt(4*np.pi*D*s)
        table+=kernel
    return table


def prepare(ref):
    sys.path.insert(0,str(ref.parent))
    from closed_form import Contract,Prices
    q0,q1=[Prices(replace(Contract(),principal=61.68*(1+.28*v))) for v in (-.9,-.7)]
    def setup(n):
        gx,gw=roots_legendre(n);x=[];w=[]
        seg=(0.,a,1.,3.,8.,16.,32.,64.,128.)
        for lo,hi in zip(seg[:-1],seg[1:]):
            x.extend(lo+(gx+1)*(hi-lo)/2);w.extend(gw*(hi-lo)/2)
        x=np.array(x);w=np.array(w)
        E,L=[np.stack([np.array([fn(y) for y in x]) for fn in methods]) for methods in
             ((q0.equity,q1.equity),(q0.credit_loss,q1.credit_loss))]
        return x,w,E,L
    x,w,E,L=setup(100)
    gx,gw=roots_legendre(72)
    bslope=(q1.boundary-q0.boundary)/.2
    rows={}
    for name in ("low","high"):
        true=port_gain(.025,1.,name,"high")
        u=true["u"];J=true["rate"]
        lam=u/D;N=a+d*u
        stationary=np.where(x<=a,-np.expm1(-lam*np.minimum(x,a)),
            -np.expm1(-lam*a)*np.exp(-lam*np.maximum(x-a,0.)))/N
        entries=[]
        for t in (.25,1.,5.,10.,20.,50.,100.,200.,500.,1000.):
            p=active_density(t,x,u)
            M=w@p
            R=refractory(t,u)
            look=min(t,40.)
            z=(look/2)*sum(gw*np.exp(-(gx+1)*look/2)*[refractory(t-s,u) for s in (gx+1)*look/2])
            v=np.tanh(np.arctanh(-.8)+.025*z)
            fraction=(v+.9)/.2
            eq=w@(p*((1-fraction)*E[0]+fraction*E[1]))/20
            loss=w@(p*((1-fraction)*L[0]+fraction*L[1]))/20
            mean=(w@(p*x))/M
            base=.03355-.7*v+.6*np.tanh(max(eq,0.))*(a-mean)-4.1*np.tanh(max(loss,0.))
            b=q0.boundary+bslope*(v+.9)
            moving=(bslope/b)*(1-v*v)*.025*(R-z)
            current=-u-base+moving
            # Integrate the interior and bound both exterior weighted tails analytically.
            active_gap=w@(np.exp(beta*x)*abs(p-stationary))
            ages=d*(gx+1)/2
            refgap=d/2*(gw@np.array([abs(flux(t-s,u)-J) if s<t else J for s in ages]))
            log_tail_static=np.log(-np.expm1(-lam*a))+lam*a-(lam-beta)*128-np.log((lam-beta)*N)
            tail_static=np.exp(max(log_tail_static,np.log(np.finfo(float).tiny)))
            waits=t-d*np.arange(int(t/d)+1)
            log_tail_transient=lam*a-(lam-beta)*128+np.log(np.sum(1/np.sqrt(4*np.pi*D*waits[waits>0]))/(lam-beta))
            tail_transient=np.exp(max(log_tail_transient,np.log(np.finfo(float).tiny)))
            epsmass=abs(M+R-1)
            if epsmass>1e-8:raise ArithmeticError((name,t,epsmass))
            entries.append(dict(t=t,precomputed_current=current,source_flux=flux(t,u),R=R,filtered=z,
                          actual_boundary=b,integrated_active_mass=M,mass_error=epsmass,
                          weighted_active_gap_upto128=active_gap,refractory_gap=refgap,
                          stationary_weighted_tail_upper=tail_static,transient_weighted_tail_bound=tail_transient,
                          log_stationary_tail=log_tail_static,log_transient_tail_bound=log_tail_transient))
        rows[name]=dict(target_u=u,target_J=J,target_R=d*J,path=entries)
    return dict(common_reset=a,normalized_source_eps=.025,beta=beta,rows=rows,
              note="Finite numeric time samples of a precomputed continuous control; no online hidden-state measurement in this construction.")

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("reference",type=Path);z=ap.parse_args()
    result=prepare(z.reference)
    Path(__file__).with_name("feedforward.json").write_text(json.dumps(result,indent=2)+"\n")
    for k,d in result["rows"].items():print(k,d["path"][-1])
