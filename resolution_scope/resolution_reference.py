"""Direct positive-delay renewal reference for one numerical design probe.

Uses the independently derived release-convolution identity, then verifies
it against the original adaptive time-convolution reference before use.
No tensor matrix, repeated finite-volume projection or task data enters it.
"""

from dataclasses import asdict
from fractions import Fraction
import math

import numpy as np
from scipy.integrate import quad

from qualification.hcsn_regenerative import process as scalar
from qualification.hcsn_regenerative.fixed_renewal import (
    ConstructionDiagnostics, FixedDiffusion, killed_interval, released_interval,
)


MU, SIGMA, DISCOUNT, MARGIN, REFRACTORY, INITIAL, ENDPOINT = -.1, .3, .15, .25, .1, .35, 2.
ACTIVE_EDGES = tuple(float(v) for v in np.linspace(0., ENDPOINT, 17))
PHASE_EDGES = tuple(float(v) for v in np.linspace(0., REFRACTORY, 9))


def positive_difference(process, lower_distance, upper_distance, horizon):
    if horizon <= 0:
        return 0.
    left = process.log_first_hit(lower_distance, horizon)
    right = process.log_first_hit(upper_distance, horizon)
    if right > left:
        raise FloatingPointError("direct positive occupation difference is unresolved")
    return math.exp(left)*(-math.expm1(right-left))


def direct(horizon):
    process = FixedDiffusion(MU, SIGMA, DISCOUNT)
    time = Fraction(str(horizon))
    refractory = Fraction(str(REFRACTORY))
    terms = int(time//refractory)+1
    intervals = list(zip(ACTIVE_EDGES[:-1], ACTIVE_EDGES[1:]))+[(ENDPOINT, math.inf)]
    diagnostics = ConstructionDiagnostics()
    active = np.array([killed_interval(process, INITIAL, horizon, lo, hi, diagnostics=diagnostics)
                       for lo, hi in intervals])
    phase = np.zeros(len(PHASE_EDGES)-1)
    hits, discounted_hits, release_occupation = [], [], []
    occupation_errors = []
    # The u^2 transform resolves positive short-time contributions without cancellation.
    initial_integral, initial_error = quad(
        lambda u: 2*u*math.exp(-DISCOUNT*horizon*u*u)
        *(-math.expm1(process.log_first_hit(INITIAL, horizon*u*u))),
        0., 1., epsabs=2e-12, epsrel=2e-12, limit=300)
    occupation_errors.append(horizon*initial_error)
    for n in range(1, terms+1):
        distance = INITIAL+(n-1)*MARGIN
        hit_horizon = time-(n-1)*refractory
        if hit_horizon < 0:
            break
        hits.append(process.first_hit(distance, float(hit_horizon)))
        discounted_hits.append(math.exp(-DISCOUNT*float((n-1)*refractory))
                               *process.first_hit(distance, float(hit_horizon), discounted=True))
        remaining = time-n*refractory
        if remaining > 0:
            duration = float(remaining)
            active += np.array([released_interval(process, distance, MARGIN, duration, lo, hi,
                                                   diagnostics=diagnostics) for lo, hi in intervals])
            integral, error = quad(
                lambda u: 2*u*math.exp(-DISCOUNT*duration*u*u)
                *positive_difference(process, distance, distance+MARGIN, duration*u*u),
                0., 1., epsabs=2e-12, epsrel=2e-12, limit=300)
            weight = duration*math.exp(-DISCOUNT*float(n*refractory))
            release_occupation.append(weight*integral)
            occupation_errors.append(weight*error)
        for i, (lo, hi) in enumerate(zip(PHASE_EDGES[:-1], PHASE_EDGES[1:])):
            left = remaining+Fraction(str(lo))
            right = remaining+Fraction(str(hi))
            upper = process.first_hit(distance, float(right)) if right > 0 else 0.
            lower = process.first_hit(distance, float(left)) if left > 0 else 0.
            difference = upper-lower
            if difference < 0:
                raise FloatingPointError("direct refractory bin is negative")
            phase[i] += difference
    mass = np.r_[active, phase]
    residual = float(mass.sum()-1)
    if not np.isfinite(mass).all() or (mass < 0).any() or abs(residual) > 5e-10:
        raise FloatingPointError("direct renewal reference mass is unresolved")
    return dict(horizon=horizon, mass=mass.tolist(), expected_hits=math.fsum(hits),
                expected_discounted_hits=math.fsum(discounted_hits),
                discounted_active_time=horizon*initial_integral+math.fsum(release_occupation),
                mass_residual=residual, finite_renewal_terms=terms, omitted_renewal_mass=0.,
                diagnostics=asdict(diagnostics), occupation_quadrature_error=sum(occupation_errors))


def crosscheck():
    process = scalar.KilledDiffusion(MU, SIGMA, DISCOUNT)
    reset = scalar.ResetRule(MARGIN, REFRACTORY)
    results = []
    for horizon in (.08, .1, .32, .7):
        analytic = direct(horizon)
        state = scalar.regenerative_transition(process, reset, INITIAL, horizon, ACTIVE_EDGES,
                                               refractory_edges=PHASE_EDGES, tolerance=2e-11)
        value = scalar.finite_horizon_value(process, reset, INITIAL, horizon, tolerance=2e-11)
        expected = np.array([*state.active_bins, state.upper_tail, *state.refractory_bins])
        differences = dict(state_l1=float(np.abs(np.asarray(analytic["mass"])-expected).sum()),
                           expected_hits=abs(analytic["expected_hits"]-state.expected_hits),
                           expected_discounted_hits=abs(analytic["expected_discounted_hits"]-value.expected_discounted_hits),
                           discounted_active_time=abs(analytic["discounted_active_time"]-value.active_time))
        results.append(dict(horizon=horizon, differences=differences,
                            pass_=max(differences.values()) <= 2e-8,
                            adaptive_state_quadrature_error=state.quadrature_error,
                            adaptive_value_quadrature_error=value.quadrature_error))
    return results
