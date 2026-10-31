"""Research-only actual CPU dtype first-hit guard, NOT HX certification."""
import math
from dataclasses import dataclass
import mpmath as mp
import torch

class UnresolvedFirstHit(ValueError): pass

@dataclass(frozen=True)
class FirstHitScreen:
    reference: float
    candidate: float
    absolute_error: float
    guard: float
    status: str
    dtype: str

def reference_integral(y,mu,sigma,T,dps=70):
    if not all(type(v) in (float,int) and math.isfinite(v) for v in (y,mu,sigma,T)) or not y>0 or not sigma>0 or not T>0:
        raise UnresolvedFirstHit('bad physical first-hit domain')
    with mp.workdps(dps):
        yy,mm,ss,tt=map(mp.mpf,(str(y),str(mu),str(sigma),str(T)))
        f=lambda t: yy/(ss*mp.sqrt(2*mp.pi*t**3))*mp.exp(-(yy+mm*t)**2/(2*ss**2*t))
        return float(mp.quad(f,[0,tt/8,tt/2,tt]))

def torch_firsthit(y,mu,sigma,T,dtype):
    kind={'fp32':torch.float32,'bf16':torch.bfloat16}.get(dtype)
    if kind is None: raise UnresolvedFirstHit('unsupported dtype')
    if not all(type(v) in (int,float) and math.isfinite(v) for v in (y,mu,sigma,T)) or not(y>0 and sigma>0 and T>0):
        raise UnresolvedFirstHit('invalid input')
    y,m,s,t=(torch.tensor(z,dtype=kind) for z in (y,mu,sigma,T))
    den=s*torch.sqrt(t)
    a=(-y-m*t)/den
    b=(-y+m*t)/den
    cdf=lambda z: 0.5*torch.erfc(-z/math.sqrt(2))
    res=cdf(a)+torch.exp(-2*m*y/(s*s))*cdf(b)
    return float(res)

def screen(y,mu,sigma,T,dtype, *, tolerance):
    if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or not 0<tolerance<1:
        raise UnresolvedFirstHit('invalid tolerance')
    ref=reference_integral(y,mu,sigma,T)
    try: result=torch_firsthit(y,mu,sigma,T,dtype)
    except (RuntimeError,OverflowError) as e: raise UnresolvedFirstHit('low precision execution failed') from e
    err=abs(ref-result)
    status='MEASURED_ONLY' if math.isfinite(result) and 0<=result<=1 and err<=tolerance else 'REFUSE'
    return FirstHitScreen(ref,result,err,tolerance,status,dtype)
