"""Rigorous complex-frequency enclosures by Chebyshev interpolation on ellipses."""
import argparse
import ctypes
from functools import lru_cache
import json
import math
from pathlib import Path
import time

from mpmath import iv

from enclose import Dual,Rigorous,enclosing_numbers
from halfline import Stationary
from stability import Transfer

iv.dps=65
lib=ctypes.CDLL(str(Path(__file__).with_name("cdf_point.so")))
lib.cdf_poly.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p]


@lru_cache(maxsize=20000)
def point(x,y):
    z=iv.mpc(iv.mpf(x),iv.mpf(y))
    r=abs(z)
    n=max(60,math.ceil(6*float(r.b)**2/2+42))
    buf=ctypes.create_string_buffer(480)
    lib.cdf_poly(x.encode(),y.encode(),n,buf)
    output=[buf.raw[k*120:(k+1)*120].split(b"\x00")[0].decode() for k in range(4)]
    # Lagrange's integral remainder for exp(-z^2 t^2/2), integrated t=0..1.
    b=r*r/2
    rem=r*iv.exp(b)*(b**(n+1))/(math.factorial(n+1)*(2*n+3)*iv.sqrt(2*iv.pi))
    err=iv.mpf([-1,1])*rem
    return iv.mpc(iv.mpf([output[0],output[1]])+err,iv.mpf([output[2],output[3]])+err)


def complex_interval(z):
    return z if hasattr(z,"_mpci_") else iv.mpc(z)


def cdf(z):
    t=complex_interval(z)
    x,y=[iv.nstr(k.mid,57).split(",")[0][1:] for k in (t.real,t.imag)]
    center=iv.mpc(iv.mpf(x),iv.mpf(y))
    # The line segment to the rounded binary center may leave the input
    # interval by one rounding unit; include its whole axis-aligned hull.
    rx=iv.mpf([min(t.real.a,iv.mpf(x).a),max(t.real.b,iv.mpf(x).b)])
    iy=iv.mpf([min(t.imag.a,iv.mpf(y).a),max(t.imag.b,iv.mpf(y).b)])
    deriv=iv.exp((iy**2-rx**2)/2)/iv.sqrt(2*iv.pi)
    err=iv.mpf([-1,1])*(deriv*abs(t-center)).b
    val=point(x,y)
    return val+iv.mpc(err,err)


class Complex:
    number=staticmethod(lambda x:iv.mpc(iv.mpf(x)))
    is_zero=staticmethod(lambda x:bool(complex_interval(x)==0))
    sqrt2pi=staticmethod(lambda:iv.sqrt(2*iv.pi))
    exp=staticmethod(iv.exp)
    sqrt=staticmethod(lambda z:complex_interval(z)**iv.mpf('.5'))
    phi=staticmethod(cdf)
    tanh=staticmethod(lambda z:(1-iv.exp(-2*z))/(1+iv.exp(-2*z)))


def limits(tr):
    """Upper bound the sources for the ellipse estimate using real intervals."""
    p,u=tr.p,tr.u
    assert p.A.v<0 and p.rec.v<0 and p.constant.v<0
    assert (p.A-p.rec*p.op.exp(-p.q*p.m)).v>0
    w0,wx,we,wl=[abs(t.v) for t in tr.weights]
    lam=u.v/p.D.v
    norm=(p.reset+p.lag*u).v
    I=abs((lam/norm)*(tr.moment(u/p.D,0,None)-p.op.exp(u/p.D*p.reset)*tr.moment(u/p.D,p.reset,None)).v)
    return [w0+wl*(p.A-p.rec).v,wx,we*p.B.v,I.b,lam,norm,u.v,p.D.v,p.reset.v,p.lag.v]


def bound(limits,srect,radius=None):
    """Uniform |H| bound for a complex rectangle, or |s|=radius inside it."""
    c0,c1,c2,I,lam,norm,u,D,a,d=limits
    z=u*u+4*D*srect
    speed_re=iv.sqrt((abs(z)+z.real)/2)
    if not speed_re.a>0:return None
    speed=iv.mpc(speed_re,z.imag/(2*speed_re))
    k=2*srect/(u+speed)
    t=(u+speed)/(2*D)
    kmin=k.real.a
    tmin=t.real.a
    if tmin<=1:return None
    amin=abs(srect).a if radius is None else radius
    amax=abs(srect).b if radius is None else radius
    if amin<=0:return None
    w=d*srect+k*a
    delay=iv.exp(-srect.real.a*d)
    image=iv.exp(-kmin*a)
    den=abs(1-iv.exp(-w)).a
    # Analytic factorization near s=0: w=s(d+2a/(u+speed)).
    wmax=amax*(d+2*a/(u+speed_re.a))
    if wmax<1:
        t_bound=d+2*a*(u+speed_re.a)/(u+abs(speed).b)**2
        den=max(den,(amin*t_bound*(1-wmax*iv.exp(wmax)/2)).a)
    if w.real.a>0:den=max(den,(1-iv.exp(-w.real.a)).a)
    if den<=0:return None
    speedabs=abs(speed).a
    if speedabs<=0:return None
    # For |s| small, use |k|<=2|s|/(u+Re(speed)), not a 1/s expansion.
    kr=2*amax/(u+speed_re.a)
    tr=(u+abs(speed).b)/(2*D)
    m0=c0/tmin+c1/(tmin*tmin)+c2/(tmin-1)
    mf=(c0+c1*a)/tmin+c1/(tmin*tmin)+c2*iv.exp(a)/(tmin-1)
    mb=a*(c0+c1*a+c2*iv.exp(a))*max(iv.mpf(1),image)
    if kmin>0:mb=min(mb,(c0+c1*a+c2*iv.exp(a))/kmin)
    val=(mb+mf+image*m0)/speedabs
    derivatives=(kr*(mb+image*m0)+tr*mf)/speedabs+m0/D+kr*(1+image)*delay*val/den
    return ((I+lam*D*derivatives/norm)/amin).b


def main(which,start,end,out,n=28):
    roots=json.loads(Path(__file__).with_name("enclosures.json").read_text())["roots"]
    r=json.loads(Path(__file__).with_name("sharp_roots.json").read_text())[which]["inward_drift"]
    # Keep closed literal constants highly accurate. Binary64 conversion is
    # confined to the complex normal CDF and is compensated in cdf().
    re=Stationary(Rigorous)
    ur=Dual(iv.mpf(r),1)
    h0=1-re.stationary(ur)[0].d
    reality=Transfer(re,Dual(iv.mpf(r)))
    constants=limits(reality)
    comp=Stationary(Complex)
    t=Transfer(comp,iv.mpc(iv.mpf(r)))
    evals=0
    @lru_cache(maxsize=16000)
    def eval_node(c,h,j,n):
        nonlocal evals
        a=iv.mpf(c)
        b=iv.mpf(h)
        w=a+b*iv.cos(iv.pi*j/n)
        if 0 in w and abs(w).b<iv.mpf('1e-40'):
            return h0
        evals+=1
        return t.response(iv.mpc(0,w)).real

    def interval(lo,hi):
        c=(lo+hi)/2; h=(hi-lo)/2
        # rho=2 Bernstein ellipse mapped into the s plane.
        immax=iv.mpf(c)+iv.mpf('1.25')*h
        immin=iv.mpf(c)-iv.mpf('1.25')*h
        width=iv.mpf('.75')*h
        box=iv.mpc(iv.mpf([-width,width]),iv.mpf([immin,immax]))
        if lo==0:
            # A small circle around the origin encloses the ellipse; the
            # only apparent pole there cancels on the mass-zero subspace.
            rad=iv.mpf('.0025')
            if abs(box).b>=rad:return None
            br=iv.mpc(iv.mpf([-rad,rad]),iv.mpf([-rad,rad]))
            mx=bound(constants,br,rad)
        else:
            mx=bound(constants,box)
        if mx is None:return None
        # For analytic H on rho=2, each complex-series Chebyshev coefficient
        # is at most 2M/2^j. On the real interval the interpolant's
        # error is at most 4M/2^n, including Lobatto aliasing.
        remainder=4*mx/(2**n)
        if remainder>iv.mpf('.08'):return None
        vals=[eval_node(c,h,j,n) for j in range(n+1)]
        coeff=[]
        for k in range(n+1):
            total=vals[0]/2+vals[-1]*((-1)**k)/2
            total+=sum(vals[j]*iv.cos(iv.pi*j*k/n) for j in range(1,n))
            coeff.append(total*(1 if k in (0,n) else 2)/n)
        upper=coeff[0].b+sum(abs(v).b for v in coeff[1:])+remainder
        return dict(lo=lo,hi=hi,re_H_upper=enclosing_numbers(upper)[1],
                    interpolation_error=enclosing_numbers(remainder)[1],ellipse_M=enclosing_numbers(mx)[1],
                    max_node_width=max(float(v.delta.b) for v in vals))

    rows=[]
    def cover(lo,hi,depth=0):
        value=interval(lo,hi)
        if value is not None and value["re_H_upper"]<1:
            rows.append(value)
            return
        if depth>=12 or hi-lo<3e-6:
            raise RuntimeError((lo,hi,depth,value))
        mid=(lo+hi)/2
        cover(lo,mid,depth+1)
        cover(mid,hi,depth+1)
    # Every endpoint is dyadic; every pair of adjacent pieces shares a literal
    # binary-exact endpoint. The last endpoint meets the analytic tail bound.
    base=[0.,.0009765625,.001953125,.00390625,.0078125,.015625,.03125,.0625,
          .125,.25,.5,1.,2.,4.,8.,16.,30.]
    t0=time.monotonic()
    for i in range(start,end):
        cover(base[i],base[i+1])
        print(which,i,evals,round(time.monotonic()-t0,2),max(r["re_H_upper"] for r in rows),flush=True)
    result=dict(root=which,frequency_start=base[start],frequency_end=base[end],degree=n,
                rigorous_upper_for_real_part=max(r["re_H_upper"] for r in rows),
                chebyshev_patches=rows,computed_nodes=evals)
    Path(out).write_text(json.dumps(result,indent=2)+"\n")


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("root",type=int)
    a.add_argument("start",type=int)
    a.add_argument("end",type=int)
    a.add_argument("out")
    a.add_argument("--degree",type=int,default=28)
    v=a.parse_args()
    main(v.root,v.start,v.end,v.out,v.degree)
