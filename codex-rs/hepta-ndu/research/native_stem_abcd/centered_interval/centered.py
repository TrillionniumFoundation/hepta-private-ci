"""Exact R22 centered-gradient intervals for the unchanged R21 forward-risk law.

The original legacy interval bound is retained; the enhanced lower is MAX of it
and a rigorous box-wide mean-value enclosure of the genuine nested derivative.
All proof-affecting calculations use fractions.Fraction, never binary64.
"""
from __future__ import annotations
from fractions import Fraction as F
from heapq import heappop,heappush
from pathlib import Path
import hashlib,json,resource,time,sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'width4_interval'))
import global_interval as old

LAMBERT_DEPTH=7
OUTWARD_SCALE=10**12
CF_ARGUMENT_SCALE=10**8

def outward(x,scale=OUTWARD_SCALE):
    """Exact integer floor/ceiling: never lose interval coverage."""
    lo,hi=x
    return F((lo*scale).numerator//(lo*scale).denominator,scale),F(-((-hi*scale).numerator//(-hi*scale).denominator),scale)

def interval_abs(x):
    return max(abs(x[0]),abs(x[1]))

def i_sub(x,y):
    return old.add(x,old.scale(y,F(-1)))

def i_div_positive(x,y):
    if y[0]<=0:raise ValueError('expected positive divisor interval')
    return old.mult(x,(F(1)/y[1],F(1)/y[0]))

def dq_bounds(v,k):
    """Exact range of q'_k(v)=k(1-v²)/(1+v²)² from endpoints and stationary points."""
    lo,hi=v
    if lo>hi or k<0:raise ValueError('dq domain')
    def value(x):return k*(1-x*x)/(1+x*x)**2
    vals=[value(lo),value(hi)]
    if lo<=0<=hi:vals.append(k)
    # q''(x)=2*k*x*(x²-3)/(1+x²)^3; +/-sqrt(3) are minima
    if (hi>0 and hi*hi>=3 and (lo<=0 or lo*lo<=3)) or (lo<0 and lo*lo>=3 and (hi>=0 or hi*hi<=3)):
        vals.append(-k/8)
    return min(vals),max(vals)

def _tanh_cf_positive(z,tail,n=LAMBERT_DEPTH):
    """Truncations of Lambert's positive continued fraction, with tail enclosures."""
    assert z>=0 and n>=1
    zz=z*z
    den=F(2*n+1)+tail
    for j in range(n-1,0,-1):den=2*j+1+zz/den
    return z/(1+zz/den)

def tanh_point_bounds(z):
    z=F(z)
    if z<0:
        lo,hi=tanh_point_bounds(-z)
        return -hi,-lo
    if z>4:return F(-1),F(1) # globally valid fallback; never extrapolate CF
    p0=_tanh_cf_positive(z,F(0))
    p1=_tanh_cf_positive(z,z*z/F(2*LAMBERT_DEPTH+3))
    return max(F(0),min(p0,p1)),min(F(1),max(p0,p1))

def tanh_interval(z):
    lo,hi=outward(z,CF_ARGUMENT_SCALE)
    if lo>hi:raise ValueError('reversed tanh argument')
    if lo<=-4 or hi>=4:return F(-1),F(1)
    return outward((tanh_point_bounds(lo)[0],tanh_point_bounds(hi)[1]))

class D:
    __slots__=('v','g')
    def __init__(self,v,g):self.v=outward(v);self.g=tuple(outward(x) for x in g)
    @classmethod
    def const(cls,n,s):
        v=(F(s),F(s)) if not isinstance(s,tuple) else s
        return cls(v,((F(0),F(0)),)*n)
    @classmethod
    def variable(cls,box,i):
        n=len(box)
        return cls(box[i],tuple((F(1),F(1)) if j==i else (F(0),F(0)) for j in range(n)))
    def __add__(self,other):
        if not isinstance(other,D):other=D.const(len(self.g),other)
        return D(old.add(self.v,other.v),[old.add(a,b) for a,b in zip(self.g,other.g)])
    __radd__=__add__
    def __neg__(self):return D(old.scale(self.v,-1),[old.scale(a,-1) for a in self.g])
    def __sub__(self,other):
        if not isinstance(other,D):other=D.const(len(self.g),other)
        return self+(-other)
    def __rsub__(self,other):return D.const(len(self.g),other)+(-self)
    def __mul__(self,other):
        if not isinstance(other,D):other=D.const(len(self.g),other)
        return D(old.mult(self.v,other.v),[old.add(old.mult(self.v,b),old.mult(other.v,a)) for a,b in zip(self.g,other.g)])
    __rmul__=__mul__
    def square(self):
        return D(old.square(self.v),[old.mult(old.scale(self.v,2),a) for a in self.g])
    def q(self,k):
        dq=dq_bounds(self.v,k)
        return D(old.qr(self.v,k),[old.mult(dq,a) for a in self.g])

def dual_ce(u,v,rho):
    """Value monotonicity + exact tanh derivative bounds of entropic 2-point CE."""
    zl=old.ce_lower(u.v[0],v.v[0],rho)
    zu=old.ce_upper(u.v[1],v.v[1],rho)
    r=old.scale(i_sub(v.v,u.v),rho/2)
    th=tanh_interval(r)
    # gradient = (du+dv)/2 + tanh(rho*(v-u)/2)*(dv-du)/2
    grad=[old.add(old.scale(old.add(a,b),F(1,2)),
                  old.scale(old.mult(th,i_sub(b,a)),F(1,2))) for a,b in zip(u.g,v.g)]
    return D((zl,zu),grad)

def gradient_bounds(box):
    """Rational component-wise Jacobian interval for the EXACT R21 nested model."""
    n=len(box)
    if n not in (2,3,4):raise ValueError('model parameter count')
    if any(l>h for l,h in box):raise ValueError('invalid parameter box')
    P=[D.variable(box,j) for j in range(n)]
    a,b=P[:2];c=P[2] if n>=3 else D.const(n,0)
    d=P[3] if n>=4 else D.const(n,0)
    v=a-b
    extra=v.square()*F(1,4)+a.q(old.ETA)+v.q(old.KAPPA)
    total=D.const(n,0)
    for x in (-1,1):
      h1=a*x+c
      common=b*h1+d*h1.square()*F(1,4)+extra
      for p0 in (0,1):
       outer=[]
       for e1 in (-1,1):
        p1=p0^(e1==1)
        leaves=[]
        for e2 in (-1,1):
          p2=p1^(e2==1)
          residual=common+F(e2,10)-x-1
          leaves.append(residual.square()+F(p2,50))
        rho=F(1,2) if p1==0 else F(1)
        outer.append(D.const(n,F(p1,20))+dual_ce(leaves[0],leaves[1],rho)*old.G)
       rho=F(1,2) if p0==0 else F(1)
       total=total+dual_ce(outer[0],outer[1],rho)*(old.G/F(4))
    return tuple(old.add(g,old.scale(vv.v,F(1,2))) for g,vv in zip(total.g,P))

def centered_lower(box):
    center=tuple((l+h)/2 for l,h in box)
    cp=tuple((c,c) for c in center)
    center_cost_l=old.cost_bounds(cp)[0]
    grads=gradient_bounds(box)
    error=sum((F(h-l,2)*interval_abs(gi) for (l,h),gi in zip(box,grads)),F(0))
    return center_cost_l-error

def hybrid_lower(box):
    orig=old.cost_bounds(box)[0]
    center=centered_lower(box)
    return max(orig,center)

def cert(n,out,mode='hybrid',node_cap=old.NODE_CAP,threshold=old.TARGET):
    if n not in (2,3,4) or mode not in ('legacy','hybrid') or node_cap<=0 or threshold<=0:
        raise ValueError('certificate mode/configuration')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();cpu=time.process_time()
    cand=tuple((F(s),F(s)) for s in old.CANDIDATES[n])
    cand_l,cand_u=old.cost_bounds(cand)
    if cand_u>=F(9,4):raise ValueError('outside root not excluded')
    root=tuple((-old.DOMAIN,old.DOMAIN) for _ in range(n))
    score=(lambda box:old.cost_bounds(box)[0]) if mode=='legacy' else hybrid_lower
    rootlo=score(root)
    heap=[(float(rootlo),0,rootlo,root)]
    seq=0;splits=0;pruned=0;peak=1;progress=[]
    with (out/'SPLITS.jsonl').open('x') as fh:
      while heap and splits<node_cap:
        best=min(x[2] for x in heap)
        gap=max(F(0),cand_u-min(cand_l,best))
        if gap<=threshold:break
        _,idx,low,box=heappop(heap)
        axis,left,right=old.bisect(box)
        rec=dict(parent_id=idx,parent_lower=str(low),parent_box=old.encode_box(box),axis=axis,children=[])
        for child in (left,right):
          cl=score(child)
          seq+=1;keep=cl<cand_u
          if keep:heappush(heap,(float(cl),seq,cl,child))
          else:pruned+=1
          rec['children'].append(dict(id=seq,box=old.encode_box(child),lower=str(cl),kept=keep))
        fh.write(json.dumps(rec,separators=(',',':'))+'\n')
        splits+=1;peak=max(peak,len(heap))
        if splits in (100,500,1000,2000,4000):
          best=min([cand_l]+[x[2] for x in heap]);progress.append(dict(splits=splits,gap=str(max(F(0),cand_u-best)),frontier=len(heap),cpu=time.process_time()-cpu))
    with (out/'FRONTIER.jsonl').open('x') as fh:
      for _,idx,lo,box in sorted(heap,key=lambda v:v[1]):
        fh.write(json.dumps(dict(id=idx,lower=str(lo),box=old.encode_box(box)),separators=(',',':')+'\n')
    global_lo=min([cand_l]+[x[2] for x in heap]);gap=max(F(0),cand_u-global_lo)
    result=dict(schema='hepta.ndu.centered-interval.r22.v1',width=n,mode=mode,
      inherited_parent='77fc87181d0abe28150b8293070bf48112bcab54',
      original_candidate=old.CANDIDATES[n],candidate_cost_upper=str(cand_u),candidate_cost_lower=str(cand_l),
      root_box=old.encode_box(root),root_lower=str(rootlo),global_lower=str(global_lo),
      global_regret_upper=str(gap),node_cap=node_cap,threshold=str(threshold),splits=splits,
      pruned=pruned,frontier_count=len(heap),max_frontier_size=peak,qualifies=gap<=threshold,
      not_qualified_reason=None if gap<=threshold else 'fixed node cap exhausted; NOT certified at threshold',
      arithmetic='Fraction only for all bounds/pruning/decisions; float priority only',
      lambert_depth=LAMBERT_DEPTH if mode=='hybrid' else None,
      exact_input_law=True,full_hessian_not_assumed=True,globally_unique_weights_not_proven=True,
      cpu=time.process_time()-cpu,wall=time.perf_counter()-started,
      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
      splits_sha256=hashlib.sha256((out/'SPLITS.jsonl').read_bytes()).hexdigest(),
      frontier_sha256=hashlib.sha256((out/'FRONTIER.jsonl').read_bytes()).hexdigest(),
      progress=progress)
    (out/'CERTIFICATE.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('width','mode','splits','qualifies','global_regret_upper','cpu','peak_rss_bytes')},sort_keys=True),flush=True)
    return result
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--width',type=int,choices=(2,3,4),required=True)
    p.add_argument('--mode',choices=('legacy','hybrid'),required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();cert(a.width,a.out,a.mode)
