"""Independent cashflow replay under the published discrete policy and transition law."""
import argparse
from pathlib import Path
import json
import sys
import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hx_reference import Parameters,StationaryFirm


def independent_terminal_bond(firm,v,t):
    p=firm.params;b=firm.boundary_green()
    if v<=b:return p.recovery*v/p.maturity
    x=np.log(v/b);s=p.volatility;mu=firm.mu;q=firm.q
    def density(u):
        return x/(s*np.sqrt(2.*np.pi*u**3))*np.exp(-(x+mu*u)**2/(2*s*s*u))
    s_t=s*np.sqrt(t)
    hit=ndtr((-x-mu*t)/s_t)+np.exp(-2*mu*x/(s*s))*ndtr((-x+mu*t)/s_t)
    discounted=quad(lambda u:np.exp(-q*u)*density(u),0,t,epsabs=3e-10)[0]
    survival=np.exp(-q*t)*(1.-hit)
    coupon=firm.c/q*(1.-discounted-survival)
    return coupon+firm.p*survival+p.recovery*b/p.maturity*discounted


def moments(x):
    se=x.std(ddof=1)/np.sqrt(len(x))
    return {'mean':float(x.mean()),'standard_error':float(se),
            'normal_95':[float(x.mean()-1.96*se),float(x.mean()+1.96*se)]}


def standardized_error(mean, truth, se):
    if se < 1e-14:
        if abs(mean-truth)>1e-10:raise ValueError('Deterministic payoff differs from lattice')
        return 0.
    return float((mean-truth)/se)


def replay(all_policy, assets, steps, count, seed):
    p=Parameters(); rng=np.random.default_rng(seed);v=all_policy[0]['v'];logv=np.log(v)
    n=int(all_policy[0]['n']);dt=1./n
    left=int(np.searchsorted(logv,np.log(assets),side='right')-1)
    frac=(np.log(assets)-logv[left])/(logv[left+1]-logv[left])
    ix=left+(rng.random(count)<frac).astype(int)
    history=[]
    for record in all_policy:
        firm=StationaryFirm(p,int(record['post']))
        final_tau=p.maturity-steps*dt
        debt=np.array([independent_terminal_bond(firm,a,final_tau) for a in v])
        history.append({'D':np.zeros(count),'E':np.zeros(count),'alive':np.ones(count,dtype=bool),
                        'terminal_debt':debt,'terminal_equity':record['equity'][0]})
    pre=StationaryFirm(p,int(all_policy[0]['pre']))
    du=pre.c*(-np.expm1(-pre.q*dt))/pre.q
    eu=-np.expm1(-p.rate*dt)/p.rate
    samples_outside=0
    for s in range(steps+1):
        k=steps-s; disk=np.exp(-pre.q*s*dt);erisk=np.exp(-p.rate*s*dt)
        for policy,ledger in zip(all_policy,history):
            was=ledger['alive'];now=was&policy['alive'][k,ix]
            stopped=was&~now
            ledger['D'][stopped]+=disk*p.recovery*v[ix[stopped]]/p.maturity
            if k:
                cash=p.payout*v[ix[now]]-(1.-p.tax_benefit)*p.coupon+policy['issue'][k,ix[now]]-pre.p
                ledger['E'][now]+=erisk*eu*cash
                ledger['D'][now]+=disk*du
            else:
                ledger['D'][now]+=disk*ledger['terminal_debt'][ix[now]]
                ledger['E'][now]+=erisk*ledger['terminal_equity'][ix[now]]
            ledger['alive']=now
        if k:
            u=rng.random(count);ix+=(u>=1.-float(all_policy[0]['up'])).astype(int)-(u<float(all_policy[0]['down'])).astype(int)
            samples_outside+=int(np.count_nonzero((ix<0)|(ix>=len(v))))
            if samples_outside:raise RuntimeError('A simulated path reached a truncated grid edge')
    record={'site':assets,'years_before':steps/n,'paths':count,'exits':samples_outside,'models':{}}
    grid_vals=[]
    for policy,led in zip(all_policy,history):
        name=str(int(policy['pre']))+'->'+str(int(policy['post']))
        vals={'E':np.interp(np.log(assets),logv,policy['equity'][steps]),'D':np.interp(np.log(assets),logv,policy['issue'][steps])}
        grid_vals.append(vals)
        out={}
        for y in ('E','D'):
            stats=moments(led[y]);stats['grid']=float(vals[y]);stats['z']=standardized_error(stats['mean'],vals[y],stats['standard_error'])
            out[y]=stats
        record['models'][name]=out
    delta={}
    for y in ('E','D'):
        m=moments(history[1][y]-history[0][y]);m['grid']=float(grid_vals[1][y]-grid_vals[0][y])
        m['z']=standardized_error(m['mean'],m['grid'],m['standard_error'])
        delta[y]=m
    record['paired_announcement_minus_constant']=delta
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('grid_dir',type=Path);parser.add_argument('--count',type=int,default=160000)
    a=parser.parse_args();pol=[np.load(a.grid_dir/f'policy_256_1_{post}.npz') for post in (1,4)]
    stored=[dict(p) for p in pol]
    rows=[replay(stored,x,64,a.count,855927+int(x)) for x in (65.,75.,100.,125.)]
    path=a.grid_dir/'monte_carlo.json';path.write_text(json.dumps(rows,indent=1,allow_nan=False)+'\n')
    print('max abs z',max(abs(row['models'][name][key]['z']) for row in rows for name in row['models'] for key in ('D','E')),flush=True)
