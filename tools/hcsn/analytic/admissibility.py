"""Reject smooth-pasting candidates that violate local limited liability.

The explicit boundary formula solves equations, not the stopping inequality.
At a candidate with E(0)=E_x(0)=0, the equity ODE gives
E_xx(0)=-2*cashflow(0)/sigma**2. A positive boundary cashflow therefore
proves that equity is negative immediately inside the continuation region.
This necessary check is not a global optimal-stopping certificate.
"""

import math
import numpy as np


class InadmissibleBoundaryError(ValueError):
    """A boundary candidate cannot be admitted as nonnegative equity."""


def boundary_cashflow(parameters, boundary):
    p = parameters
    return (p.delta*boundary-(1-p.tax)*p.coupon
            +(p.alpha*boundary-p.principal)/p.maturity)


def require_admissible_boundary(parameters, boundary):
    """Require resolvably positive boundary curvature without clipping equity.

Reject unresolved near-zero curvature as well as strictly negative curvature.
The scaled roundoff allowance avoids certifying a sign from cancellation.
"""
    p = parameters
    if not math.isfinite(boundary) or boundary <= 0:
        raise InadmissibleBoundaryError("No positive finite boundary candidate")
    flow = boundary_cashflow(p, boundary)
    scale = (abs(p.delta*boundary)+abs((1-p.tax)*p.coupon)
             +(abs(p.alpha*boundary)+abs(p.principal))/p.maturity)
    tolerance = 64*np.finfo(float).eps*max(1., scale)
    if not math.isfinite(flow) or flow >= -tolerance:
        raise InadmissibleBoundaryError(
            "Smooth-pasting candidate fails the local limited-liability check: "
            f"boundary_cashflow={flow:.17g}, sign_tolerance={tolerance:.3g}. "
            "Positive cashflow implies negative continuation equity; "
            "near-zero curvature needs a separate degenerate-case analysis.")

