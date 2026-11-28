"""Linear response of both physical cells, including their moving endogenous walls."""
import cmath
import math
from pathlib import Path
import sys

from port import drive,rate,port_gain
from halfline import Stationary,Scalars
from stability import Transfer
from enclose import Dual,Rigorous


class Complex(Scalars):
    exp=staticmethod(cmath.exp)
    sqrt=staticmethod(cmath.sqrt)
    tanh=staticmethod(cmath.tanh)


class Cell:
    def __init__(self,u,v):
        self.u=u
        self.v=v
        real=Stationary(Rigorous,drive=Dual(str(v),1))
        self.sv=float(real.stationary(Dual(str(u)))[0].d.mid)
        self.wall_slope=float((real.B.d/real.B.v).mid)
        self.p=Stationary(Complex,drive=v)
        self.tr=Transfer(self.p,u)
        a=self.p.reset
        d=self.p.lag
        su=Stationary(Rigorous,drive=Dual(str(v))).stationary(Dual(str(u),1))[0].d
        self.dc=(a/(a+d*u)**2)*(-self.sv/float(su.mid))

    def rate_response(self,s,moving=True):
        if s==0:return self.dc
        p=self.p
        u=self.u
        speed=cmath.sqrt(u*u+4*p.D*s)
        k=2*s/(u+speed)
        lam=u/p.D
        ex=cmath.exp(-k*p.reset)
        kj=lam*(1-ex)/((p.reset+p.lag*u)*(lam+k)*(1-ex*cmath.exp(-s*p.lag)))
        return kj*(-self.sv+(s*self.wall_slope if moving else 0))/(1-self.tr.response(s))


class Cascade:
    def __init__(self,eps,kappa,src,rec="high"):
        self.eps,self.kappa=eps,kappa
        y=port_gain(eps,kappa,src,rec)
        self.R=.25*y["rate"]
        self.source=Cell(y["u"],drive(eps*self.R))
        self.receiver=Cell(y["receiver_u"],y["receiver_drive"])

    def transfer(self,s,*,moving=True,active=True):
        # g(t) multiplies the refractory-mass feedback inside its physical
        # actuator; the operating point has g=1. Both actuator lags equal 1.
        f=.25 if s==0 else (1-cmath.exp(-.25*s))/s
        a=(1-self.source.v**2)*self.eps
        source_rate=self.source.rate_response(s,moving)
        source_v=a*self.R/(1+s-(a*f*source_rate if active else 0))
        wire=self.source.wall_slope*source_v
        recv=(1-self.receiver.v**2)*self.kappa*wire/(1+s)
        return wire,self.receiver.rate_response(s,moving)*recv
