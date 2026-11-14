"""HX default-boundary local curvature *necessary* gate (NOT global proof).

HX equity ODE at the candidate smooth-fit boundary E(b)=E'(b)=0:
    .5*sigma²*b²*E''(b+) + f(b;b) = 0
    f(b;b)=dividend_yield*b - (1-pi)*coupon + alpha*b/m - principal/m

If f(b;b)>0, E''(b+)<0, and with C² continuation the value is
strictly NEGATIVE immediately above b. Reject. If f(b;b)<=0, global
obstacle and bond/equity fixed-point proof are STILL REQUIRED.

All inputs are finite decimal literals (strings), or integral values with
at most 30 significant decimal digits and bounded magnitude. Floats are
refused. The sign is taken from an exact finite-decimal numerator; the
reported derivative is rounded in the 120-digit arithmetic context.
This is only a *necessary sign test*, not an HX equilibrium certificate.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext


@dataclass(frozen=True)
class CurvatureVerdict:
    status: str
    boundary_cashflow: str
    boundary_second_derivative: str
    global_obstacle_certified: bool = False


def _decimal(value, name):
    if type(value) is bool or (type(value) is not str and type(value) is not int):
        raise ValueError(f'{name} must be finite decimal literal or int')
    try:
        q=Decimal(value)
    except (ValueError,InvalidOperation) as exc:
        raise ValueError(f'{name} invalid decimal') from exc
    if not q.is_finite():
        raise ValueError(f'{name} must be finite')
    if len(q.as_tuple().digits)>30 or abs(q.adjusted())>100:
        raise ValueError(f'{name} exceeds exact-sign decimal budget')
    return q


def hx_local_curvature_gate(*, boundary, dividend_yield, rollover_fraction,
                            coupon, recovery_fraction, maturity,
                            principal, sigma) -> CurvatureVerdict:
    """Return reject / ambiguous / local-necessary-only, never global PASS."""
    with localcontext() as ctx:
        ctx.prec=120
        p={k:_decimal(v,k) for k,v in locals().items() if k!='ctx'}
        b=p['boundary']; div=p['dividend_yield']; pi=p['rollover_fraction']
        c=p['coupon']; alpha=p['recovery_fraction']; m=p['maturity']
        debt=p['principal']; sig=p['sigma']
        if not (b>0 and div>=0 and 0<=pi<=1 and c>=0 and
                0<=alpha<=1 and m>0 and debt>=0 and sig>0):
            raise ValueError('invalid HX local physical parameter domain')
        # Compute sign of m*f as a finite sum of terminating decimals.
        numerator=m*div*b-m*(1-pi)*c+alpha*b-debt
        f=numerator/m
        curvature=-2*f/(sig*sig*b*b)
        if numerator>0:
            status='REJECT_NEGATIVE_LOCAL_CONTINUATION'
        elif numerator==0:
            status='UNRESOLVED_ZERO_CURVATURE'
        else:
            status='LOCAL_NECESSARY_ONLY_GLOBAL_UNCERTIFIED'
        return CurvatureVerdict(status,str(+f),str(+curvature))
