"""R15 directed rational global certificate for a nonaffine-in-weight two-step Stem.

The proof applies only to theta in [-2,2]^2 and the fixed 40-outcome law.
No numerical optimizer, Taylor truncation, Monte Carlo or floating gate enters.
"""
from fractions import Fraction as Q
from itertools import product
import json
from problem import XS,PS,EPS,RHO,GAMMA,KAPPA,BOX,branch,certified_leaf_hessian_lower
from intervals import I,ce,softmax,SCALE

A=Q(14778030294885026,10**16)
B=Q(-10035571846373475,10**16)
M=Q(117,160)


def rational_gradient(a=A,b=B):
    vals=[I(0),I(0)]
    for x,p0 in product(XS,PS):
        first=[]; derivatives=[]
        for e1 in EPS:
            leaves2=[branch(a,b,x,p0,e1,e2) for e2 in EPS]
            v=[I(r['l2']) for r in leaves2]
            probs=softmax(v,RHO[leaves2[0]['p1']])
            first.append(I(leaves2[0]['l1'])+GAMMA*ce(v,RHO[leaves2[0]['p1']]))
            derivatives.append([I(leaves2[0]['g1'][j])+GAMMA*sum((probs[i]*leaves2[i]['g2'][j] for i in (0,1)),I(0)) for j in (0,1)])
        probs=softmax(first,RHO[p0])
        for j in (0,1):
            vals[j]+=GAMMA*sum((probs[i]*derivatives[i][j] for i in (0,1)),I(0))/len(XS)/len(PS)
    return tuple(vals)


def lower_hessian_box():
    q=certified_leaf_hessian_lower()
    if q<=0:raise AssertionError('leaf loses convexity certificate')
    if M!=2*GAMMA*Q(13,32):raise AssertionError('basis Gram mismatch')
    return M,q


def proof():
    strong,leaf=lower_hessian_box()
    if any(not BOX[0]<t<BOX[1] for t in (A,B)):
        raise AssertionError('candidate outside certified parameter box')
    grad=rational_gradient()
    G=sum((v.max_abs() for v in grad),Q(0))
    radius=G/strong
    excess=G**2/(2*strong)
    boundary_margin=min(A-BOX[0],BOX[1]-A,B-BOX[0],BOX[1]-B)
    if not radius<boundary_margin:raise AssertionError('optimum not certified interior')
    b_limited=max(Q(0),abs(B)-radius)
    restricted_gap=strong*b_limited**2/2
    if not radius<Q(1,10**12) or not excess<Q(1,10**23):
        raise AssertionError('insufficient proof accuracy')
    if not restricted_gap>Q(1,3):raise AssertionError('restricted family not separated')
    return dict(schema='hepta.ndu.nonlinear-weight.two-step-exact.r15',
        input_support=list(map(str,XS)),support_probability='1/5',branch_probabilities=['1/2','1/2'],
        risk_parameters=list(map(str,RHO)),discount=str(GAMMA),
        polynomial_nonlinear_coefficient=str(KAPPA),
        rational_candidate=[str(A),str(B)],parameter_box=list(map(str,BOX)),
        leaf_hessian_scalar_lower=str(leaf),global_hessian_eigenvalue_lower=str(strong),
        rational_population_gradient_intervals=[dict(lo=str(v.lo),hi=str(v.hi)) for v in grad],
        gradient_L1_upper=str(G),
        true_global_optimum_distance_upper=str(radius),
        true_population_excess_upper=str(excess),
        restricted_b_zero_population_excess_lower=str(restricted_gap),
        optimal_parameter_interior_proved=True,
        parameter_nonlinearity=True,global_certification_only_in_box=True,
        nonzero_risk=True,full_branch_count=40,certified_floating_point=False,
        unrestricted_nonconvex_global_optimum_certified=False)


if __name__=='__main__':
    print(json.dumps(proof(),sort_keys=True,indent=2))
