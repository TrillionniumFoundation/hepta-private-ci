"""Continuous-time reference event runtime for RR-SNN research.

Exact within floating-point/special-function sampling error for the defined
piecewise-constant, independent Brownian processes and deterministic LIF.
No diffusion time step, single-spike-per-bin approximation, or unconditional
Gaussian propagation after survival is used. All units are dimensionless.

This reference implementation deliberately synchronizes all neurons at every
event. Its O(N * events) work is a correctness reference, not a scalable or
production Hepta implementation. No resource controller is implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
import math
from typing import Optional

import numpy as np
from scipy.optimize import brentq
from scipy.special import log_ndtr, ndtri_exp


def first_hit_cdf(x: float, t: float, mu: float, sigma: float) -> float:
    if x <= 0:
        return 1.0
    if t <= 0:
        return 0.0
    if sigma == 0:
        return float(mu < 0 and -x / mu <= t)
    if sigma < 0:
        raise ValueError("sigma must be nonnegative")
    scale = sigma * math.sqrt(t)
    a = log_ndtr((-x - mu*t) / scale)
    b = -2*mu*x / (sigma*sigma) + log_ndtr((-x + mu*t) / scale)
    return float(math.exp(min(float(np.logaddexp(a, b)), 0.0)))


def log_surviving_tail(z: float, x: float, dt: float, mu: float, sigma: float) -> float:
    """log P(X_dt > z, tau>dt), z>=0, x,dt,sigma>0."""
    if min(x, dt, sigma) <= 0 or z < 0:
        raise ValueError("Require x,dt,sigma>0 and z>=0")
    scale = sigma * math.sqrt(dt)
    a = float(log_ndtr((x + mu*dt - z) / scale))
    b = -2*mu*x/(sigma*sigma) + float(log_ndtr((-x + mu*dt-z)/scale))
    difference = b-a
    # The difference is strictly negative mathematically. A nonnegative value
    # means this double-precision tail calculation cannot resolve the mass.
    if difference >= 0:
        raise FloatingPointError("Survival tail cancellation; parameters exceed resolved precision")
    return a + math.log(-math.expm1(difference))


def killed_density(z, x: float, dt: float, mu: float, sigma: float):
    z = np.asarray(z)
    gaussian = np.exp(-(z-x-mu*dt)**2/(2*sigma*sigma*dt)) / (sigma*np.sqrt(2*np.pi*dt))
    return np.where(z >= 0, gaussian * (-np.expm1(-2*x*z/(sigma*sigma*dt))), 0.0)


def conditional_survival_cdf(z, x: float, dt: float, mu: float, sigma: float):
    """Numerically stable CDF of K/S at nonnegative endpoints."""
    log_s = log_surviving_tail(0.0, x, dt, mu, sigma)
    array = np.asarray(z, dtype=float)
    out = np.empty_like(array)
    for i, zz in enumerate(array.flat):
        if zz <= 0:
            out.flat[i] = 0.0
        else:
            log_t = log_surviving_tail(float(zz), x, dt, mu, sigma)
            out.flat[i] = -math.expm1(min(log_t-log_s, 0.0))
    return out


def sample_first_hit(rng: np.random.Generator, x: float, mu: float, sigma: float) -> float:
    """Sample the full, possibly defective first-passage law to zero.

    For mu>0 the probability of ever hitting is exp(-2*mu*x/sigma^2).
    Conditional on hitting, the law equals that for drift -mu.
    """
    if x <= 0:
        return 0.0
    if sigma < 0:
        raise ValueError("sigma must be nonnegative")
    if sigma == 0:
        return -x/mu if mu < 0 else math.inf
    if mu > 0 and math.log(max(float(rng.random()), np.finfo(float).tiny)) >= -2*mu*x/(sigma*sigma):
        return math.inf
    if mu == 0:
        normal = float(rng.normal())
        return (x/(sigma*normal))**2 if normal else math.inf
    return float(rng.wald(x/abs(mu), x*x/(sigma*sigma)))


def sample_surviving_endpoint(rng: np.random.Generator, x: float, dt: float,
                              mu: float, sigma: float, stats: Optional[dict] = None) -> float:
    """Draw X_dt conditional on not previously hitting zero.

    Positive-truncated Gaussian proposals are accepted by the Brownian-bridge
    survival factor 1-exp(-2*x*z/(sigma^2*dt)). This samples K/S exactly.
    Rare-event cases fall back to numerical inversion of the exact tail.
    """
    if dt < 0 or x <= 0 or sigma < 0:
        raise ValueError("Invalid propagation domain")
    if dt == 0:
        return x
    if sigma == 0:
        endpoint = x+mu*dt
        if endpoint <= 0:
            raise ValueError("Conditioned deterministic propagation has zero survival probability")
        return endpoint
    mean = x+mu*dt
    scale = sigma*math.sqrt(dt)
    log_positive_mass = float(log_ndtr(mean/scale))
    for _ in range(256):
        if stats is not None:
            stats['survival_proposals'] += 1
        # Sample a Gaussian conditioned above zero using its upper tail, so
        # the construction remains useful when the untruncated mean is low.
        u = float(rng.random())
        normal = -float(ndtri_exp(log_positive_mass+math.log1p(-u)))
        endpoint = mean+scale*normal
        if endpoint <= 0:
            continue
        acceptance = -math.expm1(-2*x*endpoint/(sigma*sigma*dt))
        if rng.random() <= acceptance:
            return endpoint
    if stats is not None:
        stats['survival_inversions'] += 1
    log_mass = log_surviving_tail(0.0, x, dt, mu, sigma)
    log_target = log_mass+math.log1p(-float(rng.random()))
    hi = max(x, abs(mean), scale, 1e-12)
    while log_surviving_tail(hi, x, dt, mu, sigma) > log_target:
        hi *= 2
        if not math.isfinite(hi):
            raise FloatingPointError("Cannot bracket survival inverse")
    return float(brentq(lambda z: log_surviving_tail(z,x,dt,mu,sigma)-log_target,
                        0.0, hi, xtol=1e-12, rtol=8*np.finfo(float).eps))


@dataclass(frozen=True)
class Neuron:
    """Evidence dynamics or LIF parameters.

    brownian: dY=drift dt+sigma dW. lif: dY=(rest+drift-Y)/tau dt;
    drift in the latter is the equilibrium offset, not an additive derivative.
    Incoming kicks during refractory periods are discarded by definition.
    Drift/threshold/sigma changes are retained during refractory periods.
    """
    drift: float = 0.7
    sigma: float = 0.4
    threshold: float = 1.0
    reset: float = 0.0
    refractory: float = 0.1
    initial: float = 0.0
    model: str = 'brownian'
    tau: float = 0.3
    rest: float = 0.0

    def check(self):
        numeric = [self.drift,self.sigma,self.threshold,self.reset,self.refractory,
                   self.initial,self.tau,self.rest]
        if not all(math.isfinite(v) for v in numeric):
            raise ValueError("All neuron parameters must be finite")
        if self.model not in ('brownian','lif') or self.sigma < 0:
            raise ValueError("Unknown model or negative sigma")
        if self.model == 'lif' and self.sigma != 0:
            raise ValueError("Exact LIF reference is deterministic; sigma must be zero")
        if self.threshold <= self.reset or self.initial >= self.threshold:
            raise ValueError("Require reset and initial below threshold")
        if self.refractory <= 0 or self.tau <= 0:
            raise ValueError("Require strictly positive refractory and tau")


@dataclass(frozen=True)
class InputEvent:
    time: float
    target: int
    kick: float = 0.0
    drift: Optional[float] = None
    threshold: Optional[float] = None
    sigma: Optional[float] = None
    tag: str = 'external'


@dataclass(frozen=True)
class Connection:
    source: int
    target: int
    weight: float
    delay: float


def lif_hit_time(value: float, equilibrium: float, threshold: float, tau: float) -> float:
    if value >= threshold:
        return 0.0
    if equilibrium <= threshold:
        return math.inf
    return tau*math.log((equilibrium-value)/(equilibrium-threshold))


def simulate(neurons: list[Neuron], horizon: float, inputs: list[InputEvent] = (),
             connections: list[Connection] = (), seed: int = 101,
             record_trace: bool = True, max_events: int = 100_000) -> dict:
    """Simulate a coupled event network with explicit first-passage spikes.

    At each global event we discard unobserved tentative first-hit draws.
    Given the winning time, other neurons have only been observed to survive;
    their states therefore use K/S. Fresh independent future draws are then
    valid by the Markov property. Brownian innovations must be independent
    across neurons; coupling occurs through delayed kicks only.

    Ties: intrinsic crossing, then refractory release, then input events in
    insertion order. Inputs after horizon have no effect. A final endpoint is
    always returned, conditional on the actually observed spike history.
    """
    if not neurons or not math.isfinite(horizon) or horizon <= 0:
        raise ValueError("A nonempty network and positive finite horizon are required")
    for spec in neurons:
        spec.check()
    specs = list(neurons)
    n = len(specs)
    value = np.array([p.initial for p in specs], dtype=float)
    refractory_until = np.zeros(n)
    outbound = [[] for _ in range(n)]
    for edge in connections:
        if not (0 <= edge.source < n and 0 <= edge.target < n):
            raise ValueError("Connection index out of bounds")
        if not math.isfinite(edge.weight) or not math.isfinite(edge.delay) or edge.delay <= 0:
            raise ValueError("Finite weights and strictly positive delays are required")
        outbound[edge.source].append(edge)
    rng = np.random.default_rng(seed)
    heap = []
    sequence = 0
    trace, spikes = [], []
    stats = {'global_events':0,'survival_proposals':0,'survival_inversions':0,
             'survival_updates':0,'dropped_refractory_inputs':0,'parameter_updates':0,
             'transmitted_inputs':0,'first_hit_draws':0}
    time = 0.0

    def record(kind, neuron, **extra):
        if record_trace:
            trace.append({'time':time,'kind':kind,'neuron':int(neuron),**extra})

    def push(event, wake=False):
        nonlocal sequence
        if not math.isfinite(event.time) or event.time < 0 or not (0 <= event.target < n):
            raise ValueError("Invalid input event")
        for name in ('kick','drift','threshold','sigma'):
            item = getattr(event,name)
            if item is not None and not math.isfinite(item):
                raise ValueError("Event parameters must be finite")
        if event.time <= horizon:
            heapq.heappush(heap,(event.time,0 if wake else 1,sequence,event))
            sequence += 1

    for event in inputs:
        push(event)

    def fire(i, reason):
        if refractory_until[i] > time:
            raise AssertionError("A refractory neuron cannot emit")
        spikes.append({'time':time,'neuron':int(i),'reason':reason,
                       'value_before':float(value[i])})
        record('spike',i,reason=reason,value=float(value[i]))
        value[i] = specs[i].reset
        refractory_until[i] = time+specs[i].refractory
        push(InputEvent(refractory_until[i],i,tag='wake'),wake=True)
        for edge in outbound[i]:
            push(InputEvent(time+edge.delay,edge.target,kick=edge.weight,tag='synaptic'))
            stats['transmitted_inputs'] += 1

    def process_due():
        while heap and heap[0][0] <= time:
            _,priority,_,event = heapq.heappop(heap)
            i = event.target
            if priority == 0:
                record('wake',i)
                continue
            changes = {key:getattr(event,key) for key in ('drift','threshold','sigma')
                       if getattr(event,key) is not None}
            if changes:
                proposed = replace(specs[i],**changes)
                # A lower threshold may cross current evidence, but reset must
                # remain strictly inside the new continuation region.
                replace(proposed,initial=proposed.reset).check()
                specs[i] = proposed
                stats['parameter_updates'] += 1
            if refractory_until[i] > time:
                if event.kick:
                    stats['dropped_refractory_inputs'] += 1
                    record('input_dropped',i,tag=event.tag,kick=event.kick)
                continue
            value[i] += event.kick
            record('input',i,tag=event.tag,kick=event.kick,parameters=changes)
            if value[i] >= specs[i].threshold:
                fire(i,'input_or_parameter')

    process_due()
    while time < horizon:
        stats['global_events'] += 1
        if stats['global_events'] > max_events:
            raise RuntimeError("Event limit exceeded; no partial result is accepted")
        next_hits = np.full(n,math.inf)
        for i,p in enumerate(specs):
            if refractory_until[i] > time:
                continue
            if p.model == 'brownian':
                next_hits[i] = sample_first_hit(rng,p.threshold-value[i],-p.drift,p.sigma)
                stats['first_hit_draws'] += 1
            else:
                next_hits[i] = lif_hit_time(value[i],p.rest+p.drift,p.threshold,p.tau)
        winner = int(np.argmin(next_hits))
        hit_time = time+next_hits[winner]
        scheduled = heap[0][0] if heap else math.inf
        next_time = min(hit_time,scheduled,horizon)
        dt = next_time-time
        is_hit = hit_time == next_time
        for i,p in enumerate(specs):
            if refractory_until[i] > time:
                continue
            if is_hit and next_hits[i] == next_hits[winner]:
                value[i] = p.threshold
            elif dt > 0:
                if p.model == 'brownian':
                    xnew = sample_surviving_endpoint(rng,p.threshold-value[i],dt,-p.drift,p.sigma,stats)
                    value[i] = p.threshold-xnew
                    stats['survival_updates'] += 1
                else:
                    equilibrium = p.rest+p.drift
                    value[i] = equilibrium+(value[i]-equilibrium)*math.exp(-dt/p.tau)
        time = next_time
        if is_hit:
            # Deterministic neurons can cross simultaneously; all crossing
            # states fire before same-time external input by the tie rule.
            for i in np.flatnonzero(next_hits == next_hits[winner]):
                fire(int(i),'first_passage' if specs[i].model=='brownian' else 'lif_crossing')
        process_due()
        if not np.all(np.isfinite(value)):
            raise FloatingPointError("Nonfinite state encountered")
    return {'horizon':horizon,'spikes':spikes,'final_values':value.tolist(),
            'refractory_until':refractory_until.tolist(),'stats':stats,'trace':trace,
            'semantics':{'noise':'independent piecewise-constant Brownian',
                         'refractory_input':'discard kicks; retain parameter changes',
                         'ties':'intrinsic crossing; wake; ordered input events',
                         'complexity':'O(neurons * global events) reference engine'}}
