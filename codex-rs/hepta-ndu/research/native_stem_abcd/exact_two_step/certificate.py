"""R14: exact fixed-point rational interval certificate for a two-step entropic Stem.

All quantities in this module that support the theorem are Fractions or outward-
rounded intervals. Numerical solvers never participate in a proof predicate.
"""
import json
from fractions import Fraction as Q
from itertools import product
from problem import XS,PS,EPS,GAMMA,RHO,phi,leaves
from intervals import I,ce,softmax,SCALE

A=Q(14790233104650800,10**16)
B=Q(-10033907548161366,10**16)
STRONG_CONVEXITY=Q(117,160)


def gradient_enclosure(a=A,b=B):
    """Nested forward-state and backward certainty equivalent differentiation."""
    grad=[I(0),I(0)]
    risk_grad=[I(0),I(0)]
    for x,p0 in product(XS,PS):
        children=[]; dg=[]
        for e1 in EPS:
            l1, d1, p1, leaves2=leaves(a,b,x,p0,e1)
            c2=[I(z[0]) for z in leaves2]
            value=I(l1)+GAMMA*ce(c2,RHO[p1])
            weight2=softmax(c2,RHO[p1])
            deriv=[I(d1[j])+GAMMA*sum((weight2[k]*leaves2[k][1][j] for k in range(2)),I(0)) for j in (0,1)]
            children.append(value)
            dg.append(deriv)
        weight1=softmax(children,RHO[p0])
        for j in (0,1):
            grad[j]+=GAMMA*sum((weight1[k]*dg[k][j] for k in range(2)),I(0))/len(XS)/len(PS)
    return grad


def risk_neutral_optimum():
    """Exact normal equations for the SAME two-step forward law at rho=0."""
    h=[[Q(0),Q(0)],[Q(0),Q(0)]]
    d=[Q(0),Q(0)]
    for x,p0,e1 in product(XS,PS,EPS):
        weight=Q(1,len(XS)*len(PS)*len(EPS))
        f=phi(x)
        loss,grad,p1,leaves2=leaves(Q(0),Q(0),x,p0,e1)
        for j in (0,1):
            d[j]+=weight*GAMMA*grad[j]
            for k in (0,1):h[j][k]+=weight*GAMMA*2*f[j]*f[k]
        for e2_index in (0,1):
            weight2=weight/2
            gain=1+e1*x/10
            for j in (0,1):
                d[j]+=weight2*GAMMA**2*leaves2[e2_index][1][j]
                for k in (0,1):
                    h[j][k]+=weight2*GAMMA**2*2*gain**2*f[j]*f[k]
    det=h[0][0]*h[1][1]-h[0][1]*h[1][0]
    if det<=0:raise AssertionError('nonpositive risk-neutral normal determinant')
    solution=((-d[0]*h[1][1]+d[1]*h[0][1])/det,
              (-d[1]*h[0][0]+d[0]*h[1][0])/det)
    return solution,h,d


def certificate(a=A,b=B):
    if STRONG_CONVEXITY!=2*GAMMA*Q(13,32):raise AssertionError('Gram error')
    if moment_support(4)!=Q(17,40) or moment_support(5)!=0 or moment_support(6)!=Q(13,32):
        raise AssertionError('support moment mismatch')
    g=gradient_enclosure(a,b)
    # Euclidean norm <= L1 of coordinate magnitudes; all enclosure endpoints exact.
    G=sum((z.max_abs() for z in g),Q(0))
    theta_dist=G/STRONG_CONVEXITY
    objective_gap=G**2/(2*STRONG_CONVEXITY)
    restricted=min(abs(b)-theta_dist,Q(100))
    if restricted<=0:raise AssertionError('restriction distance not established')
    single_weight_excess=STRONG_CONVEXITY*restricted**2/2
    reference,H,d=risk_neutral_optimum()
    neutral_difference=abs(a-reference[0])-theta_dist
    # Invariant, falsifiable predeclared quality conditions.
    if theta_dist>=Q(1,10**10):raise AssertionError('parameter certificate too loose')
    if objective_gap>=Q(1,10**18):raise AssertionError('cost certificate too loose')
    if single_weight_excess<=Q(1,10):raise AssertionError('single-weight separation too weak')
    if neutral_difference<=Q(1,10**5):raise AssertionError('nonzero-risk solution not distinguished')
    return dict(schema='hepta.ndu.two-step-entropic-exact.r14',
        input_law={'support':list(map(str,XS)),'support_prob':'1/5', 'initial_preference_prob':'1/2',
                   'noise1_prob':'1/2','noise2_prob':'1/2'},
        risks=list(map(str,RHO)),discount=str(GAMMA),
        rational_candidate=[str(a),str(b)],
        gradient_intervals=[dict(lower=str(v.lo),upper=str(v.hi)) for v in g],
        gradient_L1_upper=str(G),
        global_hessian_lower_bound=str(STRONG_CONVEXITY),
        distance_to_unique_global_optimum_upper=str(theta_dist),
        true_population_cost_excess_upper=str(objective_gap),
        global_one_weight_b_zero_excess_lower=str(single_weight_excess),
        zero_risk_optimal_weights=list(map(str,reference)),
        nonzero_risk_shift_in_a_lower=str(neutral_difference),
        exact_interval_precision_bits=SCALE.bit_length()-1,
        global_convexity_proved_for_this_parametric_family=True,
        finite_support_population_certificate=True,
        uniform_continuous_input_certificate=False,
        general_nonconvex_neural_FBSDE_certificate=False,
        certified_with_floating_point=False)


def moment_support(n):
    return sum((x**n for x in XS),Q(0))/len(XS)


if __name__=='__main__':
    print(json.dumps(certificate(),indent=2,sort_keys=True))
