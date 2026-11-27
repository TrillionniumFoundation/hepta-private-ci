"""Exact-time stopped-path checks with independent exponential censoring and a Brownian bridge."""
import json
from pathlib import Path
import numpy as np
from stopping import Model,Continuation,FirstHit

def sample(model,v,state,n,rng):
    p=model.p;bar=np.log([model.b0,model.b1]);mu=p.r-p.payout-.5*p.sigma**2
    s=np.full(n,state);x=np.full(n,np.log(v))
    active=np.ones(n,dtype=bool);hit=np.zeros(n,dtype=bool);switch=np.zeros(n,dtype=bool);events=0
    while active.any():
        i=np.flatnonzero(active);a=s[i];rate=np.where(a==0,p.up,p.down)
        initial=x[i]-bar[a]
        stopped=initial<=0
        if stopped.any():
            hit[i[stopped]]=True;active[i[stopped]]=False;i=i[~stopped];a=a[~stopped];rate=rate[~stopped];initial=initial[~stopped]
        if not i.size:break
        t=rng.exponential(1/(rate+p.discount))
        next_x=x[i]+mu*t+p.sigma*np.sqrt(t)*rng.standard_normal(len(i))
        to=next_x-bar[a]
        p_bridge=np.exp(-2*initial*np.maximum(to,0)/(p.sigma**2*t))
        cross=rng.random(len(i))<p_bridge
        dies=rng.random(len(i))<p.discount/(rate+p.discount)
        jumped=(~cross)&(~dies)&(next_x<=bar[1-a])
        hit[i[cross|jumped]]=True
        switch[i[jumped]]=True
        active[i[cross|dies|jumped]]=False
        keep=~(cross|dies|jumped)
        x[i[keep]]=next_x[keep];s[i[keep]]=1-a[keep]
        events+=len(i)
    return hit.mean(),switch.mean(),events
def main():
    e=Continuation();h=FirstHit(e);j=FirstHit(e,'switch');rng=np.random.default_rng(192427);out=[]
    for v in [0.46,.52,.61,.8,1.,1.4]:
        for s in (0,1):
            n=160000
            av,bv,events=sample(e,v,s,n,rng)
            eh=h.values([v])[0,s];ej=j.values([v])[0,s]
            row={'asset':v,'regime':s,'paths':n,'segments':events,'closed':[eh,ej],'mc':[av,bv],
                 'discounted_switch_share':ej/eh if eh>0 else 0.,
                 'z':[abs(true-est)/(np.sqrt(true*(1-true)/n)) if 0<true<1 else 0. for true,est in [(eh,av),(ej,bv)]]}
            out.append(row)
    m=max(max(r['z']) for r in out)
    assert m<5
    Path(__file__).with_name('jump_check.json').write_text(json.dumps({'samples':out,'total_paths':sum(x['paths'] for x in out),'max_mc_z':m},indent=2)+'\n')
    print('paths',sum(x['paths'] for x in out),'max z',m,'work',next(a for a in out if a['asset']==.52 and a['regime']==0))
if __name__=='__main__':main()
