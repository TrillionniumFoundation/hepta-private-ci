"""Rigorous full right half-plane tail bound for the two outer feedback resolvents."""
from pathlib import Path
import json
from mpmath import iv
from enclose import Dual, Rigorous, enclosing_numbers
from halfline import Stationary
from stability import Transfer

def high_frequency(p,u,level):
    # Characteristic H=I/s + lambda*D/(N*s)*(V'(a)-V'(0)).
    # Bounds apply simultaneously to every Re(s)>=0 and |s|>=level.
    o=p.op; a=p.reset; D=p.D
    tr=Transfer(p,u)
    w0,wx,we,wl=[abs(t.v) for t in tr.weights]
    assert p.A.v<0 and p.rec.v<0 and p.constant.v<0
    assert (p.A-p.rec*o.exp(-p.q*p.m)).v>0
    # 0<=L<=(A-rec) and 0<=E<=B exp(y) by limited liability, the
    # bond formula and Feynman-Kac, since constant-L is nonpositive.
    c0=w0+wl*(p.A-p.rec).v
    c1=wx
    c2=we*p.B.v
    x=a.v
    N=(p.reset+p.lag*u).v
    lam=(u/D).v
    I=abs((lam/N)*(tr.moment(u/D,0,None)-o.exp((u/D)*p.reset)*tr.moment(u/D,p.reset,None)).v)
    s=iv.mpf(level)
    v=u.v;d=D.v
    speed_abs_lower=iv.sqrt(4*d*s)
    speed_re_lower=iv.sqrt((4*d*s+v*v)/2)
    k=(speed_re_lower-v)/(2*d)
    t=(speed_re_lower+v)/(2*d)
    assert k>0 and t>1
    ratio=(1+v/speed_abs_lower)/(2*d)
    image=iv.exp(-k*x)
    moment0=c0/t+c1/(t*t)+c2/(t-1)
    forward=(c0+c1*x)/t+c1/(t*t)+c2*iv.exp(x)/(t-1)
    backward=(c0+c1*x+c2*iv.exp(x))/k
    total=backward+forward+image*moment0
    # Reset transform contributes k*(1-image)*exp(-sd)*V(a).
    slope_difference=ratio*total+moment0/d+ratio*total*(1+image)/(1-image)
    bound=(I+lam*d*slope_difference/N)/s
    return dict(frequency_floor=level,absolute_H_upper=enclosing_numbers(bound)[1],
                maximum_source_moment=enclosing_numbers(I)[1],
                minimum_k_real=enclosing_numbers(k)[0],minimum_t_real=enclosing_numbers(t)[0],
                growth_majorant=[enclosing_numbers(c)[1] for c in (c0,c1,c2)])

if __name__=="__main__":
    p=Stationary(Rigorous)
    rows=json.loads(Path(__file__).with_name("enclosures.json").read_text())["roots"]
    out=[]
    for j in (0,2):
        u=Dual(iv.mpf(rows[j]["inward_drift"]))
        out.append([high_frequency(p,u,str(w)) for w in (20,30,40,60,100)])
    Path(__file__).with_name("tail.json").write_text(json.dumps(out,indent=2)+"\n")
    print(out)
