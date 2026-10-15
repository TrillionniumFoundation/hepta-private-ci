"""Exact rational 2D branch-and-bound of nested positive-risk entropic CE.

NO strong convex auxiliary optimization, interval Hessian or floating estimates.
Only exact interval range arithmetic and globally proved logcosh inequalities.
A float heap priority only chooses order; all bounds remain Fraction.
"""
from __future__ import annotations
from fractions import Fraction as F
from heapq import heappop,heappush
import time,json,hashlib
from pathlib import Path
G=F(9,10);ETA=F(1,25);COUPLING=F(1,8)
DOMAIN=F(3)


def q(v,c):return c*v/(1+v*v)
def qrange(l,h,c):
    if l>h:raise ValueError('reversed range')
    values=[q(l,c),q(h,c)]
    if l<=-1<=h:values.append(-c/2)
    if l<=1<=h:values.append(c/2)
    return min(values),max(values)

def square_range(l,h):
    if l>h:raise ValueError('reversed square')
    return (F(0) if l<=0<=h else min(l*l,h*h), max(l*l,h*h))

def cost_bounds(box,extra=True):
    al,ah,bl,bh=map(F,box)
    if al>ah or bl>bh:raise ValueError('reversed box')
    products=(al*bl,al*bh,ah*bl,ah*bh)
    tl,th=min(products),max(products)
    vl,vh=al-bh,ah-bl
    sl,sh=square_range(vl,vh)
    ql,qh=qrange(al,ah,ETA)
    zl,zh=qrange(vl,vh,COUPLING if extra else F(0))
    dl,dh=sl/4+ql+zl,sh/4+qh+zh
    ce_l_sum=F(0);ce_u_sum=F(0)
    for x in (-1,1):
        for p0 in (0,1):
            slow=[];shigh=[]
            for e1 in (-1,1):
                p1=p0^(e1==1)
                terminal_l=[];terminal_h=[]
                for e2 in (-1,1):
                    p2=p1^(e2==1)
                    # Full actual residual h2-x-1 = x*(ab-1)+d-1+eps2/10.
                    rlo,rhi=(tl-1,th-1) if x==1 else (1-th,1-tl)
                    rlo+=dl-1+F(e2,10)
                    rhi+=dh-1+F(e2,10)
                    sqlo,sqhi=square_range(rlo,rhi)
                    terminal_l.append(sqlo+F(p2,50));terminal_h.append(sqhi+F(p2,50))
                rho=F(1,2) if p1==0 else F(1)
                slow.append(F(p1,20)+G*ce_lower(terminal_l[0],terminal_l[1],rho))
                shigh.append(F(p1,20)+G*ce_upper(terminal_h[0],terminal_h[1],rho))
            rho=F(1,2) if p0==0 else F(1)
            ce_l_sum+=ce_lower(slow[0],slow[1],rho)
            ce_u_sum+=ce_upper(shigh[0],shigh[1],rho)
    al2,ah2=square_range(al,ah);bl2,bh2=square_range(bl,bh)
    return G*ce_l_sum/4+(al2+bl2)/4, G*ce_u_sum/4+(ah2+bh2)/4

def logcosh_lower(z):
    # Rigorous for any real z:
    # tanh(s) >= s-s^3/3 for s>=0, since derivative difference s²-tanh²(s)>=0.
    # integrate: logcosh z >= z²/2-z⁴/12 and >=0.
    s=z*z
    return max(F(0),s/2-s*s/12)
def logcosh_upper(z):
    # tanh(s)<=s for s>=0, hence logcosh(z)<=z²/2.
    return z*z/2

def ce_lower(v0,v1,rho):
    z=rho*(v1-v0)/2
    return (v0+v1)/2+logcosh_lower(z)/rho

def ce_upper(v0,v1,rho):
    z=rho*(v1-v0)/2
    return (v0+v1)/2+logcosh_upper(z)/rho

def bisect(box):
    al,ah,bl,bh=box
    if ah-al>=bh-bl:
        mid=(al+ah)/2
        return (al,mid,bl,bh),(mid,ah,bl,bh)
    mid=(bl+bh)/2
    return (al,ah,bl,mid),(al,ah,mid,bh)

def bnb(a,b,extra=True,threshold=F(1,100),node_cap=50000,store_frontier=None):
    if node_cap<=0 or threshold<=0:raise ValueError('cap')
    t0=time.perf_counter()
    candidate_box=(F(a),F(a),F(b),F(b))
    c_lower,c_upper=cost_bounds(candidate_box,extra)
    # Term cost >=0, positive entropic CE >= min terminal value,
    # stage >=0; outside [-3,3]^2 regularization alone >=9/4.
    if c_upper>=F(9,4):raise ValueError('outside box not excluded')
    root=(-DOMAIN,DOMAIN,-DOMAIN,DOMAIN)
    root_bound=cost_bounds(root,extra)[0]
    queue=[(float(root_bound),0,root_bound,root)]
    seq=0;split=0
    while queue and split<node_cap:
        _,_,bound,box=heappop(queue)
        if c_upper-bound<=threshold:
            heappush(queue,(float(bound),seq,bound,box))
            break
        for newbox in bisect(box):
            lo=cost_bounds(newbox,extra)[0]
            if lo>=c_upper:continue
            seq+=1
            heappush(queue,(float(lo),seq,lo,newbox))
        split+=1
    if not queue:
        lb=c_lower
    else:
        lb=min(row[2] for row in queue)
    lb=min(lb,c_lower)
    gap=max(F(0),c_upper-lb)
    receipt=dict(schema='hepta.ndu.r20.direct-interval-global-bnb.v1',
      candidate_a=str(F(a)),candidate_b=str(F(b)),extra_coupling=extra,
      candidate_cost_lower=str(c_lower),candidate_cost_rigorous_upper=str(c_upper),
      global_cost_lower=str(lb),global_regret_upper=str(gap),
      threshold=str(threshold),passes_frozen_global_threshold=gap<=threshold,
      bnb_node_cap=node_cap,nodes_split=split,frontier_count=len(queue),
      full_domain_covered=True,outside_box_lower='9/4',
      generic_parameter_space_convexity_assumed=False,
      strong_convex_auxiliary_used=False,
      nested_risk_lower='logcosh z >= max(0,z^2/2-z^4/12)',
      nested_risk_upper='logcosh z <= z^2/2',
      exact_arithmetic='Python Fraction',
      priority_only_uses_float=True,
      unique_optimum_proven=False,
      wall=time.perf_counter()-t0)
    if store_frontier:
        path=Path(store_frontier)
        with path.open('x') as f:
            for _,i,low,box in sorted(queue,key=lambda y:y[1]):
                f.write(json.dumps(dict(id=i,lower=str(low),box=list(map(str,box))))+'\n')
        receipt['frontier_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    return receipt

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--frontier',type=Path)
    p.add_argument('--a',default='1.64')
    p.add_argument('--b',default='.42')
    p.add_argument('--control',action='store_true')
    p.add_argument('--threshold',default='1/100')
    p.add_argument('--cap',type=int,default=50000)
    x=p.parse_args()
    res=bnb(F(x.a),F(x.b),not x.control,F(x.threshold),x.cap,x.frontier)
    with x.out.open('x') as f:json.dump(res,f,indent=2,sort_keys=True);f.write('\n')
    print({k:res[k] for k in ('nodes_split','frontier_count','global_regret_upper','passes_frozen_global_threshold','wall')})
