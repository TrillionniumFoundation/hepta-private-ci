"""One-sided local diagnostic; never an HX global admissibility certificate.

For the smooth-fit candidate only, f(B)>0 implies E_VV(B+)<0 under the
model ODE, hence negative equity immediately above B. Numerical sign tests
below have heuristic floating-point margins, not interval-proof guarantees.
"""
from dataclasses import dataclass
import math
import sys
from .hx import HX, boundary


@dataclass(frozen=True)
class LocalAdmissibilityDiagnostic:
    asset_boundary: float
    boundary_cashflow: float
    cashflow_roundoff_margin: float
    equity_asset_curvature: float
    equity_log_curvature: float
    recovery_to_principal: float
    local_status: str
    global_status: str = 'NOT_CERTIFIED'
    numerical_certificate: bool = False


def diagnose_local_admissibility(p: HX) -> LocalAdmissibilityDiagnostic:
    """Diagnose the computed smooth-fit root without changing model outputs.

    POSITIVE_CASHFLOW_NEGATIVE_CURVATURE is a numerical witness backed by an
    analytic implication, not a formally enclosed sign result. NO_LOCAL_REJECTION
    only says this necessary test did not reject: it is expressly not PASS.
    ROUNDING_UNRESOLVED covers a cancellation-scale neighborhood of f(B)=0.
    boundary() exceptions propagate; unsupported arithmetic raises ArithmeticError.
    """
    b=boundary(p)
    terms=(p.payout*b, -(1-p.tax_shield)*p.coupon,
           p.recovery*b/p.maturity, -p.principal/p.maturity)
    if not all(math.isfinite(x) for x in terms):
        raise ArithmeticError('Local HX cashflow scale unresolved')
    f=math.fsum(terms)
    scale=math.fsum(abs(x) for x in terms)
    margin=64*sys.float_info.epsilon*scale
    if not math.isfinite(scale) or not math.isfinite(margin) or margin == 0:
        raise ArithmeticError('Local HX roundoff scale unresolved')
    # Divide sequentially instead of forming sigma^2 B^2.
    try:
        log_curvature=-2*(f/p.volatility)/p.volatility
        asset_curvature=(log_curvature/b)/b
        recovery_ratio=(p.recovery*b)/p.principal
    except (ZeroDivisionError, OverflowError) as exc:
        raise ArithmeticError('Local HX curvature scale unresolved') from exc
    if not all(math.isfinite(x) for x in (f,log_curvature,asset_curvature,recovery_ratio)):
        raise ArithmeticError('Local HX curvature scale unresolved')
    if f and (log_curvature == 0 or asset_curvature == 0):
        raise ArithmeticError('Local HX curvature underflow unresolved')
    status=('POSITIVE_CASHFLOW_NEGATIVE_CURVATURE' if f>margin else
            'NO_LOCAL_REJECTION' if f < -margin else 'ROUNDING_UNRESOLVED')
    return LocalAdmissibilityDiagnostic(b,f,margin,asset_curvature,
                                       log_curvature,recovery_ratio,status)
