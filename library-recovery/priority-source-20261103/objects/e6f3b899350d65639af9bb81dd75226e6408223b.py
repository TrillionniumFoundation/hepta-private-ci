"""P2 deterministic-refractory renewal reference, separate from HX QVI.

An ACTIVE neuron fires after Exp(lam), then spends exactly tau units in
REFRACTORY and only then samples another Exp(lam) wait.  Under a constant
lambda, its n-th event time is Gamma(n, rate=lambda)+(n-1)*tau, hence

    Pr[N_T >= n] = gammainc(n, lam*(T-(n-1)*tau))  if T>(n-1)*tau.

E[N_T] is the sum over n>=1; P(N_T>=1) is NOT E[N_T].  The finite positive
refractory imposes a finite number of nonzero terms on bounded windows.
Tau=0 is handled as the exact Poisson limit.  This is a mathematical reference
for repeated events; it is NOT a proof of real HX barrier dynamics, nor a
classifier, nor a training result.

Also provides a deterministic counter-hash exponential-hazard stream for
piecewise-constant-rate pathwise checkpoint/replay.  Hashing is used only for
reproducible pseudorandomness, not authority or anti-tampering.  The interval
transitions have ordinary f64 roundoff and should not claim bitwise semigroup
agreement at a crossing closer than numerical precision to an interval edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math

from scipy.special import gammainc


class RenewalDomainError(ValueError):
    pass


@dataclass(frozen=True)
class RenewalStats:
    first_fire_probability: float
    expected_event_count: float
    two_or_more_probability: float
    three_or_more_probability: float
    nonzero_tail_terms: int


def constant_rate_stats(lam: float, refractory: float, horizon: float,
                        *, max_terms: int = 4096) -> RenewalStats:
    for name, value in (('lam',lam),('refractory',refractory),('horizon',horizon)):
        if type(value) not in (int,float) or not math.isfinite(value):
            raise RenewalDomainError(f'{name} must be finite number')
    if not (lam>0 and refractory>=0 and horizon>=0) or type(max_terms) is not int or max_terms<3:
        raise RenewalDomainError('require lam>0, tau,T>=0, max_terms>=3')
    if horizon==0:
        return RenewalStats(0.,0.,0.,0.,0)
    exposure=lam*horizon
    if not math.isfinite(exposure):
        raise RenewalDomainError('lam*T overflow')
    first=-math.expm1(-exposure)
    if refractory==0:
        stats=RenewalStats(first,exposure,float(gammainc(2,exposure)),
                           float(gammainc(3,exposure)), -1)
    else:
        count_ratio=horizon/refractory
        if not math.isfinite(count_ratio) or count_ratio>max_terms:
            raise RenewalDomainError('too many possible refractory cycles: explicit refusal')
        largest=math.ceil(count_ratio)
        terms=[]
        for n in range(1,largest+1):
            remaining=horizon-(n-1)*refractory
            if remaining<=0:
                break
            if n==1:
                prob=first
            else:
                prob=float(gammainc(n,lam*remaining))
            if not math.isfinite(prob) or not 0<=prob<=1:
                raise ArithmeticError('gamma-renewal tail unresolved')
            if terms and prob>terms[-1]+8*max(math.ulp(prob),math.ulp(terms[-1])):
                raise ArithmeticError('P(N>=n) monotonic ordering unresolved')
            terms.append(prob)
        stats=RenewalStats(first,math.fsum(terms),
                           terms[1] if len(terms)>1 else 0.,
                           terms[2] if len(terms)>2 else 0.,len(terms))
    if (not all(math.isfinite(v) for v in (stats.first_fire_probability,
           stats.expected_event_count, stats.two_or_more_probability,
           stats.three_or_more_probability)) or
           not 0<=stats.three_or_more_probability<=stats.two_or_more_probability
           <=stats.first_fire_probability<=1 or
           stats.expected_event_count+2e-14<stats.first_fire_probability):
        raise ArithmeticError('renewal statistics physical envelope violated')
    return stats


def _next_exponential_budget(seed: int, counter: int) -> float:
    if (type(seed) is not int or type(counter) is not int or
            not 0<=seed<2**64 or not 0<=counter<2**64):
        raise RenewalDomainError('seed/counter must be unsigned 64-bit integers')
    data=seed.to_bytes(8,'big')+counter.to_bytes(8,'big')
    digest=sha256(data).digest()
    # 53-bit midpoint avoids log(0), log(1), and unstable division.
    raw=int.from_bytes(digest[:8],'big')>>11
    u=(raw+.5)/2**53
    result=-math.log1p(-u)
    if result<=0 or not math.isfinite(result):
        raise ArithmeticError('non-positive exponential hazard budget')
    return result


@dataclass(frozen=True)
class PathState:
    physical_time: float
    refractory: float
    refractory_remaining: float
    active_hazard_remaining: float
    fired_count: int
    rng_counter: int
    rng_seed: int
    version: int = 1

    @classmethod
    def initial(cls, seed: int, refractory: float) -> 'PathState':
        if type(refractory) not in (int,float) or not math.isfinite(refractory) or refractory<0:
            raise RenewalDomainError('deterministic refractory must be finite nonnegative')
        return cls(0.,float(refractory),0.,_next_exponential_budget(seed,0),0,1,seed)


def advance_path(state: PathState, lam: float, dt: float,
                 *, max_events: int=10_000) -> PathState:
    """Causal path update for a given piecewise-constant rate and time interval.

    Checkpoint ALL fields.  Exact same prefix and seed gives exact same state;
    replay from JSON is deterministic.  This is NOT a cryptographic provenance
    gate: a forged checkpoint may pass the structural checks.
    """
    if not isinstance(state,PathState) or type(state.version) is not int or state.version!=1:
        raise RenewalDomainError('supported complete PathState checkpoint required')
    if type(lam) not in (int,float) or type(dt) not in (int,float) or not all(
            math.isfinite(v) for v in (lam,dt)) or lam<=0 or dt<0:
        raise RenewalDomainError('finite lam>0 and dt>=0 required')
    if type(max_events) is not int or max_events<1:
        raise RenewalDomainError('invalid max_events')
    if (not all(math.isfinite(v) for v in
            (state.physical_time,state.refractory,state.refractory_remaining,
             state.active_hazard_remaining)) or
            state.physical_time<0 or state.refractory<0 or
            not 0<=state.refractory_remaining<=state.refractory or
            state.active_hazard_remaining<=0 or type(state.fired_count) is not int or
            state.fired_count<0 or type(state.rng_counter) is not int or
            state.rng_counter<=0 or state.fired_count+1!=state.rng_counter or
            type(state.rng_seed) is not int or not 0<=state.rng_seed<2**64):
        raise RenewalDomainError('invalid state fields/counters')
    if state.physical_time==0:
        if (state.fired_count!=0 or state.refractory_remaining!=0 or
                state.active_hazard_remaining != _next_exponential_budget(state.rng_seed,0)):
            raise RenewalDomainError('impossible time-zero FIRE/refractory/RNG checkpoint')
    if dt==0:
        return state
    new_time=math.fsum((state.physical_time,dt))
    if not math.isfinite(new_time) or new_time<=state.physical_time:
        raise ArithmeticError('physical clock step unresolved in float64')
    todo=float(dt)
    refractory_remaining=state.refractory_remaining
    hazard=state.active_hazard_remaining
    count=state.fired_count
    counter=state.rng_counter
    fired_this_step=0
    while todo>0:
        if refractory_remaining>0:
            if todo<=refractory_remaining:
                refractory_remaining-=todo
                todo=0.
                break
            todo-=refractory_remaining
            refractory_remaining=0.
            if todo<=0:
                break
        integrated=lam*todo
        if not math.isfinite(integrated):
            raise ArithmeticError('integrated intensity overflow')
        if integrated<hazard:
            hazard-=integrated
            if hazard<=0:
                raise ArithmeticError('remaining integrated hazard erased in f64')
            todo=0.
            break
        if fired_this_step>=max_events:
            raise ArithmeticError('too many events; explicit bounded reference refusal')
        time_to_fire=hazard/lam
        if time_to_fire<0 or not math.isfinite(time_to_fire) or time_to_fire>todo:
            raise ArithmeticError('first fire time unresolved')
        if time_to_fire==0 and todo>0:
            raise ArithmeticError('event interval rounds to zero in f64')
        left=todo-time_to_fire
        if left==todo and todo>0:
            raise ArithmeticError('event time subtraction erased in f64')
        todo=left
        count+=1
        fired_this_step+=1
        if counter>=2**64:
            raise ArithmeticError('counter overflow')
        hazard=_next_exponential_budget(state.rng_seed,counter)
        counter+=1
        refractory_remaining=state.refractory
    result=PathState(new_time,state.refractory,refractory_remaining,hazard,
                     count,counter,state.rng_seed)
    if not all(math.isfinite(v) for v in (result.active_hazard_remaining,
            result.refractory_remaining)):
        raise ArithmeticError('nonfinite post-transition state')
    return result
