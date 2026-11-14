"""Diagnostic references only; not a replacement for the failed training mode.

represented: exact rational arithmetic on the given binary64 probabilities.
simplex: explicitly renormalize EACH raw policy in rational arithmetic first.
extended: explicitly renormalize in longdouble,with the SAME domain thresholds.
Simplex/extended are different numerical references,not silent repairs of the old
mode. Gradients are for log weights whose softmax is the normalized raw policy.
NDU reference H is the exact rational representation of rounded binary64 exp(-rhoR),
not an exact transcendental exponential. No model update or target selection here.
"""
import math
from fractions import Fraction as F
import numpy as np
from coupled_gradient import RESIDUAL_FLOOR,RELATIVE_BALANCE_TOL


def _inputs(p,q,reward,ft,fi,ts,ims,rho):
    p,q,r=np.asarray(p,dtype=float),np.asarray(q,dtype=float),np.asarray(reward,dtype=float)
    ft,fi,ts,ims=(np.asarray(x) for x in (ft,fi,ts,ims))
    if (p.shape!=(12,) or q.shape!=(12,) or r.shape!=(12,12) or not all(np.isfinite(x).all() for x in (p,q,r))
            or np.any(p<=0) or np.any(q<=0) or rho not in (0.,1.5) or np.any(r<-.35) or np.any(r>1)):
        raise ValueError('fixed finite twelve-class reference profile')
    if any(x.shape!=(12,) or x.dtype.kind not in 'iu' or np.any(x<0) or np.any(x>=12) for x in (ft,fi,ts,ims)):
        raise ValueError('fixed maps and observed semantics')
    if set(ts.tolist())!=set(range(12)) or set(ims.tolist())!=set(range(12)):raise ValueError('bijective semantics')
    matching=np.argsort(ims)[ts]
    h=r if rho==0 else np.exp(-rho*r)
    return p,q,r,ft,fi,matching,h


def rational_row(p,q,reward,ft,fi,ts,ims,rho,*,mode):
    if mode not in ('represented','simplex'):raise ValueError('explicit rational reference mode')
    p,q,r,ft,fi,matching,h=_inputs(p,q,reward,ft,fi,ts,ims,rho)
    pp=[F.from_float(float(x)) for x in p];qq=[F.from_float(float(x)) for x in q]
    original_sp,original_sq=sum(pp),sum(qq)
    if mode=='simplex':pp=[x/original_sp for x in pp];qq=[x/original_sq for x in qq]
    a=[F(0)]*12;original_b=[F(0)]*12
    for i in range(12):a[int(ft[i])]+=pp[i];original_b[int(fi[i])]+=qq[i]
    b=[original_b[int(j)] for j in matching]
    d=[min(x,y) for x,y in zip(a,b)];left=[x-y for x,y in zip(a,d)];right=[x-y for x,y in zip(b,d)]
    ra,rb=sum(left),sum(right);constant=bool(np.all(ft==ft[0]) and np.all(fi==fi[0]))
    ties=sum(x==y and x>0 for x,y in zip(a,b));balance=abs(ra-rb)/max(ra,rb) if max(ra,rb)>0 else F(0)
    joint=[[F(0) for _ in range(12)] for _ in range(12)]
    for i in range(12):
        for j in range(12):joint[i][j]=(d[i] if i==j else F(0))+(left[i]*right[j]/ra if ra>0 and rb>0 else F(0))
    total=sum(sum(row) for row in joint)
    if total<=0:raise ValueError('no reference mass')
    table=np.zeros((12,12))
    for i in range(12):
        for j in range(12):table[i,int(matching[j])]=float(joint[i][j]/total)
    hh=[[F.from_float(float(h[i,int(matching[j])])) for j in range(12)] for i in range(12)]
    weighted=sum(joint[i][j]*hh[i][j] for i in range(12) for j in range(12))
    value=float(weighted/total) if rho==0 else -math.log(float(weighted/total))/rho
    raw_error=max([abs(sum(joint[i])-a[i]) for i in range(12)]+[abs(sum(joint[i][j] for i in range(12))-b[j]) for j in range(12)])
    cdf_error=max([abs(sum(joint[i])/total-a[i]) for i in range(12)]+[abs(sum(joint[i][j] for i in range(12))/total-b[j]) for j in range(12)])
    mass_ok=(abs(sum(pp)-1)<=F.from_float(1e-10) and abs(sum(qq)-1)<=F.from_float(1e-10)
             and raw_error<=F.from_float(1e-12) and cdf_error<=F.from_float(1e-12))
    domain=mass_ok and (constant or (ties==0 and min(ra,rb)>F.from_float(float(RESIDUAL_FLOOR)) and balance<=F.from_float(float(RELATIVE_BALANCE_TOL))))
    result={'table':table,'value':value,'admitted':domain,'constant':constant,'positive_ties':ties,
        'residual_a':float(ra),'residual_b':float(rb),'relative_balance':float(balance),
        'input_mass_error_p':float(original_sp-1),'input_mass_error_q':float(original_sq-1),
        'exact_closure_identity':ra-rb==sum(pp)-sum(qq),'raw_marginal_error':float(raw_error),'cdf_marginal_error':float(cdf_error),'gradient_p':None,'gradient_q':None}
    if mode!='simplex' or not domain:return result
    if constant:
        result['gradient_p']=np.zeros(12);result['gradient_q']=np.zeros(12);return result
    alpha=[x/ra for x in left];beta=[x/ra for x in right]
    hb=[sum(hh[i][j]*beta[j] for j in range(12)) for i in range(12)]
    scalar=sum(alpha[i]*hb[i] for i in range(12));u=[x-scalar for x in hb]
    v=[sum(alpha[i]*hh[i][j] for i in range(12)) for j in range(12)]
    fp=[];fq=[]
    for i in range(12):
        t=int(a[i]<b[i]);delta=hh[i][i]-u[i]-v[i];fp.append(u[i]+t*delta);fq.append(v[i]+(1-t)*delta)
    if rho==0:dp=[-x/total for x in fp];dq=[-x/total+weighted/total**2 for x in fq]
    else:
        risk=F.from_float(rho);dp=[x/(risk*weighted) for x in fp];dq=[x/(risk*weighted)-1/(risk*total) for x in fq]
    inverse=np.argsort(matching);hp=[dp[int(ft[i])] for i in range(12)];hq=[dq[int(inverse[int(fi[i])])] for i in range(12)]
    mp=sum(pp[i]*hp[i] for i in range(12));mq=sum(qq[i]*hq[i] for i in range(12))
    result['gradient_p']=np.asarray([float(pp[i]*(hp[i]-mp)) for i in range(12)])
    result['gradient_q']=np.asarray([float(qq[i]*(hq[i]-mq)) for i in range(12)])
    return result


def extended_row(p,q,reward,ft,fi,ts,ims,rho):
    p,q,r,ft,fi,matching,h=_inputs(p,q,reward,ft,fi,ts,ims,rho)
    ld=np.longdouble
    if np.finfo(ld).eps>=np.finfo(np.float64).eps:raise RuntimeError('no extended precision; no fallback')
    pp=p.astype(ld);qq=q.astype(ld);pp/=pp.sum(dtype=ld);qq/=qq.sum(dtype=ld)
    a=np.zeros(12,dtype=ld);original_b=np.zeros(12,dtype=ld);np.add.at(a,ft,pp);np.add.at(original_b,fi,qq);b=original_b[matching]
    d=np.minimum(a,b);left=a-d;right=b-d;ra=left.sum(dtype=ld);rb=right.sum(dtype=ld)
    constant=bool(np.all(ft==ft[0]) and np.all(fi==fi[0]));ties=int(np.sum((a==b)&(a>0)));balance=abs(ra-rb)/max(ra,rb) if max(ra,rb)>0 else ld(0)
    joint=np.diag(d)
    if ra>0 and rb>0:joint+=left[:,None]*right[None,:]/ra
    total=joint.sum(dtype=ld);canonical_h=h[:,matching].astype(ld);weighted=(joint*canonical_h).sum(dtype=ld)
    table=np.zeros((12,12),dtype=ld);table[:,matching]=joint/total
    value=float(weighted/total) if rho==0 else float(-np.log(weighted/total)/ld(rho))
    raw_error=max(np.max(np.abs(joint.sum(1)-a)),np.max(np.abs(joint.sum(0)-b)))
    cdf_error=max(np.max(np.abs(joint.sum(1)/total-a)),np.max(np.abs(joint.sum(0)/total-b)))
    domain=raw_error<=1e-12 and cdf_error<=1e-12 and (constant or (ties==0 and min(ra,rb)>RESIDUAL_FLOOR and balance<=RELATIVE_BALANCE_TOL))
    result={'table':table.astype(float),'value':value,'admitted':bool(domain),'constant':constant,'positive_ties':ties,
        'residual_a':float(ra),'residual_b':float(rb),'relative_balance':float(balance),'raw_marginal_error':float(raw_error),'cdf_marginal_error':float(cdf_error),'gradient_p':None,'gradient_q':None}
    if not domain:return result
    if constant:result['gradient_p']=np.zeros(12);result['gradient_q']=np.zeros(12);return result
    alpha=left/ra;beta=right/ra;hb=canonical_h@beta;u=hb-(alpha*hb).sum(dtype=ld);v=alpha@canonical_h;t=(a<b).astype(ld)
    delta=np.diag(canonical_h)-u-v;fp=u+t*delta;fq=v+(1-t)*delta
    if rho==0:dp=-fp/total;dq=-fq/total+weighted/total**2
    else:dp=fp/(ld(rho)*weighted);dq=fq/(ld(rho)*weighted)-1/(ld(rho)*total)
    hp=dp[ft];original_dq=np.empty(12,dtype=ld);original_dq[matching]=dq;hq=original_dq[fi]
    result['gradient_p']=(pp*(hp-(pp*hp).sum(dtype=ld))).astype(float)
    result['gradient_q']=(qq*(hq-(qq*hq).sum(dtype=ld))).astype(float)
    return result
