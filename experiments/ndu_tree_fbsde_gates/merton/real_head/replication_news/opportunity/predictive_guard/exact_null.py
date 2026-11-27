"""Independent joint-law enumeration: no import from guard or the policy solver."""
from fractions import Fraction as F
from functools import lru_cache
from itertools import product
from math import factorial


@lru_cache(None)
def joint(curves, history):
    # Integrate the latent curve only once; observations are not marginally IID.
    weights = []
    for curve in curves:
        weight = F(1, len(curves))
        for j, k in enumerate(history):
            n = (8, 8, 16)[j]
            p = F(curve[j+1]+1, 18)
            coefficient = factorial(n)//(factorial(k)*factorial(n-k))
            weight *= coefficient * p**k * (1-p)**(n-k)
        weights.append(weight)
    return sum(weights, F(0))


def trace(curves, history):
    curves = tuple(tuple(c) for c in curves)
    q, maximum, result = F(1), F(1), []
    for j, k in enumerate(history):
        n = (8, 8, 16)[j]
        if type(k) is not int or not 0 <= k <= n:
            raise ValueError('invalid exact count')
        h = tuple(history[:j+1]); parent = h[:-1]
        null = joint(curves, h)/joint(curves, parent)
        q /= n+1
        e = q/joint(curves, h); maximum = max(maximum, e)
        result.append({'null_probability': str(null), 'alternative_probability': str(F(1,n+1)),
                       'e_value': str(e), 'running_max': str(maximum),
                       'alarm': maximum >= 20})
    return result


@lru_cache(None)
def certificate(curves):
    """Exhaust all possible histories of the registered three-observation schedule.

    Bound is for this declared null distribution only. Stopping earlier cannot
    increase the event of crossing a threshold on the same underlying path.
    """
    curves = tuple(tuple(c) for c in curves)
    total = F(0); crossed = F(0); leaves = 0; conditional_checks = 0
    for history in product(range(9), range(9), range(17)):
        probability = joint(curves, history)
        total += probability; leaves += 1
        if any(r['alarm'] for r in trace(curves, history)):
            crossed += probability
    for length in range(3):
        for h in product(*(range(n+1) for n in (8,8)[:length])):
            e = F(1) if not h else F(trace(curves,h)[-1]['e_value'])
            average = F(0)
            for k in range((8,8,16)[length]+1):
                child = h+(k,)
                probability = joint(curves,child)/joint(curves,h)
                average += probability*F(trace(curves,child)[-1]['e_value'])
            if average != e:
                raise ValueError('conditional martingale identity failed')
            conditional_checks += 1
    if total != 1 or crossed > F(1,20):
        raise ValueError('exact null normalization or maximal bound failed')
    return {'terminal_paths': leaves, 'conditional_identities': conditional_checks,
            'total_probability': str(total), 'probability_ever_alarm': str(crossed),
            'probability_ever_alarm_decimal': float(crossed), 'per_stream_level': '1/20',
            'scope': 'registered_finite_joint_law_only', 'validates_real_observation_model': False,
            'fleet_wide_bound': False, 'nonrejection_proves_accuracy': False}
