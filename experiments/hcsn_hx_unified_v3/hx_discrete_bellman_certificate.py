"""EXACT-RATIONAL a-posteriori certificate for ONE FINITE HX obstacle grid.

Treat the supplied *binary64* cash flows, coefficients, and boundary values
as exact rational numbers. For the fixed-boundary discrete Bellman map

  T(V)_i=max(0, (qL*V[i-1]+qR*V[i+1]+f_i)/(r+qL+qR)),

with fixed endpoints, T is a sup-norm contraction by
  gamma=(qL+qR)/(r+qL+qR)<1.

Therefore ||V_approx-V_exact_discrete||_inf <=
  ||V_approx-T(V_approx)||_inf / (1-gamma).

The sign of the true discrete continuation advantage at node i is
certified when the candidate continuation magnitude exceeds gamma times
that bound. Otherwise it is ambiguous and MUST NOT be silently classified.

This certifies the *quantized finite-dimensional map only*: it does NOT
bound financial model/mesh/truncation/PDE time/cash-flow approximation,
full HX equilibrium or FP32/BF16/GPU arithmetic.
"""
from dataclasses import dataclass
from fractions import Fraction
import math


class UnresolvedDiscreteCertificate(ValueError):
    pass


@dataclass(frozen=True)
class FiniteBellmanCertificate:
    node_count: int
    contraction: Fraction
    max_exact_residual: Fraction
    sup_value_error_bound: Fraction
    guaranteed_continue: tuple[int, ...]
    guaranteed_stop: tuple[int, ...]
    ambiguous: tuple[int, ...]
    scientific_gate_closed: bool = False
    production_activation: bool = False
    guarantee: str = 'exact rational certificate for supplied binary64 FINITE grid only'


def certify_quantized_financial_grid(p, result) -> FiniteBellmanCertificate:
    """Independent exact-rational residual/decision gate, no PDE solver call."""
    try:
        n=result.nodes
        b=result.candidate_barrier
        L=result.log_upper
        V=result.equity_values
        debt=result.debt_values
        pfields=(p.rate,p.payout,p.volatility,p.coupon,p.principal,
                 p.tax_shield,p.maturity)
    except (TypeError,AttributeError) as e:
        raise UnresolvedDiscreteCertificate('missing fixed financial grid') from e
    if (type(n) is not int or not 33<=n<=2001 or len(V)!=n or len(debt)!=n
            or any(type(x) not in (int,float) or not math.isfinite(x)
                   for x in (*pfields,b,L,*V,*debt))
            or p.rate<=0 or p.volatility<=0 or p.maturity<=0 or
            not 0<=p.tax_shield<=1 or b<=0 or not 0<L<=12):
        raise UnresolvedDiscreteCertificate('invalid finite-grid inputs or budget')

    h=L/(n-1)
    drift=p.rate-p.payout-.5*p.volatility**2
    diff=.5*(p.volatility/h)**2
    ql=diff-drift/(2*h)
    qr=diff+drift/(2*h)
    if min(ql,qr)<0:
        ql=diff+max(0.,-drift)/h
        qr=diff+max(0.,drift)/h
    den=p.rate+ql+qr
    if not all(math.isfinite(z) and z>0 for z in (den,ql,qr)):
        raise UnresolvedDiscreteCertificate('invalid discrete generator')
    F=Fraction.from_float
    left=F(ql);right=F(qr);div=F(den)
    gamma=(left+right)/div
    if not 0<=gamma<1:
        raise UnresolvedDiscreteCertificate('Bellman map not a contraction')
    states=tuple(F(float(v)) for v in V)
    constant=(1-p.tax_shield)*p.coupon+p.principal/p.maturity
    cash=tuple(F(p.payout*b*math.exp(i*h)+debt[i]-constant)
               for i in range(n))
    residual=Fraction(0)
    continuation=[]
    for i in range(1,n-1):
        c=(left*states[i-1]+right*states[i+1]+cash[i])/div
        continuation.append(c)
        t=max(Fraction(0),c)
        residual=max(residual,abs(states[i]-t))
    e=residual/(1-gamma)
    tolerance=gamma*e
    guaranteed_continue=tuple(i+1 for i,c in enumerate(continuation) if c>tolerance)
    guaranteed_stop=tuple(i+1 for i,c in enumerate(continuation) if c<-tolerance)
    ambiguous=tuple(i+1 for i,c in enumerate(continuation) if -tolerance<=c<=tolerance)
    if len(guaranteed_continue)+len(guaranteed_stop)+len(ambiguous)!=n-2:
        raise UnresolvedDiscreteCertificate('decision partition incomplete')
    return FiniteBellmanCertificate(n,gamma,residual,e,guaranteed_continue,
                                    guaranteed_stop,ambiguous)
