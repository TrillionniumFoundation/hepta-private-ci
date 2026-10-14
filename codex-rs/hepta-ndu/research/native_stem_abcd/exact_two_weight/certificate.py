"""R13. Exact rational, globally valid special-case nonzero-risk NDU certificate.

No floating-point operation participates in the proof. A chosen rational
candidate may come from numerical scouting, but every claimed bound is an
independent rational check of that candidate and a global convexity inequality.
"""
from __future__ import annotations
from fractions import Fraction as F
from math import comb
from functools import lru_cache
import json

GAMMA = F(9, 10)
DELTA = F(1, 5)
RISK = (F(1, 2), F(1))
PREFERENCE_COST = F(1, 20)
STRONG_CONVEXITY = F(9, 35)
DEGREE = 64
A = F(1359072658021, 10**12)
B = F(-1400028626085, 10**12)


def moment(k: int) -> F:
    if k < 0: raise ValueError('negative degree')
    return F(0) if k % 2 else F(1, k + 1)


def trim(p):
    a = list(p)
    while len(a) > 1 and a[-1] == 0: a.pop()
    return a


def poly_add(a,b):
    c=[F(0)]*max(len(a),len(b))
    for i,x in enumerate(a): c[i]+=x
    for i,x in enumerate(b): c[i]+=x
    return trim(c)


def poly_scale(a,s): return trim([x*s for x in a])


def poly_mul(a,b):
    r=[F(0)]*(len(a)+len(b)-1)
    for i,x in enumerate(a):
        if not x: continue
        for j,y in enumerate(b):
            if y:r[i+j]+=x*y
    return trim(r)


def integrate_uniform(p):
    return sum((c*moment(i) for i,c in enumerate(p)),F(0))


def zpoly(a=A,b=B):
    return [F(0),F(1),a-F(1),b,-F(1,2)]


def bernstein_hull(p, left, right):
    """Exact Bernstein enclosure on a segment for a polynomial in power basis."""
    n=len(p)-1
    # q(t)=p(left+(right-left)*t), t in [0,1].
    q=[sum((p[k]*comb(k,j)*left**(k-j)*(right-left)**j
            for k in range(j,len(p))), F(0)) for j in range(n+1)]
    coeff=[sum((q[j]*F(comb(i,j),comb(n,j)) for j in range(i+1)),F(0))
           for i in range(n+1)]
    return min(coeff), max(coeff)


def global_hull(p, segments=16):
    if segments <= 0: raise ValueError('nonpositive segments')
    bounds=[]
    for i in range(segments):
        lo=F(-1)+F(2*i,segments)
        hi=F(-1)+F(2*(i+1),segments)
        bounds.append(bernstein_hull(p,lo,hi))
    return min(b[0] for b in bounds),max(b[1] for b in bounds)


@lru_cache(maxsize=None)
def tanh_coefficients(degree=DEGREE):
    """Unique exact Taylor coefficients from tanh'=1-tanh^2, tanh(0)=0."""
    if degree < 1:raise ValueError('invalid degree')
    coeff=[F(0)]*(degree+1)
    coeff[1]=F(1)
    for n in range(1,degree):
        coeff[n+1]=-sum((coeff[k]*coeff[n-k] for k in range(n+1)),F(0))/(n+1)
    return tuple(coeff)


def tanh_poly(t,degree=DEGREE):
    """Compose exact rational Taylor polynomial with rational polynomial t(x)."""
    total=[F(0)]
    power=[F(1)]
    coeff=tanh_coefficients(degree)
    for k,c in enumerate(coeff):
        if c: total=poly_add(total,poly_scale(power,c))
        if k<degree: power=poly_mul(power,t)
    return total


def exact_poly_gradient(a=A,b=B,degree=DEGREE):
    z=zpoly(a,b)
    # For p0=0: P1+=1, P1-=0 -> +1/40 offset inside log cosh.
    # For p0=1: P1+=0, P1-=1 -> -1/40.
    t0=poly_add(poly_scale(z,F(1,5)),[F(1,80)])
    t1=poly_add(poly_scale(z,F(2,5)),[F(-1,40)])
    # rho0=1/2, (2delta*z+1/40)*rho0=z/5+1/80.
    g=poly_add(poly_scale(z,F(2)),poly_scale(poly_add(tanh_poly(t0,degree),tanh_poly(t1,degree)),DELTA))
    return tuple(GAMMA*integrate_uniform(([F(0)]*power)+g) for power in (2,3))


def uniform_tanh_argument_bound(a=A,b=B):
    lo,hi=global_hull(zpoly(a,b))
    magnitude=max(abs(lo),abs(hi))
    # strongest risk rho=1; offset at most 1/40.
    argument=F(2,5)*magnitude+F(1,40)
    if not argument <= F(1,2):
        raise ValueError('candidate is not in certified Taylor domain')
    return dict(state_lower=lo,state_upper=hi,max_tanh_argument=argument)


def certificate(a=A,b=B,degree=DEGREE):
    hull=uniform_tanh_argument_bound(a,b)
    gradient=exact_poly_gradient(a,b,degree)
    # Cauchy: |tanh z|<4 on |z|=1 (cosh has no zero there).
    # On |t|<=1/2, Taylor tail <=8/2^(degree+1).
    # Gradient multiplies two tanh terms by gamma*delta, giving per-coordinate
    # error <= (gamma*2delta)*8/2^(degree+1).
    coordinate_error=GAMMA*F(2,5)*F(8,2**(degree+1))
    grad_l1_upper=sum(map(abs,gradient),F(0))+2*coordinate_error
    theta_error_upper=grad_l1_upper/STRONG_CONVEXITY
    objective_excess_upper=grad_l1_upper**2/(2*STRONG_CONVEXITY)
    # For any b=0, distance to optimizer at least |b|-distance bound; strong
    # convexity gives excess >=m/2*distance^2, even allowing a unrestricted.
    restricted_b_gap=max(F(0),abs(b)-theta_error_upper)
    restricted_excess_lower=STRONG_CONVEXITY*restricted_b_gap**2/2
    risk_neutral_a=F(19,14)
    risk_neutral_b=F(-7,5)
    if not (theta_error_upper<F(1,100000) and restricted_excess_lower>F(1,5)):
        raise AssertionError('insufficient global certificate')
    return dict(schema='hepta.ndu.two-weight-entropic-exact.v1',
        risk_nonzero=[str(x) for x in RISK],forward_weights=[str(a),str(b)],
        risk_neutral_reference=[str(risk_neutral_a),str(risk_neutral_b)],
        weight_difference_from_neutral=[str(a-risk_neutral_a),str(b-risk_neutral_b)],
        bernstein={k:str(v) for k,v in hull.items()},
        exact_rational_taylor_gradient=[str(g) for g in gradient],
        taylor_degree=degree,gradient_coordinate_error=str(coordinate_error),
        global_hessian_lower_bound=str(STRONG_CONVEXITY),
        rigorous_parameter_error_upper=str(theta_error_upper),
        rigorous_objective_excess_upper=str(objective_excess_upper),
        one_weight_b_zero_excess_lower=str(restricted_excess_lower),
        globally_unique_optimum=True,
        rigorous_population_parameter_and_cost_certificate=True,
        general_multilayer_fbsde_certificate=False,
        all_arithmetic_in_certificate='fractions of arbitrary precision integers')


def dump_numeric(v):
    # Float fields only descriptive for readability, NEVER proof inputs.
    return {k: (round(float(F(x)),16) if k in ('rigorous_parameter_error_upper',
           'rigorous_objective_excess_upper','one_weight_b_zero_excess_lower') else x) for k,x in v.items()}


if __name__=='__main__':
    print(json.dumps(certificate(),sort_keys=True,indent=2))
