"""R11 analytic real-arithmetic population bounds. Conservative, NOT FP interval proof.

For frozen, known three-step feedback, recursively majorize the coordinatewise
first and second state derivatives of the full recursive cost over the entire
compact initial-state support. Combine with exact-rational tensor W1 transport.
Never infer a derivative supremum from sampled finite-difference gradients.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_CEILING, localcontext
from fractions import Fraction
from pathlib import Path
import math
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scaling'))
from wide import WidePolicy, make_problem, SCALE, rule


def dfloat(f):
    """Exact decimal representation of an IEEE754 binary64, before operations."""
    return Decimal.from_float(float(f))


def positive_matmul(a, b):
    if not a or not b or len(a[0]) != len(b):
        raise ValueError('matrix shapes')
    return [[sum((a[i][k]*b[k][j] for k in range(len(b))), Decimal(0))
             for j in range(len(b[0]))] for i in range(len(a))]


def global_majorants(theta: np.ndarray, width: int) -> dict:
    """Sound derivative majorants for exact-real rollout and displayed float weights.

    Computed by directed upward Decimal operations, tanh'<=1, |tanh''|<=1;
    entropic f' is convex-combined and |f''|<=max|v''|+eta(max|v'|)^2.
    The output is NOT a claim of interval-certified evaluation of Q(theta).
    """
    arr = np.asarray(theta, dtype=np.float64)
    if not np.isfinite(arr).all() or len(arr) != 50+7*width:
        raise ValueError('invalid parameters')
    policy = WidePolicy(width)
    p = make_problem()
    K, W, b, V, c = policy.unpack(arr)
    del b, c  # Their values can affect outcomes, not global derivative bounds.
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 100, ROUND_CEILING
        zero, one = Decimal(0), Decimal(1)
        horizon = p.horizon
        if horizon != 3 or p.eta < 0 or p.gamma < 0 or p.quartic < 0:
            raise ValueError('outside the proved profile')
        A = [[dfloat(abs(p.A[i,j])) for j in range(2)] for i in range(2)]
        B = [[dfloat(abs(p.B[i,j])) for j in range(2)] for i in range(2)]
        SW = [[dfloat(abs(W[t,j])) for j in range(4)] for t in range(width)]
        SV = [[dfloat(abs(V[i,t])) for t in range(width)] for i in range(2)]
        VW = positive_matmul(SV, SW)
        hbound = [dfloat(a) for a in SCALE[:2]]
        xbound = [dfloat(a) for a in SCALE[2:]]
        hprime = [[one if i==j else zero for j in range(4)] for i in range(2)]
        hsecond = [[zero for _ in range(4)] for _ in range(2)]
        xprime = [[one if i+2==j else zero for j in range(4)] for i in range(2)]
        stagebounds = []
        gamma,eta,q,U,cs = map(dfloat, (p.gamma,p.eta,p.quartic,p.bound,p.state_cost))
        cm = max(dfloat(v) for v in p.action_cost)
        nmax = [max(dfloat(abs(p.noise[m,i])) for m in range(2)) for i in range(2)]
        for step in range(horizon):
            L = [[max(dfloat(abs(K[step,m,i,j])) for m in range(2)) + VW[i][j]
                  for j in range(4)] for i in range(2)]
            sprime = hprime + xprime
            ssecond = hsecond + [[zero]*4 for _ in range(2)]
            aprime = positive_matmul(L, sprime)
            linear_second = positive_matmul(L, ssecond)
            wprime = positive_matmul(SW, sprime)
            adouble = [[linear_second[i][j] +
                        sum((SV[i][t]*wprime[t][j]**2 for t in range(width)), zero)
                        for j in range(4)] for i in range(2)]
            uprime = aprime
            udouble = [[adouble[i][j]+aprime[i][j]**2/U for j in range(4)] for i in range(2)]
            first = [cs*sum((hbound[i]*hprime[i][j] for i in range(2)),zero) +
                     cm*U*sum((uprime[i][j] for i in range(2)),zero)
                     for j in range(4)]
            second = [cs*sum((hprime[i][j]**2+hbound[i]*hsecond[i][j] for i in range(2)),zero) +
                      cm*sum((uprime[i][j]**2+U*udouble[i][j] for i in range(2)),zero)
                      for j in range(4)]
            stagebounds.append((first,second))
            hn1=positive_matmul(A, hprime)
            hn2=positive_matmul(B, uprime)
            hprime=[[hn1[i][j]+hn2[i][j] for j in range(4)] for i in range(2)]
            hd1=positive_matmul(A, hsecond)
            hd2=positive_matmul(B, udouble)
            hsecond=[[hd1[i][j]+hd2[i][j] for j in range(4)] for i in range(2)]
            hh1 = positive_matmul(A, [[v] for v in hbound])
            hh2 = positive_matmul(B, [[U],[U]])
            hbound=[hh1[i][0]+hh2[i][0]+nmax[i] for i in range(2)]

        # Terminal target is x@T.T + .18*(x_0*x_1, sin(x_0+x_1)).
        d18=dfloat(.18)
        target=[sum((dfloat(abs(p.target[i,j]))*xbound[j] for j in range(2)),zero)
                + (d18*xbound[0]*xbound[1] if i==0 else d18)
                for i in range(2)]
        targetprime=[[zero]*4 for _ in range(2)]
        targetprime[0][2]=dfloat(abs(p.target[0,0]))+d18*xbound[1]
        targetprime[0][3]=dfloat(abs(p.target[0,1]))+d18*xbound[0]
        targetprime[1][2]=dfloat(abs(p.target[1,0]))+d18
        targetprime[1][3]=dfloat(abs(p.target[1,1]))+d18
        targetsecond=[[zero]*4 for _ in range(2)]
        targetsecond[1][2]=targetsecond[1][3]=d18
        err=[hbound[i]+target[i] for i in range(2)]
        R=[[dfloat(abs(p.readouts[i,j])) for j in range(2)] for i in range(3)]
        rb=[sum((R[i][l]*err[l] for l in range(2)),zero) for i in range(3)]
        rp=positive_matmul(R,[[hprime[i][j]+targetprime[i][j] for j in range(4)] for i in range(2)])
        rpp=positive_matmul(R,[[hsecond[i][j]+targetsecond[i][j] for j in range(4)] for i in range(2)])
        wa=[max(dfloat(p.weights[m,i]) for m in range(2)) for i in range(3)]
        gp=[rb[i]+q*rb[i]**3 for i in range(3)]
        gpp=[one+3*q*rb[i]**2 for i in range(3)]
        first=[sum((wa[i]*gp[i]*rp[i][j] for i in range(3)),zero) for j in range(4)]
        second=[sum((wa[i]*(gpp[i]*rp[i][j]**2+gp[i]*rpp[i][j]) for i in range(3)),zero)
                for j in range(4)]
        checkpoints=[dict(level='terminal', first=[str(v) for v in first], second=[str(v) for v in second])]
        for step in reversed(range(horizon)):
            sf,ss=stagebounds[step]
            # IMPORTANT: second derivative uses CHILD first derivative.
            next_second=[ss[j]+gamma*(second[j]+eta*first[j]**2) for j in range(4)]
            next_first=[sf[j]+gamma*first[j] for j in range(4)]
            first,second=next_first,next_second
            checkpoints.append(dict(level=f'level-{step}', first=[str(v) for v in first],
                                    second=[str(v) for v in second]))
        def ceil_binary(d: Decimal) -> float:
            f=float(d)
            while Decimal.from_float(f)<d:
                f=math.nextafter(f, math.inf)
            return f
        return dict(first=[ceil_binary(v) for v in first],
                    second=[ceil_binary(v) for v in second],
                    first_decimal=[str(v) for v in first],
                    second_decimal=[str(v) for v in second],
                    checkpoints=checkpoints,
                    theorem='global exact-real coordinatewise derivatives; directed Decimal arithmetic',
                    machine_interval_evaluation_certified=False)


def one_dimensional_rule(name: str):
    """The exact binary64 abscissae/weights used to construct product rules."""
    if name.startswith('gl'):
        n=int(name[2:]); assert n in (5,7,9,11)
        x,w=np.polynomial.legendre.leggauss(n)
        w=w/2
    elif name.startswith('cc'):
        n=int(name[2:]); assert n in (5,9,17)
        x=np.cos(np.pi*np.arange(n)/(n-1)); x[n//2]=0.
        moments=np.zeros(n); moments[0]=1.
        w=np.linalg.solve(np.polynomial.legendre.legvander(x,n-1).T,moments)
    else:
        raise ValueError('unknown rule')
    if (w<=0).any() or not np.isfinite(x).all() or not np.isfinite(w).all():
        raise ValueError('non-positive rule')
    return x,w


def wasserstein_uniform_1d(nodes: np.ndarray, weights: np.ndarray, scale: float) -> Fraction:
    """Exact-rational W1 of uniform[-a,a] against float-atom weighted quadrature.

    Normalizes exact rational weights, independently of float sum reduction.
    Quantile coupling is optimal for W1 in one dimension.
    """
    if len(nodes)!=len(weights) or scale<=0:
        raise ValueError('rule shapes')
    ordered=sorted(zip(nodes, weights), key=lambda x:x[0])
    if not ordered or any(not np.isfinite([x,w]).all() or w<=0 for x,w in ordered):
        raise ValueError('invalid rule')
    a=Fraction.from_float(float(scale))
    weights_exact=[Fraction.from_float(float(w)) for x,w in ordered]
    total=sum(weights_exact)
    zero,one=Fraction(0),Fraction(1)
    point=zero;distance=zero
    for (x,w),wi in zip(ordered,weights_exact):
        atom=Fraction.from_float(float(x*scale))
        lo=point;hi=point+wi/total
        if abs(atom)>a:
            raise ValueError('support mismatch')
        crossing=(atom+a)/(2*a)
        def antiderivative(t):return a*t*t-(atom+a)*t
        if crossing<=lo:
            increment=antiderivative(hi)-antiderivative(lo)
        elif crossing>=hi:
            increment=antiderivative(lo)-antiderivative(hi)
        else:
            increment=antiderivative(lo)+antiderivative(hi)-2*antiderivative(crossing)
        if increment<zero:
            raise AssertionError('negative W1')
        distance+=increment
        point=hi
    assert point==one
    return distance


def transport_certificate(majorants: dict, rule_name: str) -> dict:
    x,w=one_dimensional_rule(rule_name)
    exact_distances=[wasserstein_uniform_1d(x,w,float(a)) for a in SCALE]
    radius=sum(Fraction.from_float(float(L))*d for L,d in zip(majorants['first'],exact_distances))
    f=float(radius)
    while Fraction.from_float(f)<radius:
        f=math.nextafter(f,math.inf)
    return dict(rule=rule_name, radius_upper=f,
                w1=[float(q) for q in exact_distances],
                radius_numerator_digits=len(str(radius.numerator)),
                ideal_real_quadrature_only=True,
                model_evaluation_roundoff_certified=False)


def certified_midpoint_radius(majorants: dict, n: int) -> float:
    """Real-arithmetic tensor midpoint bound; no actual expensive grid needed."""
    if n<1:
        raise ValueError('positive grid density required')
    m=majorants['second']; r=sum(Fraction.from_float(float(M))*
                                          Fraction.from_float(float(a))**2
                                          for M,a in zip(m,SCALE))/(6*n*n)
    out=float(r)
    while Fraction.from_float(out)<r:
        out=math.nextafter(out,math.inf)
    return out


def manufactured_polynomial(name: str, s: np.ndarray):
    z=np.asarray(s,dtype=np.float64)/SCALE
    if name=='constant':
        return np.full(len(s),.0484)
    if name=='affine':
        return .0484+0.002*z[:,0]+0.001*z[:,2]
    if name=='quadratic':
        return .0484+0.001*(z[:,0]**2-1/3)
    if name=='degree8':
        return .0484+0.001*(z[:,2]**8-1/9)
    raise ValueError('unknown manufactured function')


def quadratic_example_certificate(n: int):
    """Independently known M_0=2, all others 0 for z_0² on [-1,1]^4."""
    if n<1:
        raise ValueError('n')
    # For mean of x^2 on [-1,1], midpoint value differs by 1/(3n^2),
    # exactly equal to tensor midpoint second-derivative bound M/(6n²).
    return dict(n=n, exact_expectation='1/3', midpoint_bias_exact=str(Fraction(1,3*n*n)),
                midpoint_bound_exact=str(Fraction(1,3*n*n)))
