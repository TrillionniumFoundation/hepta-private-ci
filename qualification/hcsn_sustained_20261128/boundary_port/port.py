"""Steady, physical boundary-to-boundary cascade. Only one scalar leaves the sender."""
from math import exp,log,sqrt,tanh
from pathlib import Path
import sys
from scipy.optimize import brentq
from scipy.special import ndtr

sys.path.append(str(Path(__file__).resolve().parents[1]/"halfline"))
from halfline import Stationary,Scalars

BASE=-.8
TREF=.25
RESET=.30
BRACKETS={"low":(.03,.065),"high":(.25,.39)}


def drive(z,op=Scalars):
    base=op.number("-.8")
    t=op.tanh(z)
    return (base+t)/(1+base*t)


def rate(u):
    return u/(RESET+TREF*u)


def root(f,branch):
    return brentq(f,*BRACKETS[branch],xtol=1e-15,rtol=1e-15)


def port_gain(eps,kappa,source_branch,receiver_branch="high",active=True):
    p0=Stationary()
    def source(u):
        v=drive(eps*TREF*rate(u)) if active else BASE
        return Stationary(drive=v).stationary(u)[0]
    u=root(source,source_branch)
    z=TREF*rate(u)
    port=log(Stationary(drive=drive(eps*z)).B/p0.B)
    rec=Stationary(drive=drive(kappa*port))
    q=root(lambda h:rec.stationary(h)[0],receiver_branch)
    return dict(u=u,rate=rate(u),refractory=z,physical_sender_boundary=
                Stationary(drive=drive(eps*z) if active else BASE).B,
                reported_value=port,receiver_drive=rec.v,receiver_u=q,receiver_rate=rate(q))


def read_first_hit(port,kappa=1.,T=.25,x0=.18,inward=.20,sigma=.23):
    # This single-interval receiver sets its own log wall to kappa*port*t/T
    # from the shared nominal wall; it observes no sender state except port.
    mu=-inward-kappa*port/T
    width=sigma*sqrt(T)
    return ndtr((-x0-mu*T)/width)+exp(-2*mu*x0/sigma**2)*ndtr((-x0+mu*T)/width)
