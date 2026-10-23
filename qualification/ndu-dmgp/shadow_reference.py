"""NDU-DMGP shadow-only research reference (stdlib, no model calls or authority).

All outcomes and counterfactual coalitions must come from an independent observer.
This module does not claim a stochastic FBSDE solve, causal identification, or
production readiness. A missing statistical support returns an explicit failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import factorial, isfinite, log, sqrt
from typing import Mapping, Sequence


class EvidenceError(ValueError):
    """Invalid or contaminated evidence, or a violated hard constraint."""


class InsufficientSupport(EvidenceError):
    """No qualified stochastic estimate or independent counterfactual support."""


@dataclass(frozen=True)
class Objective:
    digest: str
    observer_id: str
    max_action_cost: float
    max_sync_skew_ms: int = 80

    def __post_init__(self):
        if not self.digest or not self.observer_id or self.max_action_cost <= 0:
            raise EvidenceError("invalid frozen objective")
        if self.max_sync_skew_ms < 0:
            raise EvidenceError("invalid synchronization bound")


@dataclass(frozen=True)
class Outcome:
    episode: str
    action: str
    split: str
    objective_digest: str
    observer_id: str
    source: str
    utility: float
    actual_cost: float


def validated_outcomes(rows: Sequence[Outcome], objective: Objective,
                       actor_id: str, critic_id: str) -> tuple[Outcome, ...]:
    if not rows or objective.observer_id in (actor_id, critic_id):
        raise EvidenceError("outcome observer must be independent")
    seen: set[tuple[str, str, str]] = set()
    episode_splits: dict[str, str] = {}
    for row in rows:
        key = (row.episode, row.action, row.split)
        if not row.episode or not row.action or key in seen:
            raise EvidenceError("missing identity or duplicate outcome")
        seen.add(key)
        if row.split not in ("train", "future", "retention"):
            raise EvidenceError("unsupported split")
        if row.episode in episode_splits and episode_splits[row.episode] != row.split:
            raise EvidenceError("episode leaked across splits")
        episode_splits[row.episode] = row.split
        if (row.objective_digest != objective.digest or
                row.observer_id != objective.observer_id or row.source != "external"):
            raise EvidenceError("self-scored or wrong-objective outcome")
        if not isfinite(row.utility) or not 0 <= row.utility <= 1:
            raise EvidenceError("outcome outside frozen utility range")
        if not isfinite(row.actual_cost) or row.actual_cost < 0:
            raise EvidenceError("invalid observed resource cost")
    return tuple(rows)


def paired_advantage(rows: Sequence[Outcome], baseline: str, action: str,
                     split: str = "train", min_pairs: int = 8) -> float:
    by_episode: dict[str, dict[str, Outcome]] = {}
    for row in rows:
        if row.split == split and row.action in (baseline, action):
            by_episode.setdefault(row.episode, {})[row.action] = row
    pairs = [r for r in by_episode.values() if baseline in r and action in r]
    if len(pairs) < min_pairs:
        raise InsufficientSupport("missing independent paired outcome support")
    return sum(r[action].utility-r[baseline].utility for r in pairs)/len(pairs)


@dataclass(frozen=True)
class ModalityTrace:
    modality: str
    entities: tuple[tuple[str, str], ...]
    events_ms: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class CycleProbe:
    source_modality: str
    target_modality: str
    forward_label: str
    reconstructed_label: str
    independent_label: str
    observer_id: str


def check_multimodal_consistency(traces: Sequence[ModalityTrace],
                                 probes: Sequence[CycleProbe],
                                 objective: Objective) -> dict[str, int]:
    if len({t.modality for t in traces}) < 2:
        raise InsufficientSupport("requires two modalities")
    by_entity: dict[str, str] = {}
    by_event: dict[str, list[tuple[str, int]]] = {}
    for trace in traces:
        if len(dict(trace.entities)) != len(trace.entities):
            raise EvidenceError("duplicate entity in one modality")
        for entity, value in trace.entities:
            if entity in by_entity and by_entity[entity] != value:
                raise EvidenceError("cross-modal entity conflict")
            by_entity[entity] = value
        for event, ts in trace.events_ms:
            if ts < 0:
                raise EvidenceError("negative media timestamp")
            by_event.setdefault(event, []).append((trace.modality, ts))
    sync_pairs = 0
    for entries in by_event.values():
        if len({m for m, _ in entries}) >= 2:
            times = [ts for _, ts in entries]
            if max(times) - min(times) > objective.max_sync_skew_ms:
                raise EvidenceError("cross-modal time misalignment")
            sync_pairs += 1
    modalities = {t.modality for t in traces}
    if not probes:
        raise InsufficientSupport("cycle probes required")
    for probe in probes:
        if (probe.observer_id != objective.observer_id or
                probe.source_modality == probe.target_modality or
                probe.source_modality not in modalities or
                probe.target_modality not in modalities):
            raise EvidenceError("invalid independent cross-modal cycle")
        if not (probe.forward_label == probe.reconstructed_label == probe.independent_label):
            raise EvidenceError("cycle disagrees with independent truth")
    if {"audio", "video"}.issubset(modalities) and sync_pairs == 0:
        raise InsufficientSupport("no shared audio/video synchronization event")
    return {"entities": len(by_entity), "synchronized_events": sync_pairs,
            "independent_cycles": len(probes)}


@dataclass(frozen=True)
class JointSample:
    context: str
    returns: tuple[float, ...]
    joint_propensity: float
    split: str = "train"


@dataclass(frozen=True)
class Covariance:
    matrix: tuple[tuple[float, ...], ...]
    effective_n: float
    eigenvalues: tuple[float, ...]
    rank: int
    shrinkage: float
    low_rank_factor: tuple[tuple[float, ...], ...]
    diagonal_residual: tuple[float, ...]
    relative_frobenius_error: float


def _symmetric_eigenpairs(a: Sequence[Sequence[float]]) -> list[tuple[float, tuple[float, ...]]]:
    """Deterministic small-matrix Jacobi eigendecomposition (no BLAS)."""
    n = len(a)
    b = [list(row) for row in a]
    vectors = [[float(i == j) for j in range(n)] for i in range(n)]
    for _ in range(80 * n * n):
        p, q = max(((i, j) for i in range(n) for j in range(i+1, n)),
                   key=lambda ij: abs(b[ij[0]][ij[1]]), default=(0, 0))
        if p == q or abs(b[p][q]) < 1e-11:
            break
        tau = (b[q][q]-b[p][p])/(2*b[p][q])
        t = (1 if tau >= 0 else -1)/(abs(tau)+sqrt(1+tau*tau))
        c, s = 1/sqrt(1+t*t), t/sqrt(1+t*t)
        app, aqq, apq = b[p][p], b[q][q], b[p][q]
        b[p][p], b[q][q] = app-t*apq, aqq+t*apq
        b[p][q] = b[q][p] = 0.0
        for j in range(n):
            vjp, vjq = vectors[j][p], vectors[j][q]
            vectors[j][p], vectors[j][q] = c*vjp-s*vjq, s*vjp+c*vjq
            if j not in (p, q):
                jp, jq = b[j][p], b[j][q]
                b[j][p] = b[p][j] = c*jp-s*jq
                b[j][q] = b[q][j] = s*jp+c*jq
    return sorted(((b[i][i], tuple(vectors[j][i] for j in range(n)))
                   for i in range(n)), key=lambda x: x[0], reverse=True)


def conditional_covariance(samples: Sequence[JointSample], context: str,
                           dim: int, rank: int = 2,
                           shrinkage: float = 0.4) -> Covariance:
    """Paired *joint* returns, known behavior propensities, training-only.

    Low-rank factor and diagonal residual approximate covariance, with a
    measured reconstruction residual and conservative failure on poor fit.
    """
    if not 1 <= dim <= 8 or not 1 <= rank <= dim or not 0 < shrinkage <= 1:
        raise EvidenceError("invalid covariance profile")
    rows = [s for s in samples if s.context == context and s.split == "train"]
    if len(rows) < max(8, 4*dim):
        raise InsufficientSupport("too few paired joint samples")
    for s in rows:
        if (len(s.returns) != dim or
                not all(isfinite(v) for v in s.returns) or
                not isfinite(s.joint_propensity) or
                not 0 < s.joint_propensity <= 1):
            raise EvidenceError("invalid joint sample or unknown propensity")
    inv = [1/s.joint_propensity for s in rows]
    if max(inv)/min(inv) > 20:
        raise InsufficientSupport("unsupported propensity concentration")
    sw = sum(inv)
    p = [v/sw for v in inv]
    ess = 1/sum(v*v for v in p)
    if ess < max(8, 3*dim):
        raise InsufficientSupport("insufficient effective sample size")
    means = [sum(p[j]*r.returns[i] for j, r in enumerate(rows)) for i in range(dim)]
    correction = 1-sum(x*x for x in p)
    raw = [[sum(p[k]*(s.returns[i]-means[i])*(s.returns[j]-means[j])
                for k, s in enumerate(rows))/correction for j in range(dim)] for i in range(dim)]
    if min(raw[i][i] for i in range(dim)) <= 1e-10:
        raise InsufficientSupport("degenerate joint observations: variance unidentifiable")
    diag_floor = 1e-8
    matrix = [[((1-shrinkage)*raw[i][j] if i != j else raw[i][i]+diag_floor)
               for j in range(dim)] for i in range(dim)]
    eig = _symmetric_eigenpairs(matrix)
    eigen = [value for value, _ in eig]
    if eigen[-1] <= 1e-9 or eigen[0]/eigen[-1] > 1e6:
        raise InsufficientSupport("singular or poorly conditioned covariance")
    factor = tuple(tuple(sqrt(eig[k][0])*eig[k][1][i] for k in range(rank))
                   for i in range(dim))
    residual = tuple(max(0., matrix[i][i]-sum(x*x for x in factor[i]))
                     for i in range(dim))
    approximate = [[sum(factor[i][k]*factor[j][k] for k in range(rank)) +
                    (residual[i] if i == j else 0.) for j in range(dim)]
                   for i in range(dim)]
    norm = sqrt(sum(matrix[i][j]**2 for i in range(dim) for j in range(dim)))
    error = sqrt(sum((matrix[i][j]-approximate[i][j])**2
                     for i in range(dim) for j in range(dim)))/norm
    if error > 0.25:
        raise InsufficientSupport("low-rank approximation residual unsupported")
    return Covariance(tuple(tuple(v for v in row) for row in matrix),
                      ess, tuple(eigen), rank, shrinkage, factor, residual, error)


@dataclass(frozen=True)
class Portfolio:
    weights: tuple[float, ...]
    score: float
    method: str


def choose_portfolio(advantages: Sequence[float], costs: Sequence[float],
                     budget: float, gamma: float,
                     covariance: Covariance | None,
                     prior: Sequence[float] | None = None,
                     beta: float = 0.0, slots: int = 10) -> Portfolio:
    """Finite simplex search of a *routing distribution*, not tensor blending.

    Every nonzero route must itself fit the HARD cost bound. Advantage is already
    cost-adjusted by its registered NDU profile; no second cost deduction here.
    """
    n = len(advantages)
    if (not 1 <= n <= 5 or len(costs) != n or slots < 1 or
            not isfinite(budget) or budget <= 0 or gamma < 0 or beta < 0 or
            not all(isfinite(a) for a in advantages) or
            not all(isfinite(c) and c >= 0 for c in costs)):
        raise EvidenceError("invalid portfolio inputs")
    if prior is None:
        prior = [1/n]*n
    if len(prior) != n or any(p <= 0 for p in prior) or abs(sum(prior)-1) > 1e-8:
        raise EvidenceError("invalid registered reference policy")
    if covariance is not None and len(covariance.matrix) != n:
        raise EvidenceError("covariance dimension mismatch")
    if covariance is None and gamma > 0:
        raise InsufficientSupport("risk covariance unavailable; use deterministic NDU")
    best = None
    for counts in product(range(slots+1), repeat=n):
        if sum(counts) != slots or any(counts[i] and costs[i] > budget for i in range(n)):
            continue
        weights = tuple(c/slots for c in counts)
        gain = sum(w*a for w, a in zip(weights, advantages))
        risk = (sum(sum(weights[i]*covariance.low_rank_factor[i][k]
                         for i in range(n))**2 for k in range(covariance.rank)) +
                sum(weights[i]**2*covariance.diagonal_residual[i] for i in range(n))
                if covariance else 0.0)
        kl = sum(w*log(w/prior[i]) for i, w in enumerate(weights) if w)
        value = gain - gamma*risk/2 - beta*kl
        if best is None or value > best.score+1e-12:
            best = Portfolio(weights, value, "stochastic" if covariance else "deterministic")
    if best is None:
        raise InsufficientSupport("no legal portfolio; abstain required")
    return best


def local_shapley_credit(actors: Sequence[str],
                         coalition_utilities: Mapping[frozenset[str], float],
                         observer_id: str, objective: Objective) -> dict[str, float]:
    """Exact global-to-local credit *only* for complete independently observed ablations."""
    n = len(actors)
    if observer_id != objective.observer_id or not 1 <= n <= 6 or len(set(actors)) != n:
        raise EvidenceError("invalid coalition observer or actor list")
    universe = frozenset(actors)
    for bits in product((False, True), repeat=n):
        key = frozenset(actors[i] for i, b in enumerate(bits) if b)
        if key not in coalition_utilities:
            raise InsufficientSupport("missing independently observed coalition")
        if not isfinite(coalition_utilities[key]):
            raise EvidenceError("nonfinite coalition utility")
    result = {}
    for actor in actors:
        rest = sorted(universe-{actor})
        gain = 0.0
        for bits in product((False, True), repeat=n-1):
            subset = frozenset(rest[i] for i, b in enumerate(bits) if b)
            k = len(subset)
            weight = factorial(k)*factorial(n-k-1)/factorial(n)
            gain += weight*(coalition_utilities[subset|{actor}]-coalition_utilities[subset])
        result[actor] = gain
    if abs(sum(result.values())-(coalition_utilities[universe]-coalition_utilities[frozenset()])) > 1e-8:
        raise EvidenceError("global/local utility conservation failed")
    return result


@dataclass(frozen=True)
class ClosureRow:
    state: str
    action: str
    history: str
    next_value: float
    split: str


def closure_audit(rows: Sequence[ClosureRow], improvement_tolerance: float = 0.02) -> dict:
    """Held-out comparison: state+action predictor vs history-augmented predictor.

    Unseen history must not be silently treated as a sufficient state.
    """
    train = [r for r in rows if r.split == "train"]
    test = [r for r in rows if r.split == "future"]
    if len(train) < 8 or len(test) < 4:
        raise InsufficientSupport("too few train and held-out closure rows")
    def fit(include_history):
        groups: dict[tuple, list[float]] = {}
        for r in train:
            key = (r.state, r.action, r.history) if include_history else (r.state, r.action)
            groups.setdefault(key, []).append(r.next_value)
        return {k: sum(v)/len(v) for k, v in groups.items() if len(v) >= 2}
    coarse, fine = fit(False), fit(True)
    def mse(fitted, include_history):
        errors = []
        for r in test:
            key = (r.state, r.action, r.history) if include_history else (r.state, r.action)
            if key not in fitted:
                raise InsufficientSupport("missing held-out conditional state support")
            errors.append((r.next_value-fitted[key])**2)
        return sum(errors)/len(errors)
    coarse_error, fine_error = mse(coarse, False), mse(fine, True)
    return {"state_mse": coarse_error, "history_mse": fine_error,
            "sufficient": coarse_error-fine_error <= improvement_tolerance}


def stage_next_snapshot(selected_generation: int, proposed_generation: int,
                        old_policy: Sequence[float], new_policy: Sequence[float],
                        frozen_critic_digest: str, current_critic_digest: str,
                        max_kl: float = 0.05) -> dict:
    if (proposed_generation <= selected_generation or not frozen_critic_digest or
            frozen_critic_digest != current_critic_digest):
        raise EvidenceError("stale critic or current-generation mutation")
    if (len(old_policy) != len(new_policy) or
            any(a <= 0 or b < 0 for a, b in zip(old_policy, new_policy)) or
            abs(sum(old_policy)-1) > 1e-8 or abs(sum(new_policy)-1) > 1e-8):
        raise EvidenceError("invalid bounded policy update")
    kl = sum(q*log(q/p) for p, q in zip(old_policy, new_policy) if q)
    if kl > max_kl:
        raise EvidenceError("trust region exceeded")
    return {"advisory_only": True, "proposed_generation": proposed_generation,
            "critic_digest": frozen_critic_digest, "kl": kl}


def future_window_gate(candidate: Sequence[float], baseline: Sequence[float],
                       retained_candidate: Sequence[float],
                       retained_baseline: Sequence[float], alpha: float = 0.05) -> dict:
    """Independent fixed-objective future and retention gate; no promotion authority."""
    arrays = (candidate, baseline, retained_candidate, retained_baseline)
    if (not 0 < alpha < 1 or any(len(x) < 100 for x in arrays) or
            any(not isfinite(v) or not 0 <= v <= 1 for x in arrays for v in x)):
        raise InsufficientSupport("insufficient bounded independent future-window outcomes")
    def mean_ci(xs):
        mean = sum(xs)/len(xs)
        rad = sqrt(log(4/alpha)/(2*len(xs)))
        return mean, max(0., mean-rad), min(1., mean+rad)
    c, b, rc, rb = [mean_ci(x) for x in arrays]
    return {"admitted": c[1] > b[2] and rc[1] >= rb[2]-0.02,
            "future_candidate_lcb": c[1], "future_baseline_ucb": b[2],
            "retention_candidate_lcb": rc[1], "retention_baseline_ucb": rb[2],
            "authority_granted": False}


EXPERIMENT_MODES = {
    "A0": "frozen single-decoder no-change baseline",
    "A1": "fixed routing and fixed budget",
    "A2": "ordinary learned Top-k router",
    "A3": "one-step frozen NDU advantage",
    "A4": "supported conditional covariance portfolio",
    "A5": "receding-horizon recursive NDU control and stopping",
}
