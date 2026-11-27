"""R19 exact rational global COST bounds for a truly non-quotient forward Stem.

No floating-point arithmetic enters inequalities; float heap priorities only order
which exact-rational leaf gets bisected next. A retained full frontier covers
all candidate solutions on [-3,3]^2; outside is excluded by nonnegative costs.
"""
from __future__ import annotations
from fractions import Fraction as F
from pathlib import Path
from heapq import heappush, heappop
import hashlib,json,time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'asymmetric_2d'))
from certificate import quotient_gradient, G, M

ETA=F(1,25)
A=F(164044199,100000000)
B=F(42331393,100000000)
LIMIT=50000
THRESHOLD=F(1,1000)


def q(a, eta=ETA):return eta*a/(1+a*a)

def qrange(l,h, eta=ETA):
    if l>h:raise ValueError('reversed a range')
    lower=min(q(l,eta),q(h,eta))
    upper=max(q(l,eta),q(h,eta))
    if l<=-1<=h:lower=min(lower,-eta/2)
    if l<=1<=h:upper=max(upper,eta/2)
    return lower,upper

def p_range(l,h):
    if l>h:raise ValueError('reversed')
    if l<=0<=h:return F(0),max(l*l,h*h)
    return min(l*l,h*h),max(l*l,h*h)

def zrange(al,ah,bl,bh):
    t=[al*bl,al*bh,ah*bl,ah*bh]
    dl,dh=p_range(al-bh,ah-bl)
    ql,qh=qrange(al,ah)
    return (min(t),max(t)),(dl/4+ql,dh/4+qh),qh

def dist_point_interval(c,lo,hi):
    return max(F(0),lo-c,c-hi)

def setup(a=A,b=B):
    a,b=F(a),F(b)
    qc=q(a)
    tc=a*b
    uc=(a-b)**2/4+qc
    gt,gu=quotient_gradient(tc,uc,shift=1)
    et=max(abs(gt.lower()),abs(gt.upper()))
    eu=max(abs(gu.lower()),abs(gu.upper()))
    m=M
    base=qc-(et*et+eu*eu)/(2*m)
    # Candidate objective has this exact overestimate via monotonicity CE<=max.
    max_res=max(abs(x*(tc-1)+uc-1+e*F(1,10)) for x in (-1,1) for e in (-1,1))
    absolute_upper=G*(F(1,20)+G*(max_res**2+F(1,50)))+(a*a+b*b)/4
    if absolute_upper>=F(9,4):raise AssertionError('cannot exclude outside box')
    return dict(a=a,b=b,qc=qc,tc=tc,uc=uc,et=et,eu=eu,m=m,base=base,
                exact_candidate_absolute_upper=absolute_upper)

def lower(box, s):
    al,ah,bl,bh=box
    (tl,th),(ul,uh),qh=zrange(al,ah,bl,bh)
    dt=max(F(0),dist_point_interval(s['tc'],tl,th)-s['et']/s['m'])
    du=max(F(0),dist_point_interval(s['uc'],ul,uh)-s['eu']/s['m'])
    return s['base']-qh+s['m']*(dt*dt+du*du)/2

def bisect(box):
    al,ah,bl,bh=box
    if ah-al>=bh-bl:
        middle=(al+ah)/2
        return (al,middle,bl,bh),(middle,ah,bl,bh)
    middle=(bl+bh)/2
    return (al,ah,bl,middle),(al,ah,middle,bh)

def run(limit=LIMIT,threshold=THRESHOLD, a=A,b=B, store_frontier=None):
    if not (isinstance(limit,int) and 0<limit<=1000000) or not 0<threshold<=F(1,10):
        raise ValueError('bounds')
    start=time.perf_counter();s=setup(a,b)
    root=(F(-3),F(3),F(-3),F(3))
    seq=0
    heap=[(float(lower(root,s)),seq,lower(root,s),root)]
    best=lower(root,s)
    splits=0
    while heap and splits<limit:
        priority,_,bound,box=heappop(heap)
        if bound>=-threshold:
            heappush(heap,(priority,seq,bound,box))
            break
        for child in bisect(box):
            ql=lower(child,s)
            seq+=1
            heappush(heap,(float(ql),seq,ql,child))
        splits+=1
    global_lower=min(x[2] for x in heap)
    global_regret=max(F(0),-global_lower)
    receipt=dict(schema='hepta.ndu.nonquotient.forward.r19.bnb',
                 parent_r18='02c2bd45592dbe4c4156cd08fb52f58811336f1a',
                 eta=str(ETA),candidate_a=str(s['a']),candidate_b=str(s['b']),
                 gradient_coordinate_max=[str(s['et']),str(s['eu'])],
                 original_strong_convexity=str(s['m']),
                 candidate_objective_rational_upper=str(s['exact_candidate_absolute_upper']),
                 outside_box_lower='9/4',
                 global_cost_regret_rigorous_upper=str(global_regret),
                 passes_frozen_global_threshold=bool(global_regret<=threshold),
                 bnb_max_nodes=limit,nodes_split=splits,frontier_count=len(heap),
                 frontier_complete=True,global_optimum_unique_proven=False,
                 exact_quotient_convexification_valid=False,
                 all_bound_inequalities_rational=True,
                 priority_only_uses_float=True,
                 wall=time.perf_counter()-start)
    if store_frontier:
        store_frontier=Path(store_frontier)
        with store_frontier.open('x') as f:
            for priority,i,bound,box in sorted(heap,key=lambda t:t[1]):
                f.write(json.dumps(dict(id=i,lower=str(bound),bounds=list(map(str,box))))+'\n')
        receipt['frontier_sha256']=hashlib.sha256(store_frontier.read_bytes()).hexdigest()
    return receipt

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--frontier',type=Path)
    args=p.parse_args()
    receipt=run(store_frontier=args.frontier)
    with args.out.open('x') as file:
        json.dump(receipt,file,sort_keys=True,indent=2);file.write('\n')
    print(json.dumps({k:receipt[k] for k in ('nodes_split','frontier_count','global_cost_regret_rigorous_upper','passes_frozen_global_threshold','wall')}))
