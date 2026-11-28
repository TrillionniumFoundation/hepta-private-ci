"""Solve two continuous wall locations from smooth fit on a moving nonuniform mesh."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.optimize import least_squares
from scipy.sparse.linalg import spsolve
from solve import Model, R, DELTA, SIGMA, TAX, COUPON


def mesh(lower,upper,xmin,xmax,cells):
    knots=np.log([xmin,lower,upper,xmax])
    active=[0,1,3] if abs(lower-upper)<1e-9 else [0,1,2,3]
    xc=[];index=[0]
    for i,j in zip(active[:-1],active[1:]):
        m=cells[0] if i==0 else cells[1] if i==1 and j==2 else cells[2]
        seg=np.linspace(knots[i],knots[j],m+1)
        xc.extend(seg[:-1]);index.append(len(xc))
    xc.append(knots[-1]);x=np.array(xc);v=np.exp(x);n=len(xc)
    dx0=x[1:-1]-x[:-2];dx1=x[2:]-x[1:-1]
    mu=R-DELTA-SIGMA**2/2
    left=(SIGMA**2-mu*dx1)/(dx0*(dx0+dx1))
    right=(SIGMA**2+mu*dx0)/(dx1*(dx0+dx1))
    assert left.min()>0 and right.min()>0
    spatial=sparse.diags([np.r_[left,0.],np.r_[0.,-left-right,0.],np.r_[0.,right]],[-1,0,1],format='csr')
    wallidx=(index[1],index[1] if len(active)==3 else index[2])
    return x,v,spatial,wallidx


def residual(bounds,lam,rates,segments,M,extent=(12.,500.),save=False):
    low,high=bounds
    x,v,S,ids=mesh(low,high,*extent,segments)
    n=len(x);m=Model(n,M,low=extent[0],high=extent[1],friction=lam,rates=rates)
    m.v=v;m.V=np.tile(v,2)
    m.L=(sparse.kron(sparse.eye(2),S)+sparse.kron(m.Q,sparse.eye(n))).tocsr()
    m.Db=m.L-sparse.diags(R+np.repeat(lam,n));m.A=R*m.I-m.L
    stop=np.concatenate([np.arange(n)<=idx for idx in ids]);d=m.bond(stop)
    g=DELTA*m.V-(1-TAX)*COUPON+d-m.p
    active=~stop;active[m.hi]=False
    A=sparse.diags(active.astype(float))@m.A+sparse.diags((~active).astype(float))
    rhs=active*g;rhs[m.hi]=m.Ehigh
    E=spsolve(A.tocsc(),rhs).reshape(2,n)
    derivative=[]
    for regime,idx in enumerate(ids):
        # Solve the local cubic interpolant in scaled coordinates, then differentiate in log V.
        local=x[idx:idx+4]-x[idx];scale=local[-1]
        mat=np.polynomial.polynomial.polyvander(local/scale,3)
        coefficients=np.linalg.solve(mat,E[regime,idx:idx+4])
        derivative.append(coefficients[1]/scale)
    if save:
        # At a fitted wall the true second derivative can jump, so the discrete centered wall row
        # is not used to certify the sign away from the contact. Preserve both diagnostics.
        full=m.A@E.ravel()-g
        safe=np.ones(len(full),bool);safe[m.hi]=False;safe[m.lo]=False
        interior=safe.copy()
        for regime,idx in enumerate(ids):interior[regime*n+idx]=False
        residuals=dict(walls=list(map(float,bounds)),smooth_residual=list(map(float,derivative)),
                       min_live_equity=float(E.ravel()[active].min()),min_stop_complement_full=float(full[safe & stop].min()),
                       min_stop_complement_interior=float(full[interior & stop].min()),
                       equation_max=float(np.abs(full[active]).max()),
                       debt_at_100=[float(np.interp(100.,v,x)) for x in d.reshape(2,n)],
                       equity_at_100=[float(np.interp(100.,v,x)) for x in E],
                       segments=segments,time_steps=M,domain=list(extent))
        return residuals, dict(v=v,x=x,equity=E,debt=d.reshape(2,n),stopped=stop.reshape(2,n))
    return np.array(derivative)


def fit(lam,rates,segments,M,initial=(69.8,71.4),extent=(12.,500.)):
    equal=abs(lam[0]-lam[1])<1e-12
    def unpack(v):
        return (v[0],v[0]) if equal else (v[0],v[0]+v[1])
    def objective(v):
        res=residual(unpack(v),lam,rates,segments,M,extent)
        return res[:1] if equal else res
    start=[initial[0]] if equal else [initial[0],initial[1]-initial[0]]
    limits=([40.],[100.]) if equal else ([40.,.02],[100.,25.])
    res=least_squares(objective,start,bounds=limits,xtol=1e-10,ftol=1e-10,gtol=1e-10,diff_step=1e-5,max_nfev=60)
    summary,arrays=residual(unpack(res.x),lam,rates,segments,M,extent,True)
    summary.update(friction=list(lam),rates=list(rates),initial=initial,evaluations=res.nfev,
                   success=bool(res.success and np.linalg.norm(res.fun,np.inf)<2e-5))
    return summary,arrays


def main(folder):
    folder.mkdir(exist_ok=True,parents=True)
    rows=[]
    for size in [1,2,4]:
        jobs=[('original',(.01,.04),(0.,0.),(67.,74.)),('equal',(.01,.01),(.12,.16),(67.,67.)),
              ('switch',(.01,.04),(.12,.16),(69.5,72.5)),('startalt',(.01,.04),(.12,.16),(65.,78.))]
        for label,lam,q,initial in jobs:
            s=[70*size,12*size,80*size];H=48*size;name=f'{label}-{size}'
            r,ar=fit(lam,q,s,H,initial);r['case']=name
            if label in ('original','equal'):
                expected=[67.4415153906037,74.5218309923192 if label=='original' else 67.4415153906037]
                r['analytical_error']=(np.array(r['walls'])-expected).tolist()
            np.savez_compressed(folder/(name+'.npz'),**ar);rows.append(r)
            print(name,r['success'],r['walls'],r['smooth_residual'],r['min_stop_complement_interior'],flush=True)
    (folder/'SMOOTH.json').write_text(json.dumps(rows,indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);main(p.parse_args().out)
