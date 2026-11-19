"""R21 exact Fraction N-dimensional 2/3/4 forward-weight direct entropic B&B.

No convex quotient or Hessian is used. The float heap key changes only search
order; all pruning, bound comparisons, outputs and decisions are Fraction.
"""
from fractions import Fraction as F
from heapq import heappop, heappush
from pathlib import Path
import hashlib,json,time,resource

G=F(9,10);ETA=F(1,25);KAPPA=F(1,8);DOMAIN=F(3)
CANDIDATES={
 2:['1.546968894170478','0.448874006060473'],
 3:['0.724272383498535','1.076854103128394','0.727904342674089'],
 4:['0.766767953723746','0.924372831675018','0.754668981051615','0.360581962736983']}
NODE_CAP=4000;TARGET=F(1,100)

def add(a,b):return(a[0]+b[0],a[1]+b[1])
def plus(a,s):return(a[0]+s,a[1]+s)
def scale(a,s):return(a[0]*s,a[1]*s) if s>=0 else(a[1]*s,a[0]*s)
def mult(a,b):
    v=(a[0]*b[0],a[0]*b[1],a[1]*b[0],a[1]*b[1]);return(min(v),max(v))
def square(v):return (F(0) if v[0]<=0<=v[1] else min(v[0]**2,v[1]**2),max(v[0]**2,v[1]**2))
def qr(v,k):
    if k<0:raise ValueError('negative coefficient')
    lo,hi=v
    if lo>hi:raise ValueError('reversed interval')
    vals=[k*lo/(1+lo*lo),k*hi/(1+hi*hi)]
    if lo<=-1<=hi:vals.append(-k/2)
    if lo<=1<=hi:vals.append(k/2)
    return min(vals),max(vals)
def logcosh_lower(z):
    t=z*z;return max(F(0),t/2-t*t/12)
def logcosh_upper(z):return z*z/2
def ce_lower(v0,v1,rho):
    z=rho*(v1-v0)/2
    return (v0+v1)/2+logcosh_lower(z)/rho
def ce_upper(v0,v1,rho):
    z=rho*(v1-v0)/2
    return (v0+v1)/2+logcosh_upper(z)/rho

def cost_bounds(box):
    n=len(box)
    if n not in (2,3,4):raise ValueError('width must be 2,3,4')
    if any(l>h for l,h in box):raise ValueError('reversed parameter box')
    a,b=box[:2];c=box[2] if n>2 else (F(0),F(0));d=box[3] if n>3 else (F(0),F(0))
    v=add(a,scale(b,-1))
    common=add(add(scale(square(v),F(1,4)),qr(a,ETA)),qr(v,KAPPA))
    reg=sum((square(vv)[0] for vv in box),F(0))/4
    reg_upper=sum((square(vv)[1] for vv in box),F(0))/4
    lower=F(0);upper=F(0)
    for x in (-1,1):
      h1=add(scale(a,F(x)),c)
      h2_noeps=add(add(mult(b,h1),scale(mult(d,square(h1)),F(1,4))),common)
      for p0 in (0,1):
       lows=[];highs=[]
       for e1 in (-1,1):
        p1=p0^(e1==1)
        term_l=[];term_h=[]
        for e2 in (-1,1):
         p2=p1^(e2==1)
         residual=plus(h2_noeps,F(e2,10)-x-1)
         sl,sh=square(residual)
         term_l.append(sl+F(p2,50));term_h.append(sh+F(p2,50))
        risk=F(1,2) if p1==0 else F(1)
        lows.append(F(p1,20)+G*ce_lower(term_l[0],term_l[1],risk))
        highs.append(F(p1,20)+G*ce_upper(term_h[0],term_h[1],risk))
       risk=F(1,2) if p0==0 else F(1)
       lower+=G*ce_lower(lows[0],lows[1],risk)/4
       upper+=G*ce_upper(highs[0],highs[1],risk)/4
    return lower+reg,upper+reg_upper

def bisect(box):
    idx=max(range(len(box)),key=lambda i:(box[i][1]-box[i][0],-i))
    l,h=box[idx];middle=(l+h)/2
    left=list(box);right=list(box)
    left[idx]=(l,middle);right[idx]=(middle,h)
    return idx,tuple(left),tuple(right)

def encode_box(box):return [[str(l),str(h)] for l,h in box]
def decode_box(data):return tuple((F(l),F(h)) for l,h in data)

def cert(n,output,node_cap=NODE_CAP,threshold=TARGET):
    if n not in (2,3,4) or node_cap<=0 or threshold<=0:raise ValueError('configuration')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    wall=time.perf_counter();cpu=time.process_time()
    candidate=tuple((F(s),F(s)) for s in CANDIDATES[n]);candidate_l,candidate_u=cost_bounds(candidate)
    if not candidate_u<F(9,4):raise ValueError('outside domain not excluded by nonnegative loss')
    root=tuple((-DOMAIN,DOMAIN) for _ in range(n))
    root_lo=cost_bounds(root)[0]
    heap=[(float(root_lo),0,root_lo,root)]
    seq=0;split=0;pruned=0;max_heap=1;progress=[]
    splitf=(output/'SPLITS.jsonl').open('x')
    def snapshot():
        current=min((entry[2] for entry in heap),default=candidate_l)
        gap=max(F(0),candidate_u-min(current,candidate_l))
        progress.append(dict(splits=split,frontier_count=len(heap),lower=str(min(current,candidate_l)),gap=str(gap),cpu=time.process_time()-cpu))
        return gap
    snapshot()
    while heap and split<node_cap:
        _,idx,lower,box=heappop(heap)
        if candidate_u-lower<=threshold:
            heappush(heap,(float(lower),idx,lower,box));break
        direction,left,right=bisect(box)
        record=dict(parent_id=idx,parent_box=encode_box(box),parent_lower=str(lower),axis=direction,children=[])
        for half in (left,right):
            low=cost_bounds(half)[0]
            keep=low<candidate_u
            seq+=1
            if keep:heappush(heap,(float(low),seq,low,half))
            else:pruned+=1
            record['children'].append(dict(id=seq,box=encode_box(half),lower=str(low),kept=keep))
        splitf.write(json.dumps(record,separators=(',',':'))+'\n')
        split+=1;max_heap=max(max_heap,len(heap))
        if split in (100,500,1000,2000,4000):snapshot()
    splitf.close()
    final_gap=snapshot()
    fpath=output/'FRONTIER.jsonl'
    with fpath.open('x') as f:
        for _,idx,low,box in sorted(heap,key=lambda r:r[1]):
            f.write(json.dumps(dict(id=idx,lower=str(low),box=encode_box(box)),separators=(',',':'))+'\n')
    lb=min([candidate_l]+[r[2] for r in heap]);gap=max(F(0),candidate_u-lb)
    if gap!=final_gap:raise AssertionError('progress gap mismatch')
    evidence=dict(schema='hepta.ndu.r21.direct-multidimensional.v1',width=n,
       candidate=CANDIDATES[n],candidate_cost_lower=str(candidate_l),candidate_cost_upper=str(candidate_u),
       global_lower=str(lb),global_regret_upper=str(gap),threshold=str(threshold),
       qualifies=gap<=threshold,node_cap=node_cap,splits=split,pruned=pruned,
       frontier_count=len(heap),max_frontier_size=max_heap,progress=progress,
       root_box=encode_box(root),root_lower=str(root_lo),
       outside_domain_cost_lower='9/4',rigorous_positive_risk=True,
       fractional_bounds_only=True,priority_float_only=True,
       globally_unique_optimum_proven=False,model_is_truly_four_parameter=(n==4),
       quadratic_convex_auxiliary_used=False,
       reason_if_not_qualified='node cap reached with uncertified global gap' if gap>threshold else None,
       proof_scope='known two-step 16-leaf positive-risk finite-state toy system',
       splits_sha256=hashlib.sha256((output/'SPLITS.jsonl').read_bytes()).hexdigest(),
       frontier_sha256=hashlib.sha256(fpath.read_bytes()).hexdigest(),
       wall=time.perf_counter()-wall,cpu=time.process_time()-cpu,
       peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    (output/'CERTIFICATE.json').write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:evidence[k] for k in ('width','splits','frontier_count','global_regret_upper','qualifies','cpu')},sort_keys=True),flush=True)
    return evidence

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--width',type=int,required=True,choices=(2,3,4));p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();cert(args.width,args.out)
