#!/usr/bin/env python3
"""NDU-DMGP shadow-only research reference. No production authority or model calls.

Every claimed observation, cost, split and identity must be admitted separately.
Synthetic runs exercise algorithms only: they can never satisfy deployment gates.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
import tracemalloc
from dataclasses import dataclass
from typing import Mapping, Sequence

ARMS = ("A0", "A1", "A2", "A3", "A4", "A5")
MODALITIES = frozenset({"text", "image", "audio", "video"})


class GateRejected(ValueError):
    """Reject an unqualified candidate; do not silently assign a zero score."""


def _finite(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise GateRejected(f"{label}: non-finite")
    return value


def _digest(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Objective:
    objective_id: str
    generation: int
    allowed_modalities: frozenset[str]
    required_modalities: frozenset[str]
    budget_units: float
    resource_price: float
    risk_price: float
    max_action_risk: float

    def __post_init__(self) -> None:
        if (not self.objective_id or self.generation < 1
                or not self.allowed_modalities.issubset(MODALITIES)
                or not self.required_modalities.issubset(self.allowed_modalities)
                or not self.allowed_modalities):
            raise GateRejected("invalid frozen objective")
        for key in ("budget_units", "resource_price", "risk_price", "max_action_risk"):
            if _finite(getattr(self, key), key) < 0:
                raise GateRejected(f"negative {key}")
        if self.budget_units <= 0:
            raise GateRejected("zero budget")

    @property
    def digest(self) -> str:
        return _digest({
            "objective_id": self.objective_id, "generation": self.generation,
            "allowed": sorted(self.allowed_modalities),
            "required": sorted(self.required_modalities),
            "budget": self.budget_units,
            "resource_price": self.resource_price, "risk_price": self.risk_price,
            "max_action_risk": self.max_action_risk,
        })


@dataclass(frozen=True)
class Observation:
    episode: str
    objective_digest: str
    generation: int
    policy_id: str
    actor_id: str
    observer_id: str
    split: str
    observed_at: int
    quality: float
    compute_units: float
    risk: float
    evidence_kind: str
    resource_metered: bool


def independent_utility(objective: Objective, item: Observation) -> float:
    """No Actor-authored reward, unmetered cost or synthetic evidence is admitted."""
    if (not item.episode or item.objective_digest != objective.digest
            or item.generation != objective.generation
            or not item.actor_id or not item.observer_id
            or item.actor_id == item.observer_id
            or item.evidence_kind != "independent_observation"
            or not item.resource_metered or item.observed_at <= 0
            or item.split not in ("train", "validation", "future", "retention")):
        raise GateRejected("untrusted outcome, source or objective revision")
    if not item.policy_id:
        raise GateRejected("missing policy identity")
    for key in ("quality", "compute_units", "risk"):
        _finite(getattr(item, key), key)
    if item.compute_units < 0 or not 0 <= item.risk <= 1:
        raise GateRejected("invalid physical resource/risk observation")
    return (item.quality - objective.resource_price * item.compute_units
            - objective.risk_price * item.risk)


def validate_splits(train: Sequence[Observation], future: Sequence[Observation]) -> None:
    if not train or not future:
        raise GateRejected("missing train/future episodes")
    if {r.episode for r in train} & {r.episode for r in future}:
        raise GateRejected("episode leakage across chronological splits")
    if any(r.split != "train" for r in train) or any(r.split != "future" for r in future):
        raise GateRejected("wrong split labels")
    if max(r.observed_at for r in train) >= min(r.observed_at for r in future):
        raise GateRejected("future evaluation predates training cutoff")


@dataclass(frozen=True)
class MediaEvent:
    event_id: str
    modality: str
    start_ms: int
    end_ms: int
    entity_ids: frozenset[str]
    semantic_tags: frozenset[str]
    pair_id: str = ""


@dataclass(frozen=True)
class ConsistencyResult:
    supported: bool
    violations: tuple[str, ...]
    checked_pairs: int


def cross_modal_contract(
    objective: Objective,
    events: Sequence[MediaEvent],
    source_entities: frozenset[str],
    source_tags: frozenset[str],
    max_av_skew_ms: int = 120,
) -> ConsistencyResult:
    """Structured, bidirectional checks; NOT perceptual quality or semantic truth."""
    problems: list[str] = []
    checked = 0
    seen: set[str] = set()
    by_pair: dict[str, list[MediaEvent]] = {}
    for event in events:
        if event.event_id in seen or not event.event_id:
            problems.append("duplicate/empty event identity")
        seen.add(event.event_id)
        if event.modality not in objective.allowed_modalities:
            problems.append("forbidden modality")
        if event.start_ms < 0 or event.end_ms <= event.start_ms:
            problems.append("invalid event timeline")
        if not event.entity_ids.issubset(source_entities):
            problems.append("unverified generated entity")
        if not event.semantic_tags.issubset(source_tags):
            problems.append("unsupported generated semantic tag")
        if event.pair_id:
            by_pair.setdefault(event.pair_id, []).append(event)
    emitted = {e.modality for e in events}
    if not objective.required_modalities.issubset(emitted):
        problems.append("missing required output modality")
    reconstructed_entities = frozenset().union(*(e.entity_ids for e in events))
    reconstructed_tags = frozenset().union(*(e.semantic_tags for e in events))
    # Supported sources -> output and output -> supported sources are both checked.
    if source_entities - reconstructed_entities:
        problems.append("source entities lost in output reconstruction")
    if source_tags - reconstructed_tags:
        problems.append("source semantic tags lost in output reconstruction")
    for pair in by_pair.values():
        audio = [e for e in pair if e.modality == "audio"]
        video = [e for e in pair if e.modality == "video"]
        if bool(audio) != bool(video):
            problems.append("unpaired audio-video timeline")
        if audio and video:
            for a in audio:
                for v in video:
                    checked += 1
                    if (abs(a.start_ms - v.start_ms) > max_av_skew_ms
                            or abs(a.end_ms - v.end_ms) > max_av_skew_ms):
                        problems.append("audio-video temporal misalignment")
                    if not a.entity_ids.intersection(v.entity_ids):
                        problems.append("audio-video entity disagreement")
    if max_av_skew_ms < 0:
        problems.append("invalid skew profile")
    return ConsistencyResult(not problems, tuple(sorted(set(problems))), checked)


@dataclass(frozen=True)
class Covariance:
    supported: bool
    matrix: tuple[tuple[float, ...], ...]
    sample_count: int
    condition_number: float
    factor_rank: int
    reason: str

    def risk(self, weights: Sequence[float]) -> float:
        if not self.supported or len(weights) != len(self.matrix):
            raise GateRejected("unsupported covariance dimension")
        return max(0.0, sum(
            weights[i] * self.matrix[i][j] * weights[j]
            for i in range(len(weights)) for j in range(len(weights))
        ))


def _eigen_symmetric(matrix: list[list[float]]) -> list[tuple[float, list[float]]]:
    """Deterministic Jacobi eigensolver; bounded small research matrices only."""
    n = len(matrix)
    a = [row[:] for row in matrix]
    v = [[float(i == j) for j in range(n)] for i in range(n)]
    for _ in range(120 * n * n):
        p, q = 0, 0
        biggest = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > biggest:
                    p, q, biggest = i, j, abs(a[i][j])
        if biggest < 1e-11:
            break
        phi = 0.5 * math.atan2(2 * a[p][q], a[q][q] - a[p][p])
        c, s = math.cos(phi), math.sin(phi)
        # Rotated columns: p'=c*p-s*q, q'=s*p+c*q
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = c*c*app - 2*c*s*apq + s*s*aqq
        a[q][q] = s*s*app + 2*c*s*apq + c*c*aqq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            if k == p or k == q:
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = c*akp - s*akq
            a[k][q] = a[q][k] = s*akp + c*akq
        for k in range(n):
            vp, vq = v[k][p], v[k][q]
            v[k][p], v[k][q] = c*vp - s*vq, s*vp + c*vq
    return sorted(((a[i][i], [v[k][i] for k in range(n)]) for i in range(n)),
                  key=lambda x: x[0], reverse=True)


def paired_covariance(
    episode_outcomes: Mapping[str, Mapping[str, float]],
    experts: Sequence[str],
    *, shrinkage: float = 0.25,
    floor: float = 1e-5,
    rank: int | None = None,
) -> Covariance:
    """Paired condition-scoped outcomes, shrinkage and optional PSD low-rank+diagonal.

    This is portfolio outcome risk, NOT the NDU FBSDE martingale covariance.
    """
    k, n = len(experts), len(episode_outcomes)
    bad = lambda reason: Covariance(False, (), n, math.inf, 0, reason)
    if not 1 <= k <= 8 or len(set(experts)) != k:
        return bad("unsupported or duplicate expert dimensions")
    if not 0 <= shrinkage <= 1 or floor <= 0 or not math.isfinite(floor):
        return bad("invalid covariance profile")
    if n < max(8, 3 * k):
        return bad("insufficient matched episodes")
    if rank is not None and not 1 <= rank <= k:
        return bad("invalid low-rank profile")
    samples = []
    for row in episode_outcomes.values():
        if set(row) != set(experts):
            return bad("unpaired or mismatched expert outcomes")
        samples.append([row[e] for e in experts])
        if not all(math.isfinite(x) and abs(x) <= 1e6 for x in samples[-1]):
            return bad("invalid numerical observation")
    mean = [statistics.fmean(row[i] for row in samples) for i in range(k)]
    raw = [[sum((row[i]-mean[i])*(row[j]-mean[j]) for row in samples)/(n-1)
            for j in range(k)] for i in range(k)]
    if min(raw[i][i] for i in range(k)) <= floor:
        return bad("unidentified or constant risk direction")
    shrunk = [[(1-shrinkage)*raw[i][j] if i != j else raw[i][i] + floor
               for j in range(k)] for i in range(k)]
    eig = _eigen_symmetric(shrunk)
    e_min = eig[-1][0]
    cond = eig[0][0] / max(e_min, 1e-300)
    if e_min < floor / 2 or cond > 1e6:
        return bad("singular or ill-conditioned covariance")
    r = rank or k
    if r < k:
        approx = [[sum(eig[h][0] * eig[h][1][i] * eig[h][1][j]
                       for h in range(r)) for j in range(k)] for i in range(k)]
        # PSD factor component plus diagonal remainder (nonnegative on precision tolerance).
        diag = [max(floor, shrunk[i][i] - approx[i][i]) for i in range(k)]
        for i in range(k):
            approx[i][i] += diag[i]
        shrunk = approx
    return Covariance(True, tuple(tuple(row) for row in shrunk), n, cond, r, "supported")


def _softmax(logits: Sequence[float]) -> list[float]:
    pivot = max(logits)
    exp = [math.exp(v - pivot) for v in logits]
    total = sum(exp)
    return [v / total for v in exp]


def portfolio_weights(
    advantage: Sequence[float], covariance: Covariance, *,
    risk_price: float = 1.0, kl_price: float = 0.3,
) -> tuple[float, ...]:
    """Bounded KL-regularized risk-sensitive one-step allocation on simplex."""
    n = len(advantage)
    if not n or n > 8 or any(not math.isfinite(x) for x in advantage):
        raise GateRejected("invalid portfolio advantages")
    if (not math.isfinite(risk_price) or risk_price < 0
            or kl_price <= 0 or not math.isfinite(kl_price)):
        raise GateRejected("invalid portfolio optimization profile")
    if not covariance.supported or len(covariance.matrix) != n:
        # Explicit deterministic NDU fallback when covariance is unidentified.
        winner = max(range(n), key=lambda i: (advantage[i], -i))
        return tuple(float(i == winner) for i in range(n))
    if any(len(row) != n or any(not math.isfinite(v) for v in row)
           for row in covariance.matrix):
        raise GateRejected("malformed portfolio covariance")
    if (any(covariance.matrix[i][i] < 0 for i in range(n))
            or any(abs(covariance.matrix[i][j] - covariance.matrix[j][i]) > 1e-8
                   for i in range(n) for j in range(n))
            or _eigen_symmetric([list(row) for row in covariance.matrix])[-1][0] < -1e-8):
        raise GateRejected("non-PSD or asymmetric portfolio covariance")
    weight = [1 / n] * n
    for _ in range(256):
        grad = [advantage[i] - risk_price * sum(
            covariance.matrix[i][j] * weight[j] for j in range(n)
        ) for i in range(n)]
        candidate = _softmax([g / kl_price for g in grad])
        nxt = [(a + b) / 2 for a, b in zip(weight, candidate)]
        if max(abs(a-b) for a, b in zip(nxt, weight)) < 1e-9:
            weight = nxt
            break
        weight = nxt
    return tuple(weight)


@dataclass(frozen=True)
class CellCredit:
    cell_id: str
    credit: float
    observer_id: str
    support_digest: str


def credit_conservation(
    global_delta: float, credits: Sequence[CellCredit],
    interaction_credit: float, tolerance: float = 1e-6,
) -> float:
    if not credits or not math.isfinite(tolerance) or tolerance < 0:
        raise GateRejected("missing credit/conservation profile")
    if len({c.cell_id for c in credits}) != len(credits):
        raise GateRejected("duplicate cell credit")
    if any(not c.support_digest or not c.observer_id or not math.isfinite(c.credit)
           for c in credits):
        raise GateRejected("unsupported local credit")
    _finite(global_delta, "global utility")
    _finite(interaction_credit, "interaction credit")
    residual = global_delta - sum(c.credit for c in credits) - interaction_credit
    if abs(residual) > tolerance:
        raise GateRejected("local rewards do not reconstruct global NDU")
    return residual


def closure_audit(
    train: Sequence[tuple[str, str, float]],
    heldout: Sequence[tuple[str, str, float]],
    *, maximum_mse_gain: float = 0.05,
) -> tuple[bool, float]:
    """Heldout history-predictivity test for a compressed state (not Markov proof)."""
    if len(train) < 4 or len(heldout) < 2:
        raise GateRejected("insufficient state closure evidence")
    if not all(math.isfinite(row[2]) for row in (*train, *heldout)):
        raise GateRejected("invalid closure sample")
    _finite(maximum_mse_gain, "closure tolerance")
    if maximum_mse_gain < 0:
        raise GateRejected("negative closure tolerance")
    by_state: dict[str, list[float]] = {}
    by_history: dict[tuple[str, str], list[float]] = {}
    for state, history, outcome in train:
        by_state.setdefault(state, []).append(outcome)
        by_history.setdefault((state, history), []).append(outcome)
    if any(s not in by_state or (s, h) not in by_history for s, h, _ in heldout):
        raise GateRejected("heldout state/history outside training support")
    compressed_err, expanded_err = 0., 0.
    for s, h, outcome in heldout:
        compressed_err += (outcome - statistics.fmean(by_state[s]))**2
        expanded_err += (outcome - statistics.fmean(by_history[(s, h)]))**2
    mse_gain = (compressed_err - expanded_err) / len(heldout)
    return mse_gain <= maximum_mse_gain, mse_gain


@dataclass(frozen=True)
class GenerationAction:
    name: str
    modality: str
    compute_units: float
    immediate_gain: float
    risk: float
    observed_gain: float | None = None

    def __post_init__(self) -> None:
        if not self.name or self.modality not in MODALITIES or self.compute_units <= 0:
            raise GateRejected("invalid generation action")
        for key in ("compute_units", "immediate_gain", "risk"):
            _finite(getattr(self, key), key)
        if not 0 <= self.risk <= 1:
            raise GateRejected("invalid action risk")
        if self.observed_gain is not None:
            _finite(self.observed_gain, "observed gain")


@dataclass(frozen=True)
class Scenario:
    episode: str
    actions: tuple[GenerationAction, ...]
    synergy: Mapping[tuple[str, str], float]  # pre-registered forecast, not test oracle
    budget: float
    horizon: int
    observed_synergy: Mapping[tuple[str, str], float] | None = None

    def __post_init__(self) -> None:
        if (not self.episode or not 1 <= self.horizon <= 8 or len(self.actions) > 8
                or self.budget <= 0 or not math.isfinite(self.budget)
                or len({a.name for a in self.actions}) != len(self.actions)):
            raise GateRejected("invalid bounded generation scenario")
        ids = {a.name for a in self.actions}
        for ledger in (self.synergy, self.observed_synergy or {}):
            if any(a == b or a not in ids or b not in ids
                   or not math.isfinite(v) for (a, b), v in ledger.items()):
                raise GateRejected("invalid registered pair interaction")

    def value(self, chosen: Sequence[str], resource_price: float, risk_price: float, *,
              observed: bool = False) -> float:
        lookup = {a.name: a for a in self.actions}
        base = sum((lookup[name].observed_gain if observed and lookup[name].observed_gain is not None
                    else lookup[name].immediate_gain)
                   - resource_price*lookup[name].compute_units
                   - risk_price*lookup[name].risk for name in chosen)
        synergy = (self.observed_synergy if observed and self.observed_synergy is not None
                   else self.synergy)
        return base + sum(bonus for (x, y), bonus in synergy.items()
                          if x in chosen and y in chosen)


def _feasible(scenario: Scenario, used: tuple[str, ...], budget: float,
              objective: Objective) -> list[GenerationAction]:
    return [a for a in scenario.actions if a.name not in used
            and a.modality in objective.allowed_modalities
            and a.compute_units > 0 and a.compute_units <= budget + 1e-9
            and a.risk <= objective.max_action_risk]


def fit_static_topk_router(train: Sequence[Scenario], objective: Objective) -> dict[str, float]:
    """A2: train a lightweight top-k score table on TRAIN observations only.

    No evaluation episode or its realized benefit may enter this fitted table.
    """
    if len(train) < 8 or len({s.episode for s in train}) != len(train):
        raise GateRejected("insufficient or overlapping router training episodes")
    seen: dict[str, list[float]] = {}
    for scenario in train:
        for action in scenario.actions:
            if action.observed_gain is None:
                raise GateRejected("router training lacks independently observed label")
            net = (action.observed_gain - objective.resource_price*action.compute_units
                   - objective.risk_price*action.risk) / action.compute_units
            seen.setdefault(action.name, []).append(net)
    return {name: statistics.fmean(values) for name, values in seen.items()}


def _lookahead(scenario: Scenario, used: tuple[str, ...], budget: float,
               steps: int, objective: Objective) -> tuple[float, str | None]:
    current = scenario.value(used, objective.resource_price, objective.risk_price)
    emitted = {a.modality for a in scenario.actions if a.name in used}
    # Stop is only valid after required output modalities have been satisfied.
    best_score = current if objective.required_modalities.issubset(emitted) else -math.inf
    choice = None
    if steps <= 0:
        return best_score, choice
    for a in _feasible(scenario, used, budget, objective):
        score, _ = _lookahead(scenario, used+(a.name,), budget-a.compute_units,
                              steps-1, objective)
        if score > best_score + 1e-10:
            best_score, choice = score, a.name
    return best_score, choice


def choose_action(arm: str, scenario: Scenario, used: tuple[str, ...],
                  budget: float, objective: Objective,
                  covariance: Covariance,
                  learned_router_scores: Mapping[str, float] | None = None) -> str | None:
    actions = _feasible(scenario, used, budget, objective)
    if not actions:
        return None
    if arm == "A0":
        return "flash" if not used and any(a.name == "flash" for a in actions) else None
    if arm == "A1":
        return next((name for name in ("text", "image", "audio", "video")
                     if any(a.name == name for a in actions)), None)
    if arm == "A2":
        if learned_router_scores is not None:
            if not all(a.name in learned_router_scores and
                       math.isfinite(learned_router_scores[a.name]) for a in actions):
                raise GateRejected("untrained or unqualified expert routing score")
            return max(actions, key=lambda a: learned_router_scores[a.name]).name
        # A2 unit-test-only fallback; the matrix experiment supplies fitted scores.
        return max(actions, key=lambda a: a.immediate_gain / a.compute_units).name
    if arm == "A3":
        return max(actions, key=lambda a: a.immediate_gain
                   - objective.resource_price*a.compute_units
                   - objective.risk_price*a.risk).name
    if arm == "A4":
        advantage = [a.immediate_gain - objective.resource_price*a.compute_units
                     - objective.risk_price*a.risk for a in actions]
        # Covariance identity belongs to expert labels, not the changing feasible subset.
        if covariance.supported and len(covariance.matrix) == len(scenario.actions):
            indices = [list(scenario.actions).index(a) for a in actions]
            matrix = tuple(tuple(covariance.matrix[i][j] for j in indices)
                           for i in indices)
            subcov = Covariance(True, matrix, covariance.sample_count,
                                covariance.condition_number, covariance.factor_rank, "submatrix")
        else:
            subcov = Covariance(False, (), covariance.sample_count, math.inf, 0,
                                "fallback to deterministic NDU")
        weights = portfolio_weights(advantage, subcov, risk_price=1.0)
        return actions[max(range(len(actions)), key=lambda i: weights[i])].name
    if arm == "A5":
        _, choice = _lookahead(scenario, used, budget, scenario.horizon-len(used), objective)
        return choice
    raise GateRejected("unknown or unregistered ablation arm")


def run_shadow_arm(arm: str, scenario: Scenario, objective: Objective,
                   covariance: Covariance,
                   learned_router_scores: Mapping[str, float] | None = None) -> dict[str, object]:
    """Scenario/decoder outputs are SYNTHETIC; only controller time is actually timed."""
    if arm not in ARMS:
        raise GateRejected("unregistered ablation arm")
    if scenario.horizon < 1 or scenario.horizon > 8 or scenario.budget > objective.budget_units:
        raise GateRejected("invalid horizon/resource envelope")
    if len({a.name for a in scenario.actions}) != len(scenario.actions):
        raise GateRejected("duplicate expert names")
    used: tuple[str, ...] = ()
    budget = scenario.budget
    controller_us = 0.
    tracemalloc.start()
    try:
        for _ in range(scenario.horizon):
            start = time.perf_counter_ns()
            choice = choose_action(arm, scenario, used, budget, objective, covariance,
                                   learned_router_scores)
            controller_us += (time.perf_counter_ns() - start)/1000
            if choice is None:
                break
            action = next(a for a in scenario.actions if a.name == choice)
            used += (action.name,)
            budget -= action.compute_units
            if arm == "A0":
                break
        peak_bytes = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    emitted = {a.modality for a in scenario.actions if a.name in used}
    complete = objective.required_modalities.issubset(emitted)
    return {
        "arm": arm, "episode": scenario.episode, "selected": list(used),
        "output_contract_satisfied": complete,
        "disposition": "completed" if complete else "abstain_missing_modality",
        "synthetic_ndu": (scenario.value(used, objective.resource_price,
                                         objective.risk_price, observed=True)
                          if complete else None),
        "synthetic_compute_units": scenario.budget - budget,
        "controller_time_us_measured": round(controller_us, 3),
        "controller_peak_python_bytes_measured": peak_bytes,
        "decoder_runtime_measured": False,
        "evidence_kind": "synthetic_reference",
        "promotion_eligible": False,
    }


def make_scenarios(count: int = 24) -> tuple[Scenario, ...]:
    if count <= 0:
        raise GateRejected("empty scenario count")
    result = []
    for i in range(count):
        # Matched synthetic outcomes; no changing data across A0..A5.
        shift = (i % 7 - 3) * .06
        actions = (
            GenerationAction("flash", "text", 2., 3.8+shift, .25, 3.75+shift*.7),
            GenerationAction("text", "text", 1., 1.35+shift, .04, 1.28+shift*.6),
            GenerationAction("image", "image", 1., 1.18-shift, .04, 1.21-shift*.5),
            GenerationAction("audio", "audio", 1., .65, .07, .60),
        )
        result.append(Scenario(f"synthetic-episode-{i:04d}", actions,
                               {("text", "image"): 5.+i%3*.1}, 2., 3,
                               {("text", "image"): 4.5+i%4*.15}))
    return tuple(result)


def _mean_confidence(scores: Sequence[float]) -> tuple[float, float, float]:
    if len(scores) < 8:
        raise GateRejected("too few independent future episodes")
    avg = statistics.fmean(scores)
    se = statistics.stdev(scores) / math.sqrt(len(scores))
    return avg, avg-1.96*se, avg+1.96*se


def next_snapshot_gate(
    candidate: Sequence[Observation], baseline: Sequence[Observation],
    retention_candidate: Sequence[Observation], retention_baseline: Sequence[Observation],
    objective: Objective, *, selected_generation: int, candidate_generation: int,
    critic_frozen: bool, trust_region_kl: float, synthetic: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    """Conservative forward-only gate. It never grants model promotion authority."""
    reasons = []
    if synthetic:
        reasons.append("synthetic evidence is not deployment evidence")
    if not critic_frozen:
        reasons.append("critic revision not frozen")
    if candidate_generation <= selected_generation or selected_generation != objective.generation:
        reasons.append("current-run parameters cannot be mutated")
    if not math.isfinite(trust_region_kl) or trust_region_kl > .05 or trust_region_kl < 0:
        reasons.append("trust-region violation")
    for collection, split in ((candidate, "future"), (baseline, "future"),
                              (retention_candidate, "retention"),
                              (retention_baseline, "retention")):
        if not collection or any(row.split != split for row in collection):
            reasons.append(f"missing or mislabeled {split} observations")
    all_rows = tuple(candidate)+tuple(baseline)+tuple(retention_candidate)+tuple(retention_baseline)
    if len(all_rows) < 32:
        reasons.append("insufficient independent observations")
    if reasons:
        return False, tuple(sorted(set(reasons)))
    try:
        cand_scores = [independent_utility(objective, x) for x in candidate]
        base_scores = [independent_utility(objective, x) for x in baseline]
        old_cand = [independent_utility(objective, x) for x in retention_candidate]
        old_base = [independent_utility(objective, x) for x in retention_baseline]
        if (len({r.policy_id for r in candidate}) != 1
                or len({r.policy_id for r in baseline}) != 1
                or {r.policy_id for r in candidate} == {r.policy_id for r in baseline}
                or len({r.policy_id for r in retention_candidate}) != 1
                or len({r.policy_id for r in retention_baseline}) != 1
                or {r.policy_id for r in retention_candidate}
                   != {r.policy_id for r in candidate}
                or {r.policy_id for r in retention_baseline}
                   != {r.policy_id for r in baseline}):
            raise GateRejected("candidate/baseline policy identity mismatch")
        if ({r.episode for r in candidate} != {r.episode for r in baseline}
                or {r.episode for r in retention_candidate}
                != {r.episode for r in retention_baseline}
                or {r.episode for r in candidate} & {r.episode for r in retention_candidate}):
            raise GateRejected("unmatched or overlapping future/retention episodes")
        if ({r.observer_id for r in candidate} & {r.actor_id for r in candidate}
                or {r.observer_id for r in baseline} & {r.actor_id for r in baseline}):
            raise GateRejected("observer and actor roles overlap")
        c_avg, c_lcb, _ = _mean_confidence(cand_scores)
        _, _, b_ucb = _mean_confidence(base_scores)
        old_c_avg, _, _ = _mean_confidence(old_cand)
        old_b_avg, _, _ = _mean_confidence(old_base)
        if c_lcb <= b_ucb:
            reasons.append("future LCB does not exceed baseline UCB")
        if old_c_avg < old_b_avg - .02*max(abs(old_b_avg), .01):
            reasons.append("old-task degradation exceeds 2%")
    except (GateRejected, statistics.StatisticsError) as exc:
        reasons.append(str(exc))
    return not reasons, tuple(sorted(set(reasons)))


def reference_report() -> dict[str, object]:
    objective = Objective("ndu-dmgp-reference", 1, MODALITIES, frozenset(),
                          2., .05, .5, 1.)
    all_scenarios = make_scenarios(48)
    train_scenarios, scenarios = all_scenarios[:24], all_scenarios[24:]
    if {s.episode for s in train_scenarios} & {s.episode for s in scenarios}:
        raise GateRejected("evaluation scenario leaked into training data")
    learned_router = fit_static_topk_router(train_scenarios, objective)
    # Only TRAIN episodes can inform conditional covariance; evaluation stays held out.
    # Use TRAIN realized-minus-forecast residuals, never synthesized jitter
    # over forecasts. Constant or unidentified directions must disable A4 risk.
    # This is still SYNTHETIC supervision; it is not an external observation.
    if any(a.observed_gain is None for s in train_scenarios for a in s.actions):
        raise GateRejected("covariance train row lacks observed expert outcome")
    outcomes = {
        s.episode: {a.name: a.observed_gain - a.immediate_gain
                    for a in s.actions}
        for s in train_scenarios
    }
    cov = paired_covariance(outcomes, [a.name for a in scenarios[0].actions], rank=2)
    matrix = [run_shadow_arm(arm, scenario, objective, cov,
                             learned_router_scores=learned_router)
              for scenario in scenarios for arm in ARMS]
    summaries = {}
    for arm in ARMS:
        rows = [row for row in matrix if row["arm"] == arm]
        summaries[arm] = {
            "episodes": len(rows),
            "mean_synthetic_ndu": round(statistics.fmean(row["synthetic_ndu"] for row in rows), 6),
            "mean_synthetic_compute_units": round(statistics.fmean(
                row["synthetic_compute_units"] for row in rows), 6),
            "controller_p95_us_measured": round(sorted(row["controller_time_us_measured"]
                                                   for row in rows)[int(.95*(len(rows)-1))], 3),
            "controller_peak_python_bytes_max_measured": max(
                row["controller_peak_python_bytes_measured"] for row in rows),
        }
    return {
        "schema": "hepta.ndu-dmgp.shadow-report.v1", "objective_digest": objective.digest,
        "experiment_arms": list(ARMS), "dataset": "synthetic_scenarios_only",
        "training_episodes": len(train_scenarios),
        "evaluation_episodes": len(scenarios),
        "train_eval_episodes_disjoint": True,
        "a2_fitted_train_only": True,
        "covariance_supported": cov.supported,
        "covariance_condition_number": cov.condition_number if cov.supported else None,
        "real_decoder_observed": False, "independent_future_observed": False,
        "reference_assertions_only": True, "production_blockers_closed": False,
        "no_promotion_authority": True, "summary": summaries,
    }


if __name__ == "__main__":
    print(json.dumps(reference_report(), indent=2, sort_keys=True))
