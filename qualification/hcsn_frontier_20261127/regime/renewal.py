"""Laplace transform of the exact two-regime renewal flow following reset and refractory delay."""
import dataclasses
import json
from pathlib import Path
import numpy as np
from scipy.linalg import expm
from stopping import Model,Continuation,FirstHit

class Renewal:
    def __init__(self,model=Model(),reset=.30,delay=.25):
        if reset<=0 or delay<0:raise ValueError('expected positive reset and nonnegative delay')
        self.e=Continuation(model);self.k=[FirstHit(self.e,k) for k in ('cheap','dear')]
        self.reset=reset;self.delay=delay
        self.reset_values=np.array([self.e.b0,self.e.b1])*np.exp(reset)
        Q=np.array([[-model.up,model.up],[model.down,-model.down]])
        self.post=expm(Q*delay)
        U=self.exit_bank(self.reset_values)[np.arange(2),np.arange(2)]
        self.kernel=np.exp(-model.discount*delay)*U@self.post
        self.z=np.linalg.solve(np.eye(2)-self.kernel,U.sum(1))
    def exit_bank(self,v):
        return np.stack([k.values(v) for k in self.k],axis=-1)
    def values(self,v):
        p=self.e.p
        return self.exit_bank(v)@(1+np.exp(-p.discount*self.delay)*self.post@self.z)

def simulate(cell,v,s,n,rng):
    p=cell.e.p;B=np.log([cell.e.b0,cell.e.b1]);mu=p.r-p.payout-.5*p.sigma**2
    state=np.full(n,s);x=np.full(n,np.log(v));active=np.ones(n,dtype=bool);total=np.zeros(n,dtype=int)
    while active.any():
        idx=np.flatnonzero(active);a=state[idx];start=x[idx]-B[a]
        known=start<=0
        stop=idx[known];at=a[known];i=idx[~known];b=a[~known]
        if len(i):
            rate=np.where(b==0,p.up,p.down);t=rng.exponential(1/(rate+p.discount))
            to=x[i]+mu*t+p.sigma*np.sqrt(t)*rng.standard_normal(len(i))
            crossing=rng.random(len(i))<np.exp(-2*start[~known]*np.maximum(to-B[b],0)/(p.sigma**2*t))
            killed=rng.random(len(i))<p.discount/(p.discount+rate)
            jump=(~crossing)&(~killed)&(to<=B[1-b])
            dead=(~crossing)&killed
            active[i[dead]]=False
            keep=~(crossing|jump|dead)
            x[i[keep]]=to[keep];state[i[keep]]=1-b[keep]
            stop=np.r_[stop,i[crossing],i[jump]];at=np.r_[at,b[crossing],1-b[jump]]
        if len(stop):
            total[stop]+=1
            survives=rng.random(len(stop))<np.exp(-p.discount*cell.delay)
            active[stop[~survives]]=False;live=stop[survives];j=at[survives]
            after=(rng.random(len(live))>=cell.post[j,0]).astype(int)
            state[live]=after;x[live]=np.log(cell.reset_values[after])
    return total
def main():
    result=[];rng=np.random.default_rng(91530)
    for disc in (.03,.09,.30):
        model=dataclasses.replace(Model(),discount=disc)
        cell=Renewal(model)
        xx=np.geomspace(.25,10,141)
        partition=float(np.max(abs(cell.exit_bank(xx).sum(-1)-FirstHit(cell.e).values(xx))))
        reset_err=float(np.max(abs(cell.values(cell.reset_values)[np.arange(2),np.arange(2)]-cell.z)))
        samples=[]
        for v in (.52,1.0):
            for s in (0,1):
                y=simulate(cell,v,s,120000,rng);ey=cell.values([v])[0,s];se=y.std(ddof=1)/np.sqrt(len(y))
                samples.append(dict(asset=v,regime=s,paths=len(y),expected=ey,empirical=y.mean(),se=se,z=abs(ey-y.mean())/se))
        q=dict(discount=disc,maximum_exit_partition_error=partition,reset_identity_error=reset_err,
               spectral_radius=max(abs(np.linalg.eigvals(cell.kernel))),renewal_at_resets=cell.z.tolist(),mc=samples)
        assert partition<3e-14 and reset_err<3e-14 and q['spectral_radius']<1 and max(x['z'] for x in samples)<5
        result.append(q)
    Path(__file__).with_name('renewal_check.json').write_text(json.dumps(result,indent=2)+'\n')
    print([(r['discount'],r['spectral_radius'],r['renewal_at_resets'],max(x['z'] for x in r['mc'])) for r in result])
if __name__=='__main__':main()
