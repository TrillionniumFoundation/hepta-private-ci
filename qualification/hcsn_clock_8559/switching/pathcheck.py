"""Independent continuous-time pricing on prescribed switching walls with exact Brownian-bridge first hits."""
import argparse
import json
from pathlib import Path
import numpy as np
from solve import R,DELTA,SIGMA,ALPHA,COUPON,PRINCIPAL


def price(walls,initial,regime,maturity,count,seed,rates=(.12,.16),premia=(.01,.04)):
    rng=np.random.default_rng(seed)
    dist=np.log(np.asarray(walls))
    x=np.full(count,np.log(initial));reg=np.full(count,regime,int)
    t=np.zeros(count);discount=np.ones(count);components=np.zeros((count,4))
    reasons=np.zeros(count,int)
    rates=np.array(rates);q=R+np.array(premia);mu=R-DELTA-SIGMA**2/2
    live=np.flatnonzero(x>dist[reg]);stopped=np.flatnonzero(x<=dist[reg])
    components[stopped,2]=ALPHA*initial/maturity;reasons[stopped]=1
    while len(live):
        i=live;s=reg[i];margin=x[i]-dist[s]
        jump=np.full(len(i),np.inf)
        can=rates[s]>0
        jump[can]=rng.exponential(1./rates[s[can]])
        left=maturity-t[i];dt=np.minimum(jump,left);switch=jump<left
        y=margin+mu*dt+SIGMA*np.sqrt(dt)*rng.standard_normal(len(i))
        # A bridge starting at margin and ending at y>0 hits zero with this conditional probability.
        hit=(y<=0)|(rng.random(len(i))<np.exp(-2.*margin*np.maximum(y,0.)/(SIGMA**2*dt)))
        length=dt.copy()
        if hit.any():
            # Conditional on crossing and the endpoint, U=tau/(dt-tau) has an inverse Gaussian law.
            m=margin[hit];end=np.maximum(np.abs(y[hit]),1e-13)
            u=rng.wald(m/end,m*m/(SIGMA**2*dt[hit]))
            length[hit]=dt[hit]*(u/(1.+u))
        dq=q[s]
        components[i,0]+=discount[i]*(COUPON/maturity)*(-np.expm1(-dq*length))/dq
        discount[i]*=np.exp(-dq*length)
        t[i]+=length
        actual=i[hit]
        components[actual,2]=discount[actual]*ALPHA*np.asarray(walls)[s[hit]]/maturity
        reasons[actual]=1
        mature=~hit&~switch
        final=i[mature];components[final,1]=discount[final]*PRINCIPAL/maturity
        alive=~hit&switch
        nextid=i[alive];x[nextid]=y[alive]+dist[s[alive]]
        reg[nextid]=1-s[alive]
        cross=x[nextid]<=dist[reg[nextid]]
        stopped=nextid[cross]
        components[stopped,3]=discount[stopped]*ALPHA*np.exp(x[stopped])/maturity
        reasons[stopped]=2
        live=nextid[~cross]
    totals=components.sum(1)
    return dict(fair_value=float(totals.mean()),standard_error=float(totals.std(ddof=1)/np.sqrt(count)),
                components=dict(zip(('coupon','principal','diffusion_recovery','jump_recovery'),components.mean(0).tolist())),
                probabilities=dict(zip(('matured','diffusion_hit','jump_hit'),(np.bincount(reasons,minlength=3)/count).tolist())),
                paths=count,seed=seed)
def main(source,out,count):
    src=json.loads((source/'SMOOTH.json').read_text());rows=[]
    for case in ('switch-4','original-4','equal-4'):
        r=next(d for d in src if d['case']==case)
        with np.load(source/(case+'.npz')) as calc:
            for k,V in enumerate((70.5,75.,100.,140.)):
                for j in (0,1):
                    pred=float(np.interp(V,calc['v'],calc['debt'][j]))
                    val=price(r['walls'],V,j,1.,count,775791+23*k+101*j,rates=r['rates'],premia=r['friction'])
                    diff=val['fair_value']-pred
                    rows.append(dict(case=case,regime=j,value=V,grid_price=pred,mc_minus_grid=diff,
                                     standardized_error=diff/val['standard_error'] if val['standard_error']>1e-11 else None,**val))
    out.write_text(json.dumps(rows,indent=1)+'\n')
    for row in rows:
        if row['case']=='switch-4':print(row['value'],row['regime'],row['fair_value'],row['grid_price'],row['standardized_error'],flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);p.add_argument('--paths',type=int,default=300000);a=p.parse_args();main(a.source,a.out,a.paths)
