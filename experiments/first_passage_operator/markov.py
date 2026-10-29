"""Positive active/refractory bin basis for finite-horizon Bellman learning.

Transitions integrate the continuous regenerative law into bins. They are exact
bin probabilities up to floating arithmetic and the existing killed CDF routine;
representing a subsequent value as constant within each bin is a separate
projection approximation, not an exact continuous-state Bellman solution.
"""

import numpy as np

from experiments.first_passage_cell.kernels import first_passage, killed_cdf
from .operators import operator_features

ACTIVE_EDGES = np.array([0.0, 0.04, 0.08, 0.14, 0.22, 0.32, 0.44, 0.60,
                         0.80, 1.05, 1.35, 1.75, 2.25, 3.0, 4.0, np.inf])
REFRACTORY_EDGES = np.linspace(0.0, 1.0, 6)
ACTIVE_BINS = len(ACTIVE_EDGES) - 1
BIN_COUNT = ACTIVE_BINS + len(REFRACTORY_EDGES) - 1


def _partitions(active_edges, refractory_edges):
    ae, re = np.asarray(active_edges, float), np.asarray(refractory_edges, float)
    if (ae.ndim != 1 or re.ndim != 1 or len(ae) < 2 or len(re) < 2
            or not np.isfinite(ae[:-1]).all() or not np.isfinite(re).all()
            or ae[0] != 0 or not np.isposinf(ae[-1]) or not np.all(np.diff(ae) > 0)
            or re[0] != 0 or re[-1] != 1 or not np.all(np.diff(re) > 0)):
        raise ValueError("finite increasing bins must cover active [0,infinity) and refractory [0,1]")
    return ae, re


def state_bin(distance, pending, refractory, active_edges=ACTIVE_EDGES,
              refractory_edges=REFRACTORY_EDGES):
    ae, re = _partitions(active_edges, refractory_edges)
    if (not np.isfinite([distance, pending, refractory]).all() or distance < 0
            or refractory <= 0 or not 0 <= pending <= refractory):
        raise ValueError("invalid active distance or refractory clock")
    if pending > 0:
        index = np.searchsorted(re, pending/refractory, side="right")-1
        return len(ae)-1+min(index, len(re)-2)
    return min(np.searchsorted(ae, distance, side="right")-1, len(ae)-2)


def representative_states(spec):
    active = (ACTIVE_EDGES[:-2] + ACTIVE_EDGES[1:-1]) / 2
    active = np.r_[active, ACTIVE_EDGES[-2]]
    ref = (REFRACTORY_EDGES[:-1] + REFRACTORY_EDGES[1:]) * spec.refractory / 2
    return np.r_[active, np.full(len(ref), spec.reset)], np.r_[np.zeros(len(active)), ref]


def transition_bins(spec, distance, horizon, pending=0.0, *, active_edges=ACTIVE_EDGES,
                    refractory_edges=REFRACTORY_EDGES):
    x, t, eta = float(distance), float(horizon), float(pending)
    ae, re = _partitions(active_edges, refractory_edges)
    if x < 0 or t < 0 or not 0 <= eta <= spec.refractory or not np.isfinite([x, t, eta]).all():
        raise ValueError("invalid augmented state")
    if eta > 0 and not np.isclose(x, spec.reset, rtol=0, atol=1e-12):
        raise ValueError("refractory state must be held at reset")
    # An already absorbed start emits before a zero-horizon observation.
    if x == 0:
        return transition_bins(spec, spec.reset, t, spec.refractory,
                               active_edges=ae, refractory_edges=re)
    if eta > t or t == 0:
        result = np.zeros(len(ae) + len(re) - 2)
        result[state_bin(x, max(eta-t, 0), spec.refractory, ae, re)] = 1.0
        return result
    if eta > 0:
        return transition_bins(spec, spec.reset, t - eta, 0.0,
                               active_edges=ae, refractory_edges=re)
    count = int(np.ceil(t / spec.refractory))
    if count > 512:
        raise ValueError("bounded regenerative expansion exceeded")
    indices = np.arange(count)
    distances = x + indices * spec.reset
    times = t - (indices + 1) * spec.refractory
    fractions = re * spec.refractory
    cumulative_ref = np.sum(first_passage(distances[:, None], spec.mu, spec.sigma,
                                          np.maximum(0, times[:, None] + fractions[None, :]))["F"], axis=0)
    ref = np.diff(cumulative_ref)
    active_mass = 1 - np.sum(ref)
    y = ae[1:-1]
    cumulative_active = np.asarray(killed_cdf(x, y, spec.mu, spec.sigma, t))
    keep = times > 0
    if np.any(keep):
        d = distances[keep, None]
        h = times[keep, None]
        first = killed_cdf(d + spec.reset, y[None, :], spec.mu, spec.sigma, h)
        second = killed_cdf(d, np.maximum(0, y[None, :] - spec.reset), spec.mu, spec.sigma, h)
        cumulative_active += np.sum(first - second, axis=0)
    active = np.diff(np.r_[0.0, cumulative_active, active_mass])
    result = np.r_[active, ref]
    negative_mass = -float(np.sum(result[result < 0]))
    if not np.isfinite(result).all() or negative_mass > 2e-10 or abs(result.sum()-1) > 2e-10:
        raise ArithmeticError(f"bin mass/positivity defect: {result.min()}, {result.sum()}")
    # Repair only bounded floating subtraction error. Its total removed mass,
    # rather than each bin alone, is capped at 2e-10. No row normalization occurs.
    repaired = np.maximum(result, 0.0)
    if abs(repaired.sum()-1) > 4e-10:
        raise ArithmeticError("roundoff repair exceeded the explicit row-mass budget")
    return repaired


def transition_and_reward(spec, distance, horizon, pending=0.0):
    probabilities = transition_bins(spec, distance, horizon, pending)
    moments = operator_features(spec, distance, horizon, pending_refractory=pending,
                                active_decays=(0.0,), refractory_decays=(0.0,))
    return probabilities, moments["discounted_events"], moments["discounted_active_time"]
