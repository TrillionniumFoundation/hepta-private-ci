"""Independent *algebraic* HX boundary implicit sensitivities, f64 CPU only.

No claim about policy active-set gradients, FP32/BF16, production autodiff or
validity of a globally optimal financial default boundary.
"""
from dataclasses import dataclass, replace
import math

from .hx_coupled_smoothfit_independent import (independent_smoothfit_root, _calc_integral)
from .hx_obstacle_grid_independent import UnresolvedObstacle, _validate

@dataclass(frozen=True)
class ImplicitHXGradient:
    """Finite-difference coefficient Jacobian, *not* an autodiff/GPU kernel."""
    boundary: float
    gradients: dict[str,float]
    perturbations: dict[str,float]
    numerical_method: str = 'db/dtheta=-(b*ds/dtheta+do/dtheta)/s; coefficient differences'


def implicit_financial_boundary_gradient(p, *, fields: tuple[str,...]=(
        'rate','payout','volatility','maturity','recovery','sale_fraction'),
        nodes: int=128, log_cutoff: float=14.) -> ImplicitHXGradient:
    """Differentiate independent I(b,theta)=s(theta)*b+o(theta)=0.

    Input-coefficient derivatives use central differences, while d b/dtheta
    follows the implicit function theorem. The candidate may fail the global
    obstacle, in which case this is NOT a gradient of an admissible policy.
    Active-set switching, zero slope and out-of-domain perturbations refuse.
    """
    if not (type(fields) is tuple and fields and len(fields)==len(set(fields))):
        raise UnresolvedObstacle('invalid gradient parameter selection')
    allowed={'rate','payout','volatility','maturity','principal','coupon',
             'tax_shield','recovery','shock_intensity','sale_fraction'}
    if any(f not in allowed for f in fields):
        raise UnresolvedObstacle('unsupported gradient parameter')
    reference=independent_smoothfit_root(p,nodes=nodes,log_cutoff=log_cutoff)
    gradients={}; steps={}
    for name in fields:
        v=getattr(p,name)
        h=max(2e-5,abs(v)*1e-4)
        if not (math.isfinite(h) and math.isfinite(v-h) and math.isfinite(v+h)):
            raise UnresolvedObstacle('unrepresentable gradient perturbation')
        try:
            plus=replace(p,**{name:v+h})
            minus=replace(p,**{name:v-h})
            _validate(plus,1.,3.6,33)
            _validate(minus,1.,3.6,33)
            s_plus,o_plus,_,_,_=_calc_integral(plus,nodes,log_cutoff)
            s_minus,o_minus,_,_,_=_calc_integral(minus,nodes,log_cutoff)
        except (ValueError,TypeError,OverflowError) as exc:
            raise UnresolvedObstacle('invalid perturbed financial domain') from exc
        ds=(s_plus-s_minus)/(2*h)
        do=(o_plus-o_minus)/(2*h)
        derivative=-(reference.boundary*ds+do)/reference.slope
        if not math.isfinite(derivative):
            raise UnresolvedObstacle('nonfinite implicit gradient')
        gradients[name]=derivative
        steps[name]=h
    return ImplicitHXGradient(reference.boundary,gradients,steps)
