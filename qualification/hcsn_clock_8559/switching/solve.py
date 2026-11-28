"""Finite-maturity bond semigroup coupled to an equity stopping problem in two liquidity regimes."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from scipy import sparse
from scipy.linalg import expm
from scipy.sparse.linalg import splu,spsolve

R=.08; DELTA=.02; SIGMA=.23; TAX=.27; ALPHA=.60; COUPON=6.39; PRINCIPAL=61.68


def grid(n,vmax,vmin=12.):
    x=np.linspace(np.log(vmin),np.log(vmax),n)
    v=np.exp(x);step=x[1]-x[0]
    mu=R-DELTA-SIGMA**2/2
    base=SIGMA**2/(2*step**2)
    a=base-mu/(2*step);b=base+mu/(2*step)
    assert min(a,b)>0
    xx=sparse.diags([a*np.ones(n-1),-(a+b)*np.ones(n),b*np.ones(n-1)],[-1,0,1],format='lil')
    xx[0,:]=0.;xx[-1,:]=0.
    return v,xx.tocsr()


class Model:
    def __init__(self,n=601,M=96,low=12.,high=500.,friction=(.01,.04),rates=(.12,.16),maturity=1.):
        self.n=n;self.M=M;self.m=maturity
        self.c=COUPON/maturity;self.p=PRINCIPAL/maturity
        self.v,op=grid(n,high,low)
        self.V=np.tile(self.v,2)
        u,w=rates
        self.Q=np.array([[-u,u],[w,-w]])
        self.L=(sparse.kron(sparse.eye(2),op)+sparse.kron(self.Q,sparse.eye(n))).tocsr()
        self.lo=np.array([0,n]);self.hi=np.array([n-1,2*n-1])
        lam=np.repeat(np.array(friction),n)
        self.Db=self.L-sparse.diags(R+lam)
        self.A=sparse.eye(2*n,format='csr')*R-self.L
        H=self.Q-np.diag(R+np.array(friction))
        riskless=expm(H*maturity)@(self.p*np.ones(2))+np.linalg.solve(H,(expm(H*maturity)-np.eye(2))@(self.c*np.ones(2)))
        self.Ehigh=self.v[-1]-np.linalg.solve(R*np.eye(2)-self.Q,(1-TAX)*COUPON+self.p-riskless)
        self.I=sparse.eye(2*n,format='csr')

    def rows(self,stop):
        # A stopped bond locks the actual recovery at first crossing. Cross-regime transitions
        # from a still-live row read that locked payoff even if V is far below the new wall.
        return sparse.diags((~stop).astype(float))@self.Db

    def bond(self,stop,independent=False):
        B=self.rows(stop);c=self.c*(~stop)
        state=np.where(stop,ALPHA*self.V/self.m,self.p)
        if independent:
            from scipy.sparse.linalg import expm_multiply
            ext=sparse.bmat([[B,c[:,None]],[None,np.zeros((1,1))]],format='csr')
            return expm_multiply(ext*self.m,np.r_[state,1.])[:-1]
        dt=self.m/self.M
        solve=splu((self.I-dt*.5*B).tocsc()).solve
        # Two half implicit Euler steps, then Crank–Nicolson after the initial terminal jump.
        for _ in range(2):state=solve(state+.5*dt*c)
        advance=(self.I+dt*.5*B).tocsr()
        for _ in range(self.M-1):
            state=solve(advance@state+dt*c)
        return state

    def equity(self,debt,trial):
        flow=DELTA*self.V-(1-TAX)*COUPON+debt-self.p
        stop=trial.copy();Eq=np.zeros_like(flow)
        for it in range(2000):
            active=~stop;active[self.hi]=False
            lhs=sparse.diags(active.astype(float))@self.A+sparse.diags((~active).astype(float))
            rhs=active*flow;rhs[self.hi]=self.Ehigh
            Eq=spsolve(lhs.tocsc(),rhs)
            cont=(self.A@Eq-flow)/self.A.diagonal()
            new=cont>=Eq-2e-12
            new[self.hi]=False;new[self.lo]=True
            if np.array_equal(stop,new):
                inner=np.ones(len(Eq),bool);inner[self.lo]=False;inner[self.hi]=False
                err=float(np.abs(np.minimum(cont,Eq)[inner]).max())
                return Eq,new,it+1,err
            stop=new
        raise RuntimeError('equity policy iteration failed')

    def fixed(self,start):
        stop=(self.V.reshape(2,self.n)<=np.array(start)[:,None]).ravel()
        observed=[];visited=set()
        for it in range(120):
            key=stop.tobytes()
            if key in visited:return {'status':'cycle','history':observed}
            visited.add(key)
            debt=self.bond(stop)
            E,new,inner,obstacle=self.equity(debt,stop)
            bounds=[]
            for s in new.reshape(2,self.n):
                i=int(np.flatnonzero(s)[-1])
                assert s[:i+1].all() and not s[i+1:].any()
                bounds.append([float(self.v[i]),float(self.v[i+1])])
            changes=int((new!=stop).sum())
            observed.append(dict(wall_cells=bounds,changed=changes,policy_iterations=inner,obstacle=obstacle))
            if not changes:return {'status':'fixed','history':observed,'debt':debt,'E':E,'stop':stop}
            stop=new
        return {'status':'iteration_limit','history':observed}


def one(n,M,high,lam,q,maturity,start,exact=False,save=None):
    t=time.perf_counter()
    m=Model(n,M,high=high,friction=lam,rates=q,maturity=maturity)
    res=m.fixed(start)
    d=dict(n=n,bond_time_steps=M,high=high,friction=lam,rates=q,maturity=maturity,initial=start,
           status=res['status'],outer=len(res['history']),iterates=res['history'])
    if res['status']=='fixed':
        debt=res['debt'];E=res['E'];wall=res['stop']
        d['wall_cells']=res['history'][-1]['wall_cells']
        d['mean_wall_cell']=[float(np.sqrt(l*h)) for l,h in d['wall_cells']]
        d['issue_at_100']=[float(np.interp(100.,m.v,a)) for a in debt.reshape(2,n)]
        d['equity_at_100']=[float(np.interp(100.,m.v,a)) for a in E.reshape(2,n)]
        d['obstacle_residual_normalized']=res['history'][-1]['obstacle']
        d['min_equity']=float(E.min())
        if exact:
            independent=m.bond(wall,independent=True)
            d['semigroup_grid_max_diff']=float(np.max(abs(independent-debt)))
            d['semigroup_diff_at_100']=[float(np.interp(100.,m.v,a)) for a in abs(independent-debt).reshape(2,n)]
        if save is not None:
            np.savez_compressed(save,v=m.v,issue=debt.reshape(2,n),equity=E.reshape(2,n),stop=wall.reshape(2,n))
    d['elapsed']=time.perf_counter()-t
    return d


def audit(out):
    out.mkdir(exist_ok=True,parents=True)
    studies=[]
    jobs=[]
    for n,M in [(161,48),(321,96),(641,192),(1281,384)]:
        for tag,lam,q in [('original',(.01,.04),(0.,0.)),('equal',(.01,.01),(.12,.16)),('switch',(.01,.04),(.12,.16))]:
            starts=[(50.,55.),(67.44,74.52),(84.,88.)] if tag=='switch' or n==321 else [(67.44,74.52)]
            for start in starts:jobs.append((n,M,500.,tag,lam,q,1.,start))
    for n,h in [(700,650.),(800,900.)]:
        jobs.append((n,224,h,'domain',(.01,.04),(.12,.16),1.,(67.44,74.52)))
    for mat in [.5,2.]: jobs.append((641,192,500.,'maturity',(.01,.04),(.12,.16),mat,(67.44,74.52)))
    for u,w in [(1.2,1.6),(.012,.016)]: jobs.append((641,192,500.,'rate',(.01,.04),(u,w),1.,(67.44,74.52)))
    for i,(n,M,upper,tag,lam,q,mat,start) in enumerate(jobs):
        name=f'{i:02d}-{tag}-{n}'
        f=out/(name+'.json')
        if f.exists():studies.append(json.loads(f.read_text()));continue
        r=one(n,M,upper,lam,q,mat,start,exact=(n==321 and start==(67.44,74.52)),save=out/(name+'.npz'))
        r['name']=name;f.write_text(json.dumps(r,indent=1)+'\n');studies.append(r)
        print(name,r['status'],r.get('mean_wall_cell'),r['outer'],round(r['elapsed'],2),flush=True)
    summary=[{k:v for k,v in r.items() if k!='iterates'} for r in studies]
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);args=p.parse_args();audit(args.out)
