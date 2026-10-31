"""Independent *two-state* CTMC renewal event oracle; research only.

Active --(fire, rate lam)--> refractory --(recover, rate gamma)--> active.
F(T)=P(N_T>=1) is not E[N_T], and repeated fires require regeneration.
This constant-rate memoryless reference does NOT implement HX, Erlang
refractory, physical SNN threshold crossings or production probability flow.
"""

from dataclasses import dataclass
import math


def _parameters(lam: float, gamma: float, dt: float):
    if not (all(math.isfinite(x) for x in (lam, gamma, dt))
            and lam > 0 and gamma > 0 and dt >= 0):
        raise ValueError('Finite positive rates and nonnegative time required')


def _exp_difference_quotient(lam: float, gamma: float, dt: float):
    """(exp(-gamma*dt)-exp(-lam*dt))/(lam-gamma), including equality."""
    d = (lam-gamma)*dt
    if abs(d) <= .01:
        # Finite positive-term Taylor series, no subtractive cancellation.
        term = 1.0
        total = 1.0
        for n in range(1, 16):
            term *= d/(n+1)
            total += term
        return dt * math.exp(-lam*dt) * total
    return math.fsum((math.exp(-gamma*dt),-math.exp(-lam*dt)))/(lam-gamma)


def _first_fire_from_refractory(lam: float, gamma: float, dt: float):
    A,B = lam*dt, gamma*dt
    if max(A, B) <= .05:
        # CDF of the sum of independent Exp(gamma) and Exp(lam) waiting
        # times. In positive A,B, this alternating expansion resolves tiny
        # O(dt^2) probabilities without the subtractive 1-survival operation.
        terms = []
        for n in range(16):
            homogeneous = math.fsum(A**(n-i)*B**i for i in range(n+1))
            terms.append(((-1)**n)*homogeneous/math.factorial(n+2))
        result = A*B*math.fsum(terms)
    else:
        kernel = _exp_difference_quotient(lam, gamma, dt)
        result = math.fsum((1.,-math.exp(-gamma*dt),-gamma*kernel))
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ArithmeticError('Unresolved refractory first-fire probability')
    return result


@dataclass(frozen=True)
class RenewalState:
    time: float
    active: float
    no_fire_active: float
    no_fire_refractory: float
    ever_fired: float
    expected_count: float
    version: int = 1

    @classmethod
    def initial(cls, active: float):
        if not math.isfinite(active) or not 0 <= active <= 1:
            raise ValueError('Initial active probability must be in [0,1]')
        return cls(0.,active,active,1.-active,0.,0.)


def advance(state: RenewalState, lam: float, gamma: float, dt: float) -> RenewalState:
    """Exact constant-rate segment, with both physical and killed states.

    The no-event survival state is unnormalized and persists across segments.
    Checkpoint all six numeric fields and version; neither reset refractory mass nor reconstruct
    a first-event probability from the last interval's event expectation.
    """
    _parameters(lam,gamma,dt)
    if not isinstance(state,RenewalState):
        raise TypeError('A full versioned renewal state is required')
    entries=(state.time,state.active,state.no_fire_active,
             state.no_fire_refractory,state.ever_fired,state.expected_count)
    if (type(state.version) is not int or state.version != 1 or
            not all(math.isfinite(x) for x in entries)
            or not 0<=state.active<=1
            or min(state.no_fire_active,state.no_fire_refractory,state.ever_fired,
                   state.expected_count,state.time)<0
            or state.ever_fired>1
            or abs(math.fsum((state.no_fire_active,state.no_fire_refractory,state.ever_fired))-1)>1e-11
            or state.expected_count+1e-11<state.ever_fired):
        raise ValueError('Inconsistent or nonfinite persisted renewal state')
    if dt == 0:
        return state
    s=lam+gamma
    if not math.isfinite(s):
        raise ArithmeticError('Renewal rates sum unresolved in f64')
    decay=math.exp(-s*dt)
    eq=gamma/s
    active=math.fsum((eq,(state.active-eq)*decay))
    occupation=math.fsum((eq*dt,(state.active-eq)*(-math.expm1(-s*dt))/s))
    count=math.fsum((state.expected_count,lam*occupation))
    kernel=_exp_difference_quotient(lam,gamma,dt)
    no_fire_active=math.fsum((state.no_fire_active*math.exp(-lam*dt),
                             state.no_fire_refractory*gamma*kernel))
    no_fire_refractory=state.no_fire_refractory*math.exp(-gamma*dt)
    event_increment=math.fsum((state.no_fire_active*(-math.expm1(-lam*dt)),
                                state.no_fire_refractory*_first_fire_from_refractory(lam,gamma,dt)))
    fired=math.fsum((state.ever_fired,event_increment))
    output=RenewalState(math.fsum((state.time,dt)),active,no_fire_active,
                        no_fire_refractory,fired,count,version=1)
    if (not all(math.isfinite(x) for x in vars(output).values()) or
            not 0<=active<=1 or not 0<=fired<=1 or
            min(no_fire_active,no_fire_refractory,count)<0 or
            abs(math.fsum((no_fire_active,no_fire_refractory,fired))-1)>1e-10 or
            count+1e-10<fired):
        raise ArithmeticError('Renewal state/probability conservation unresolved')
    return output
