"""A normalized continuous firing-population with an explicit slow/fast feedback extension."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
from scipy.interpolate import CubicSpline
from scipy.special import ndtr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import GRID,CUTS,DT,MU,SIGMA,reset_vector
from hx_reference import Parameters, StationaryFirm

RESET=reset_vector();US=np.linspace(-1,1,401);ZS=np.array([np.log(StationaryFirm(Parameters(),np.exp(1.5*u)).boundary_closed()) for u in US])
SURFACE=CubicSpline(US,ZS-ZS[len(US)//2]);SLOPE=float(SURFACE(0.,1))
def wall(u,law):
    return np.where(law==2,SURFACE(u),np.where(law==1,SLOPE*u,0.))
def interval_mass(z):
    lo=z[...,:-1];hi=z[...,1:]
    return np.where(lo>=0,ndtr(-lo)-ndtr(-hi),ndtr(hi)-ndtr(lo))
def kernel(u,old,law):
    drift=MU-.7*.25*u-(wall(u,law)-wall(old,law))/DT
    m=drift[:,None,None];x=GRID[None,:,None];cuts=CUTS[None,None,:];sd=SIGMA*np.sqrt(DT)
    a=interval_mass((cuts-x-m*DT)/sd)
    b=interval_mass((cuts+x-m*DT)/sd)*np.exp(-2*m*x/SIGMA**2)
    q=a-b
    if np.min(q)<-2e-11:raise ArithmeticError(float(np.min(q)))
    return np.maximum(q,0)
def open_loop():
    q=kernel(np.zeros(1),np.zeros(1),np.zeros(1))[0]
    T=np.zeros((len(GRID)+1,len(GRID)+1));T[:-1,:-1]=q;T[:-1,-1]=np.maximum(0.,1-q.sum(1));T[-1,:-1]=RESET
    M=T.T-np.eye(len(T));M[-1]=1
    target=np.linalg.solve(M,np.r_[np.zeros(len(T)-1),1.]);return T,target

TRANS,P0=open_loop();F0=P0[-1]
def unpack(z):
    return np.column_stack([z[:,:len(GRID)-1],1.-z[:,:len(GRID)].sum(1),z[:,len(GRID)-1]])
def pack(p,a,u):
    return np.column_stack([p[:,:-2],p[:,-1],a,u])
def mapping(z,law,g,h,beta):
    p=unpack(z);a=z[:,-2];old=z[:,-1]
    u=np.tanh(g*(p[:,-1]-F0)-h*(a-F0))
    q=kernel(u,old,law);alive=np.einsum('ij,ijk->ik',p[:,:-1],q)
    flux=p[:,:-1].sum(1)-alive.sum(1)
    nextp=np.column_stack([alive+p[:,-1,None]*RESET,flux])
    return pack(nextp,(1-beta)*a+beta*flux,u)
def derivative(z,law,g,h,beta,hstep):
    dim=len(z);delta=np.eye(dim)*hstep;const=lambda x:np.full(dim,x)
    positive=mapping(z[None,:]+delta,const(law),const(g),const(h),const(beta))
    negative=mapping(z[None,:]-delta,const(law),const(g),const(h),const(beta))
    return ((positive-negative)/(2*hstep)).T
def period(v):
    amp=np.ptp(v)
    if amp<=1e-4:return None
    for j in range(2,min(256,len(v)//8)+1):
        err=np.sqrt(np.mean((v[j:]-v[:-j])**2))
        if err<1e-7:return (j,float(err))
    return None
def evolve(cases,sign,steps,tail):
    pars=np.array(cases);law,g,h,beta=pars.T
    n=len(cases);p=np.repeat(P0[None,:],n,axis=0);order=np.argsort(-P0[:-1])
    delta=sign*.015*min(P0[order[0]],P0[order[1]]);p[:,order[0]]+=delta;p[:,order[1]]-=delta
    eq=pack(p,np.full(n,F0),np.zeros(n))
    end=np.empty((tail,n));minimum=1.;maximum=0.;masserr=0.
    for t in range(steps):
        eq=mapping(eq,law,g,h,beta);current=unpack(eq)
        minimum=min(minimum,float(current.min()));maximum=max(maximum,float(current.max()));masserr=max(masserr,float(np.max(abs(current.sum(1)-1))))
        if t>=steps-tail:end[t-steps+tail]=current[:,-1]
    return end.T,dict(minimum=minimum,maximum=maximum,mass_error=masserr)
def run(out):
    start=time.monotonic();out.mkdir(parents=True,exist_ok=True)
    cases=[(law,g,ratio*g,beta) for law in (0,1,2) for g in (0,2,4,8,16,32,64,128) for ratio in ((0.,) if g==0 else (0.,.5,1.5)) for beta in (.05,.2)]
    z=pack(P0[None,:],np.array([F0]),np.zeros(1))[0];rows=[];saved={}
    for i,(law,g,h,beta) in enumerate(cases):
        j=derivative(z,law,g,h,beta,1e-6);j2=derivative(z,law,g,h,beta,3e-7)
        eig=np.linalg.eigvals(j);q=eig[np.argmax(abs(eig))]
        new=mapping(z[None,:],np.array([law]),np.array([g]),np.array([h]),np.array([beta]))[0]
        rows.append(dict(index=i,law=['fixed','tangent','literal'][law],g=g,h=h,beta=beta,eigenradius=abs(q),leading=[q.real,q.imag],
           jacobian_fd_max=float(np.max(abs(j-j2))),jacobian_32_spectral_norm=float(np.linalg.norm(np.linalg.matrix_power(j,32),2)),fixed_point_error=float(np.max(abs(new-z)))))
        saved[law,g,h,beta]=j
    for row,(law,g,h,beta) in zip(rows,cases):
        if law==2:row['tangent_jacobian_max_abs_difference']=float(np.max(abs(saved[2,g,h,beta]-saved[1,g,h,beta])))
    tail,finite=evolve(cases,1,1536,512)
    for e,v in zip(rows,tail):
        e.update(tail_min=float(v.min()),tail_max=float(v.max()),tentative_period=period(v))
    # Lowest successful gain and latest/highest gain for each law, slow ratio, and filter.
    selected=set()
    for law in (0,1,2):
        for ratio in (0.,.5,1.5):
            for beta in (.05,.2):
                keys=[i for i,ss in enumerate(cases) if ss[0]==law and ss[1]>0 and abs(ss[2]/ss[1]-ratio)<1e-6 and ss[3]==beta and rows[i]['tentative_period']]
                if keys:selected.update((keys[0],keys[-1]))
    confirmations={};signals={};extended=[]
    if selected:
        idx=sorted(selected);selection=[cases[i] for i in idx]
        for sign in (-1,1):
            sig,stats=evolve(selection,sign,4096,2048);extended.append(stats)
            for i,v in zip(idx,sig):
                confirmations.setdefault(str(i),{})[str(sign)]=dict(period=period(v),min=float(v.min()),max=float(v.max()))
                signals[f'i{i}_sign{sign}']=v
    np.savez_compressed(out/'traces.npz',**signals)
    eigen=np.sort(abs(np.linalg.eigvals(TRANS)))[::-1]
    src=dict(stationary_flux=float(F0),stationary_distribution=P0.tolist(),second_eigen_modulus=float(eigen[1]),
        stochastic_error=float(abs(TRANS.sum(1)-1).max()),stationary_error=float(abs(P0@TRANS-P0).max()),open_two_step_min_numerical=float((TRANS@TRANS).min()),
        stationary_wall_derivative=SLOPE,cases=rows,confirmations=confirmations,coarse_mass=finite,extended_mass=extended,
        wall_seconds=time.monotonic()-start)
    (out/'results.json').write_text(json.dumps(src,indent=1,allow_nan=False)+'\n')
    print('cases',len(cases),'confirmed cases',len(confirmations),'seconds',src['wall_seconds'],flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();run(a.out)
