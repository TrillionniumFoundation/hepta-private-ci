"""Find indistinguishable distributions reachable by two legal input histories.

Every trajectory starts at x=.18 and uses the same physical dynamics. External
scalar pressure is bounded, and the last two settings are always the common P0.
Independently replay any witness by quadrature of the killed transition density.
"""
from pathlib import Path
import argparse,json,math
import numpy as np
from scipy.special import ndtr
from scipy.integrate import quad
from observability import X,P,SIGMA,MU,price,hit,boundary

N=len(X);FREE=10;T=12;DT=.25;SD=SIGMA*math.sqrt(DT)
EDGES=np.r_[0.,(X[1:]+X[:-1])/2]
INIT=np.r_[np.isclose(X,.18).astype(float),0.]
RESET=np.isclose(X,.30).astype(float)
B0=boundary()
SLOPE=.28*P*(boundary(P+1)-B0)
phi=lambda t:np.exp(-t*t/2)/math.sqrt(2*math.pi)

def matrices(shifts):
    m=X+shifts[:,None]
    x=np.maximum(m,0)[...,None];z=(x+MU*DT-EDGES)/SD;zi=(-x+MU*DT-EDGES)/SD
    w=np.exp(-2*MU*x/SIGMA**2);image=ndtr(zi)
    survival=np.where(m[...,None]>0,ndtr(z)-w*image,0.)
    slope=np.where(m[...,None]>0,phi(z)/SD+w*(2*MU/SIGMA**2*image+phi(zi)/SD),0.)
    M=np.zeros((len(shifts),N+1,N+1));D=M.copy()
    for store,S,h in [(M,survival,1-survival[...,0]),(D,slope,-slope[...,0])]:
        store[:,:N,:-2]=S[...,:-1]-S[...,1:]
        store[:,:N,-2]=S[...,-1];store[:,:N,-1]=h
    M[:,-1,:N]=RESET
    return M,D
def evolve(u):
    u=np.r_[u,0.,0.]
    b=np.log((B0+SLOPE*u)/B0)
    derivative=np.eye(T,FREE)*(SLOPE/(B0+SLOPE*u))[:,None]
    ds=np.vstack((np.zeros((1,FREE)),derivative[:-1]))-derivative
    M,D=matrices(np.r_[0.,b[:-1]]-b);weights=INIT.copy();dw=np.zeros((FREE,N+1))
    for i in range(T):
        dw=dw@M[i]+ds[i,:,None]*(weights@D[i])[None,:];weights=weights@M[i]
    return weights,dw
def replay(u):
    b=B0;weights=INIT.copy();min_entry=1.;mass_error=0.
    for q in np.r_[u,0.,0.]:
        new=boundary(P*(1+.28*q));pos=X+np.log(b/new);edges=np.r_[EDGES,np.inf]
        M=np.zeros((N+1,N+1))
        for i,x in enumerate(pos):
            if x<=0:M[i,-1]=1;continue
            w=np.exp(-2*MU*x/SIGMA**2)
            def density(y):return (phi((y-x-MU*DT)/SD)-w*phi((y+x-MU*DT)/SD))/SD
            M[i,:N]=[quad(density,lo,hi,epsabs=1e-12,epsrel=1e-11)[0] for lo,hi in zip(edges[:-1],edges[1:])]
            M[i,-1]=1-M[i,:N].sum()
        M[-1,:N]=RESET;weights=weights@M;b=new
        min_entry=min(min_entry,M.min());mass_error=max(mass_error,abs(weights.sum()-1))
    return weights,[min_entry,mass_error]
def run():
    E,L=price(X);row={"equity":np.r_[E,0.],"shortfall":np.r_[L,0.],
        "refractory":np.r_[np.zeros(N),1.],"F.25":np.r_[hit(X,.25),0.],"F1":np.r_[hit(X,1.),0.]}
    target=np.r_[hit(X,.5)-hit(X,.25),hit(.30,.25)]
    controls=np.random.default_rng(613776).uniform(-.68,.68,(18,FREE))
    ranks=[]
    for u in controls:
        w,d=evolve(u);s=np.linalg.svd(d[:,:N],compute_uv=False)
        ranks.append((s[-1],u,s))
    _,base,s=max(ranks,key=lambda e:e[0]);diff_error={}
    for step in (1e-5,5e-6):
        fd=np.stack([(evolve(base+step*e)[0]-evolve(base-step*e)[0])/(2*step) for e in np.eye(FREE)])
        diff_error[str(step)]=float(abs(fd-evolve(base)[1]).max())
    outputs=[]
    for names in (["equity","shortfall","refractory"],["equity","shortfall","refractory","F.25"],
                  ["equity","shortfall","refractory","F.25","F1"]):
        a=np.stack([row[k] for k in names]);A=a/np.linalg.norm(a,axis=1)[:,None]
        def tangent(u):
            w,d=evolve(u);G=A@d.T
            _,sv,V=np.linalg.svd(G,full_matrices=True);null=V[np.count_nonzero(sv>sv[0]*1e-12):]
            return w,G,null.T@(null@(d@target))
        def march(u,sign):
            u=u.copy();level=A@evolve(u)[0];accepted=0
            for _ in range(35):
                old,_,g=tangent(u)
                if max(abs(g))<1e-13:break
                delta=sign*g/max(abs(g));ok=False
                for step in (.035,.012,.004,.001):
                    v=u+step*delta
                    if max(abs(v))>.88:continue
                    for _ in range(12):
                        w,d=evolve(v);res=A@w-level
                        if max(abs(res))<8e-14:break
                        corr=np.linalg.lstsq(A@d.T,res,rcond=1e-12)[0]
                        if max(abs(corr))>.12:break
                        v-=corr
                    w,_=evolve(v)
                    if max(abs(v))<.9 and max(abs(A@w-level))<2e-12 and sign*((w-old)@target)>0:
                        u=v;accepted+=1;ok=True;break
                if not ok:break
            return u,accepted
        ordered=sorted(controls,key=lambda z:max(abs(tangent(z)[2])),reverse=True);results=[]
        for start in ordered[:4]:
            hi,n1=march(start,1);lo,n2=march(start,-1);z=evolve(hi)[0]-evolve(lo)[0]
            if max(abs(a@z))<1e-8:results.append((float(z@target),hi,lo,n1+n2))
        if not results:raise ArithmeticError(names)
        gap,hi,lo,it=max(results,key=lambda result:result[0])
        H,hcheck=replay(hi);W,wcheck=replay(lo);z=H-W
        assert max(abs(a@z))<1e-8 and abs(z@target-gap)<1e-9
        outputs.append(dict(matched=names,high_command=np.r_[hi,0.,0.].tolist(),low_command=np.r_[lo,0.,0.].tolist(),
            high_state=H.tolist(),low_state=W.tolist(),high_observed=(a@H).tolist(),low_observed=(a@W).tolist(),
            maximum_observed_gap=float(max(abs(a@z))),future_risk=[float(H@target),float(W@target)],risk_gap=float(z@target),
            controls_are_distinct=bool(np.linalg.norm(hi-lo)>1e-9),level_set_steps=it,quadrature_kernel_checks=[hcheck,wcheck]))
    return dict(scope="bounded, independently controllable inputs driving the explicitly discretized population; no assertion of independently reachable human observations",
       initial=INIT.tolist(),last_two_principals=[P,P],free_coordinates=FREE,nominal_control=base.tolist(),
       coordinate_singular_values=s.tolist(),analytic_jacobian_central_error=diff_error,pairs=outputs)
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("output",type=Path);args=ap.parse_args()
    args.output.write_text(json.dumps(run(),indent=2)+"\n")
