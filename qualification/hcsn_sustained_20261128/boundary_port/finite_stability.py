"""Closed right-half-plane stability check at epsilon=.025 for one cascade block."""
import argparse
import json
from pathlib import Path
import sys
from mpmath import iv

from port import BASE
from halfline import Stationary
from stability import Transfer
from enclose import Rigorous,Dual,enclosing_numbers
from frequency import Complex,main as certify
from tail import high_frequency


class Augmented:
    def __init__(self,t,sv,ell,active):
        self.t,self.sv,self.ell,self.active=t,sv,ell,active

    def response(self,s):
        h=self.t.response(s)
        if not self.active:return h
        p,u=self.t.p,self.t.u
        speed=p.op.sqrt(u*u+4*p.D*s)
        k=2*s/(u+speed)
        lam=u/p.D
        image=p.op.exp(-k*p.reset)
        delay=p.op.exp(-s*p.lag)
        kj=lam*(1-image)/((p.reset+p.lag*u)*(lam+k)*(1-delay*image))
        rr=(1-delay)/s
        return h+(1-p.v*p.v)*p.op.number(".025")*rr*kj*(-self.sv+s*self.ell)/(1+s)


def extension(p,u,sv,ell):
    a,d,D=p.reset.v,p.lag.v,p.D.v
    vel=u.v
    epsgain=(1-p.v.v**2)*iv.mpf(".025")
    lam=vel/D
    n=a+d*vel

    def extra(rect,radius=None):
        z=vel*vel+4*D*rect
        sr=iv.sqrt((abs(z)+z.real)/2)
        speed=iv.mpc(sr,z.imag/(2*sr))
        k=2*rect/(vel+speed)
        amin=abs(rect).a if radius is None else radius
        amax=abs(rect).b if radius is None else radius
        pole=abs(1+rect).a
        if pole<=0:return iv.mpf("inf")
        w=rect*d+k*a
        den=abs(1-iv.exp(-w)).a
        wmax=amax*(d+2*a/(vel+sr.a))
        if wmax<1:
            bound=d+2*a*(vel+sr.a)/(vel+abs(speed).b)**2
            den=max(den,(amin*bound*(1-wmax*iv.exp(wmax)/2)).a)
        if w.real.a>0:den=max(den,(1-iv.exp(-w.real.a)).a)
        if den<=0:return iv.mpf("inf")
        # Numerator estimates retain the removable zero as s tends to 0.
        image=iv.exp(-k.real.a*a)
        num=min((1+image).b,(2*amax*a/(vel+sr.a)*max(iv.mpf(1),image)).b)
        tmin=(vel+sr.a)/(2*D)
        kj=lam*num/(n*tmin*den)
        rest=d*max(iv.mpf(1),iv.exp(-rect.real.a*d))
        return (epsgain*kj*rest*(abs(sv)+amax*abs(ell))/pole).b

    def tail(level):
        w=iv.mpf(level)
        sr=iv.sqrt((4*D*w+vel*vel)/2)
        kr=(sr-vel)/(2*D)
        image=iv.exp(-kr*a)
        tmin=(sr+vel)/(2*D)
        kj=lam*(1+image)/(n*tmin*(1-image))
        return (epsgain*kj*(2/w)*(abs(sv)/w+abs(ell))).b
    return extra,tail


def run(tag,out):
    specs=json.loads(Path(__file__).with_name("operating_points.json").read_text())
    spec=specs[tag]
    uv=iv.mpf(spec["u"]);vv=iv.mpf(spec["v"])
    real=Stationary(Rigorous,drive=Dual(vv))
    ud=Dual(uv)
    ordinary=Transfer(real,ud)
    sv_model=Stationary(Rigorous,drive=Dual(vv,1))
    sv=sv_model.stationary(ud)[0].d
    ell=(sv_model.B.d/sv_model.B.v)
    su=real.stationary(Dual(uv,1))[0].d
    act=spec["source_feedback"]
    c=Stationary(Complex,drive=iv.mpc(vv))
    tf=Augmented(Transfer(c,iv.mpc(uv)),iv.mpc(sv),iv.mpc(ell),act)
    extra,extra_tail=extension(real,ud,sv,ell)
    coeff=(1-vv**2)*iv.mpf(".025")
    jprime=real.reset.v/(real.reset.v+real.lag.v*uv)**2
    h0=1-su+(coeff*real.lag.v*jprime*(-sv) if act else 0)
    setup=(ordinary,tf,h0,extra if act else None)
    certify(0,0,16,out,28,setup)
    detail=json.loads(Path(out).read_text())
    # The original bound is serialized with an outward binary64 endpoint,
    # so it remains valid when adding the verified dynamic-loop correction.
    ball=iv.mpf(high_frequency(real,ud,"30")["absolute_H_upper"])
    if act:ball+=extra_tail("30")
    if ball.b>=1:raise ArithmeticError("right-half-plane tail")
    detail.update(tag=tag,spec=spec,tail_abs_H_upper=enclosing_numbers(ball)[1],
                  dc_return=enclosing_numbers(h0),active_refractory_loop=act)
    Path(out).write_text(json.dumps(detail,indent=2)+"\n")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("tag")
    a.add_argument("out")
    z=a.parse_args()
    run(z.tag,z.out)
