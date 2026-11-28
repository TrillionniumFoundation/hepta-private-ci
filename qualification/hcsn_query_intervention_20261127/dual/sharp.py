"""Sharp ambiguity of future event probabilities under exact equity/first-hit moment messages."""
import argparse
from pathlib import Path
import json
import sys
import warnings
import numpy as np
from scipy.optimize import linprog,brentq, OptimizeWarning
from scipy.special import ndtr,log_ndtr

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from hx_reference import Parameters,StationaryFirm

SETS={'E+F':('E','F'),'E+G':('E','G'),'E+F+G':('E','F','G'),'E+F+x':('E','F','x'),'E+F+short':('E','F','short')}

def first(firm,V,t,discount=0.):
    p=firm.params;b=firm.boundary_closed();u=np.maximum(0.,np.log(V/b))/p.volatility
    v=firm.mu/p.volatility;w=v if not discount else np.sqrt(v*v+2*discount);rt=np.sqrt(t)
    return np.minimum(1.,np.exp(np.minimum(700,(w-v)*u))*(ndtr(-u/rt-w*rt)+np.exp(-2*u*w+log_ndtr(-u/rt+w*rt))))

def program(raw,q):
    # Column conditioning preserves each moment equality.
    lo=raw.min(0);span=np.maximum(raw.max(0)-lo,1e-12);x=(raw-lo)/span
    n,k=x.shape;A=np.column_stack([np.ones(n),x]);Z=np.zeros(n)
    eq=np.vstack([np.r_[np.ones(n),Z],np.r_[Z,np.ones(n)],np.column_stack([x.T,-x.T])])
    rhs=np.r_[1.,1.,np.zeros(k)]
    opts={'primal_feasibility_tolerance':1e-10,'dual_feasibility_tolerance':1e-10,'threads':1}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',OptimizeWarning)
        pr=linprog(np.r_[-q,q],A_eq=eq,b_eq=rhs,bounds=(0.,None),method='highs',options=opts)
        # min t over -t <= q-Ac <= t.
        ub=np.vstack([np.column_stack([-A,-np.ones(n)]),np.column_stack([A,-np.ones(n)])])
        du=linprog(np.r_[np.zeros(k+1),1.],A_ub=ub,b_ub=np.r_[-q,q],bounds=[(None,None)]*(k+1)+[(0,None)],method='highs',options=opts)
    if not pr.success or not du.success:raise ArithmeticError((pr.message,du.message))
    pp,rr=np.split(pr.x,2);diff=q@(pp-rr);cm=np.stack([pp@raw,rr@raw])
    if np.max(abs(cm[0]-cm[1]))>2e-7 or abs(diff-2*du.fun)>2e-7:raise ArithmeticError('duality or moment residual')
    def compact(v):
        keep=np.where(abs(v)>1e-14)[0];return {'index':keep.tolist(),'weight':v[keep].tolist()}
    return dict(sharp_gap=float(diff),dual_twice_uniform_radius=2*du.fun,
              query_probabilities=[float(q@pp),float(q@rr)],raw_messages=cm.tolist(),
              fp32_identical=bool(np.array_equal(cm[0].astype(np.float32),cm[1].astype(np.float32))),
              max_message_difference=float(np.max(abs(cm[0]-cm[1]))),primal=[compact(pp),compact(rr)],
              dual_scaled_coefficients=du.x[:-1].tolist(),dual_uniform_residual=float(np.max(abs(q-A@du.x[:-1]))))

def run(n):
    p=Parameters();f=StationaryFirm(p,1);b=f.boundary_closed();V=np.exp(np.linspace(np.log(b),np.log(125),n));V[0]=b
    moment={'x':np.log(V/b),'E':np.array([f.equity_green(v,b) for v in V]),'F':first(f,V,1.),
            'G':first(f,V,1.,f.q),'short':first(f,V,.25)}
    # Independently invert the one-year stochastic observation for interior deterministic states.
    inversion=[]
    for point in (b+.1,70.,75.,100.,124.):
        prob=float(first(f,np.array([point]),1.)[0])
        recover=brentq(lambda z:float(first(f,np.array([z]),1.)[0])-prob,b,125,xtol=1e-11)
        inversion.append([point,prob,recover,abs(f.equity_green(point,b)-f.equity_green(recover,b))])
    rows=[]
    for intensity in (1,2,4):
        post=StationaryFirm(p,intensity)
        for time in (.125,.25,.5,1.):
            q=first(post,V,time)
            for name,names in SETS.items():
                raw=np.column_stack([moment[k] for k in names]);v=program(raw,q)
                rows.append(dict(grid=n,intensity=intensity,horizon=time,set=name,**v))
    return {'grid':n,'assets':V.tolist(),'base_boundary':b,'inversion':inversion,'rows':rows}

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('out',type=Path);op=a.parse_args();op.out.mkdir(parents=True,exist_ok=True)
    for n in (129,257,513):
        r=run(n);(op.out/f'grid_{n}.json').write_text(json.dumps(r,separators=(',',':'),allow_nan=False)+'\n')
        main=next(x for x in r['rows'] if x['set']=='E+F' and x['intensity']==4 and x['horizon']==.25)
        print(n,main['sharp_gap'],main['query_probabilities'],flush=True)
