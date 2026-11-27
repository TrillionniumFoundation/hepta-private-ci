"""Search for reachable price-port collisions and replay them through the original PyTorch cell."""
import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr


class Population:
    def __init__(self, cell):
        self.grid=cell.grid.detach().numpy()
        self.reset=cell.reset_weights.detach().numpy()
        self.n=len(self.grid)
        self.cuts=np.r_[0,(self.grid[1:]+self.grid[:-1])/2]
        self.mu=cell.prices.mu
        self.sigma=cell.prices.p.sigma
        self.dt=cell.dt
        self.k=2*self.mu/self.sigma**2
        import torch
        p=torch.tensor([cell.prices.p.P0],dtype=torch.float64)
        e,l=cell.priced_channels(p)
        self.port=np.zeros((self.n+1,7))
        self.port[-1,0]=1
        self.port[:-1,1]=e.detach().numpy().ravel()/20
        self.port[:-1,2]=l.detach().numpy().ravel()/20
        for j,h in enumerate(cell.probe_horizons):
            self.port[:-1,3+j]=cell.prices.passage(cell.grid,h).detach().numpy()
        self.next=self.matrix(0)[0][:,-1]

    def matrix(self,change):
        x=self.grid+change
        s=self.sigma*np.sqrt(self.dt)
        live=x>0
        x=np.maximum(x,0)[:,None]
        refl=np.exp(-self.k*x)
        z=(self.cuts-x-self.mu*self.dt)/s
        rz=(self.cuts+x-self.mu*self.dt)/s
        c=ndtr(z)-refl*ndtr(rz)
        v=(-np.exp(-z*z/2)-refl*np.exp(-rz*rz/2))/(s*np.sqrt(2*np.pi))+self.k*refl*ndtr(rz)
        prob=np.diff(np.c_[c,1-refl],axis=1)
        grad=np.diff(np.c_[v,self.k*refl],axis=1)
        mat=np.zeros((self.n+1,self.n+1))
        deriv=np.zeros_like(mat)
        mat[:-1,:-1]=np.where(live[:,None],np.maximum(prob,0),0)
        deriv[:-1,:-1]=np.where(live[:,None],grad,0)
        mat[:-1,-1]=1-mat[:-1,:-1].sum(1)
        deriv[:-1,-1]=-deriv[:-1,:-1].sum(1)
        mat[-1,:-1]=self.reset
        return mat,deriv

    def endpoint(self,levels):
        history=np.r_[0,levels,0]
        p=np.r_[self.reset,0.]
        dp=np.zeros((len(levels),self.n+1))
        for j,shift in enumerate(history[:-1]-history[1:]):
            mat,deriv=self.matrix(shift)
            dp=dp@mat
            influence=p@deriv
            if j: dp[j-1]+=influence
            if j<len(levels): dp[j]-=influence
            p=p@mat
        return p,dp


def run_case(pop,cols,seed,iterations):
    rng=np.random.default_rng(seed)
    d=pop.n
    visible=pop.port[:,:cols]
    # Whiten only the fixed observable span to help constraints with different units.
    uu,ss,_=np.linalg.svd(visible-visible.mean(0),full_matrices=False)
    if ss[-1]/ss[0]<1e-12: raise ValueError('dependent visible columns')
    U=uu[:,:cols]
    @lru_cache(maxsize=4)
    def values(key):
        a,b=np.frombuffer(key,dtype=np.float64).reshape(2,d)
        pa,ja=pop.endpoint(a)
        pb,jb=pop.endpoint(b)
        return pa-pb,np.vstack((ja,-jb))
    def objective(w):
        v,j=values(w.tobytes())
        return -float(v@pop.next), -(j@pop.next)
    def constraints(w):
        v,j=values(w.tobytes())
        return v@U
    def jac(w):
        v,j=values(w.tobytes())
        return (j@U).T
    start=rng.uniform(-.08,.08,2*d)
    fit=minimize(objective,start,jac=True,method='SLSQP',bounds=[(-.17,.17)]*(2*d),
                 constraints={'type':'eq','fun':constraints,'jac':jac},
                 options={'ftol':2e-12,'maxiter':iterations})
    a,b=fit.x.reshape(2,d)
    p,q=pop.endpoint(a)[0],pop.endpoint(b)[0]
    return dict(seed=seed,solver=fit.message,iterations=fit.nit,terminal_a=p.tolist(),
                terminal_b=q.tolist(),a=np.r_[a,0].tolist(),b=np.r_[b,0].tolist(),
                port_error=float(np.max(abs((p-q)@visible))),next_gap=float((p-q)@pop.next))


def torch_replay(cell,history):
    import torch
    law=cell.prices
    state=cell.initial(1)
    with torch.no_grad():
        for level in [*history,0.]:
            z=np.expm1(level)*law.B0/(law.bp*law.p.P0*.28)
            assert abs(z)<1
            msg,state=cell.step(torch.tensor([[np.arctanh(z)]],dtype=torch.float64),state)
            yield msg.flatten().tolist()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--core',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--seeds',type=int,default=4)
    p.add_argument('--iterations',type=int,default=180)
    args=p.parse_args()
    sys.path.insert(0,str(args.core.resolve()))
    import torch
    from population import BoundaryPopulation
    torch.set_num_threads(1)
    rows=[]
    for n in (8,12):
        cell=BoundaryPopulation(1,1,atoms=n)
        with torch.no_grad():
            cell.sender.weight.fill_(1)
            cell.sender.bias.zero_()
            cell.recurrent.weight.zero_()
            cell.feedback.zero_()
        pop=Population(cell)
        for cols in (3,7):
            attempts=[run_case(pop,cols,7109+s,args.iterations) for s in range(args.seeds)]
            qualified=[r for r in attempts if r['port_error']<1e-9]
            if qualified:
                chosen=max(qualified,key=lambda r:r['next_gap'])
                aa,bb=[list(torch_replay(cell,chosen[k])) for k in ('a','b')]
                delta=np.array(aa[-2])-bb[-2]
                check={'max_port_error':float(np.max(abs(delta[:cols+1]))),
                       'future_flow_gap':aa[-1][1]-bb[-1][1],
                       'numpy_gap_error':float(abs(aa[-1][1]-bb[-1][1]-chosen['next_gap'])),
                       'trajectory_a':aa,'trajectory_b':bb}
                assert check['max_port_error']<1e-8 and check['numpy_gap_error']<1e-9
            else:
                chosen=None
                check=None
            rows.append(dict(atoms=n,interlayer_width=cols+1,attempts=attempts,
                             selected_seed=chosen['seed'] if chosen else None,torch_replay=check))
            args.out.write_text(json.dumps(rows,indent=1)+'\n')
            print(n,cols, None if check is None else (check['max_port_error'],check['future_flow_gap']),flush=True)


if __name__=='__main__':
    main()
