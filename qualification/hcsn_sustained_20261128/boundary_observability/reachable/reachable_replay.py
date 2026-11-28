"""Independent NumPy/SciPy replay with the contract resolvent, scalar portfolios and no Torch."""
import argparse
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import itertools
import json
import sys
import numpy as np
from scipy.special import ndtr

ROOT=Path(__file__).resolve().parent
PORTS={'boundary':[0],'flow':[1],'priced':[1,2,3],'horizons':[4,5,6,7],'augmented':[1,2,3,4,5,6,7]}
FUTURE=(-.77,-.22,.22,.77)


def main(resolvent):
    sys.path.insert(0,str(resolvent))
    from closed_form import Prices,Contract
    base=Contract()
    price=Prices(base)
    dt=.25;s=base.sigma;mu=base.r-base.payout-.5*s*s
    def boundary(u):
        return np.log(Prices(replace(base,principal=base.principal*(1+.28*np.tanh(u)))).boundary/price.boundary)
    def hit(x,t):
        z=np.maximum(x,0.)
        w=s*np.sqrt(t)
        return np.where(x>0,ndtr((-z-mu*t)/w)+np.exp(-2*mu*z/s**2)*ndtr((-z+mu*t)/w),1.)
    raw=np.load(ROOT/'reachable.npz')
    all_bounds=json.loads((ROOT/'reachable_results.json').read_text())['rows']
    report={'source_sha256':sha256((resolvent/'closed_form.py').read_bytes()).hexdigest()}
    errors={'states':0.,'messages':0.,'targets':0.,'exact_pair_radius':0.,'convex_cert_gap':0.,
            'witness_noise_excess':0.,'convex_mass':0.}
    controls=raw['controls']
    for n in (12,32):
        grid=np.linspace(.015,1.30,n);cuts=np.r_[0.,(grid[:-1]+grid[1:])*.5,np.inf]
        reset=np.zeros(n)
        j=np.searchsorted(grid,.3);reset[j]=(.3-grid[j-1])/(grid[j]-grid[j-1])
        reset[j-1]=1-reset[j]
        kernels={}
        for old,new in itertools.product((-.55,0.,.55),repeat=2):
            x=grid+boundary(old)-boundary(new)
            weight=np.exp(-2*mu*np.maximum(x,0.)/s**2)
            a=(cuts[None,:]-x[:,None]-mu*dt)/(s*np.sqrt(dt))
            b=(cuts[None,:]+x[:,None]-mu*dt)/(s*np.sqrt(dt))
            K=np.maximum(0,np.diff(ndtr(a)-weight[:,None]*ndtr(b),axis=1))
            K[x<=0]=0
            kernels[old,new]=K,hit(x,dt)
        states=[];messages=[];tgt=[]
        for history in controls:
            mass=reset.copy();ref=0.;old=0.
            for u in history:
                K,h=kernels[old,u];newref=mass@h;mass=mass@K+ref*reset;ref=newref;old=u
            states.append(np.r_[mass,ref])
            # All histories finish with the original contract, whose independent resolvent is on the grid.
            if not messages:
                equity=np.array([price.equity(x) for x in grid])
                losses=np.array([price.credit_loss(x) for x in grid])
                hitprobes=np.stack([hit(grid,t) for t in (.08,.125,.5,3.)])
                future=np.stack([hit(grid-boundary(u),dt) for u in FUTURE])
            messages.append(np.r_[0.,ref,(mass@equity)/20,(mass@losses)/20,hitprobes@mass])
            tgt.append(future@mass)
        st=np.array(states);msg=np.array(messages);tar=np.array(tgt)
        for key,actual,expected in [('states',st,raw[f'state{n}']),('messages',msg,raw[f'message{n}']),('targets',tar,raw[f'targets{n}'])]:
            errors[key]=max(errors[key],float(np.max(abs(actual-expected))))
        for row in all_bounds:
            if row['atoms']!=n:continue
            # Recheck overlaps against original bit-exact messages to avoid machine-epsilon collisions.
            p=raw[f'message{n}'][:,PORTS[row['port']]]
            t=tar[:,FUTURE.index(row['shock'])]
            eps=row['noise'];radius=0.
            for i,q in enumerate(p):
                ok=np.max(abs(p[i:]-q),axis=1)<=2*eps
                radius=max(radius,float(np.max(abs(t[i:][ok]-t[i]))/2))
            errors['exact_pair_radius']=max(errors['exact_pair_radius'],abs(radius-row['reachable']))
            z=row['ensemble']
            def mix(pairs):
                idx,ws=zip(*pairs);weights=np.array(ws)
                errors['convex_mass']=max(errors['convex_mass'],abs(weights.sum()-1),max(0,-weights.min()))
                return weights@t[list(idx)],weights@p[list(idx)]
            ht,hp=mix(z['high']);lt,lp=mix(z['low'])
            feasible=float(max(0,np.max(abs(hp-lp))-2*eps))
            errors['witness_noise_excess']=max(errors['witness_noise_excess'],feasible)
            w=np.array(z['a'])
            bound=np.max(abs(p@w+z['intercept']-t))+eps*abs(w).sum()
            errors['convex_cert_gap']=max(errors['convex_cert_gap'],abs(bound-(ht-lt)/2))
    assert max(errors['states'],errors['messages'],errors['targets'],errors['exact_pair_radius'])<2e-11,errors
    assert errors['convex_mass']<2e-8 and errors['witness_noise_excess']<4e-8 and errors['convex_cert_gap']<5e-7,errors
    report.update(rows_checked=len(all_bounds),controls_per_grid=len(controls),errors=errors)
    (ROOT/'reachable_replay.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('resolvent',type=Path)
    main(p.parse_args().resolvent)
