"""NDU-DMGP shadow-only, dependency-free reference: no model/effect authority.

This is a bounded deterministic research implementation, NOT a production NDU
solver, neural decoder, authenticated observer or evidence of learned efficacy.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
from math import atan2, cos, factorial, isfinite, log, sin, sqrt
from statistics import mean, stdev
from typing import Mapping
import json


class Unavailable(ValueError):
    """Insufficient support, identity drift or hard infeasibility; fail closed."""


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Unavailable(message)


def finite(*values: float) -> bool:
    return all(isfinite(v) for v in values)


@dataclass(frozen=True)
class Freeze:
    objective: str
    generation: int
    actor: str
    critic: str
    observer: str
    critic_digest: str
    feature_digest: str

    def validate(self) -> None:
        require(self.objective and self.generation > 0, "unbound objective/generation")
        require(all((self.actor, self.critic, self.observer, self.critic_digest,
                     self.feature_digest)), "missing identity/digest")
        require(len({self.actor, self.critic, self.observer}) == 3,
                "actor, critic and outcome observer must be distinct")


@dataclass(frozen=True)
class Outcome:
    episode: str
    arm: str
    objective: str
    generation: int
    observer: str
    actor: str
    critic_digest: str
    source_digest: str
    split: str
    observed_utility: float
    decoder_us: int
    controller_us: int
    verifier_us: int
    work_key: str
    behavior_propensity: float = 1.0

    def validate(self, freeze: Freeze) -> None:
        freeze.validate()
        require(self.objective == freeze.objective and self.generation == freeze.generation,
                "objective/generation drift")
        require(self.observer == freeze.observer and self.actor == freeze.actor
                and self.critic_digest == freeze.critic_digest, "identity/critic drift")
        require(self.episode and self.arm and self.source_digest and self.work_key,
                "incomplete provenance")
        require(self.split in {"train", "future"}, "undeclared split")
        require(finite(self.observed_utility) and -1 <= self.observed_utility <= 1,
                "unbounded observed utility")
        require(finite(self.behavior_propensity)
                and 0 < self.behavior_propensity <= 1,
                "unbound behavior propensity")
        require(min(self.decoder_us, self.controller_us, self.verifier_us) >= 0,
                "invalid physical cost")

    @property
    def total_us(self) -> int:
        return self.decoder_us + self.controller_us + self.verifier_us


def paired_future_evaluation(rows: tuple[Outcome, ...], freeze: Freeze,
                             baseline: str, candidate: str, cost_per_us: float,
                             min_episodes: int = 20) -> tuple[float, float, int]:
    """Conservative paired future-split LCB; independent evidence is REQUIRED.

    This 2.5-SE exploratory bound is not a distribution-free confidence guarantee.
    A production gate must use the repository's registered future-window profile.
    """
    require(min_episodes >= 20, "cannot lower preregistered future support")
    require(finite(cost_per_us) and cost_per_us >= 0, "invalid cost scalarization")
    groups: dict[str, dict[str, Outcome]] = {}
    work: set[str] = set()
    for r in rows:
        r.validate(freeze)
        require(r.split == "future", "train/outcome leakage")
        require(r.work_key not in work, "physical work double counted")
        work.add(r.work_key)
        arm = groups.setdefault(r.episode, {})
        require(r.arm not in arm, "duplicate episode/arm")
        arm[r.arm] = r
    require(len(groups) >= max(2, min_episodes), "too few independent future episodes")
    deltas = []
    for episode, arms in groups.items():
        require(set(arms) == {baseline, candidate}, f"unpaired/extra arm: {episode}")
        b, c = arms[baseline], arms[candidate]
        require(b.source_digest == c.source_digest, "unmatched input across arms")
        deltas.append(c.observed_utility - b.observed_utility - cost_per_us *
                      (c.total_us - b.total_us))
    avg = mean(deltas)
    lcb = avg - 2.5 * stdev(deltas) / sqrt(len(deltas))
    return avg, lcb, len(deltas)


@dataclass(frozen=True)
class Claim:
    modality: str
    event: str
    entity: str
    start_ms: int
    end_ms: int
    evidence_digest: str
    observer: str


@dataclass(frozen=True)
class SemanticPlan:
    # Each required modality must independently cover every declared event.
    modalities: tuple[str, ...]
    events: tuple[tuple[str, str, int, int], ...]
    tolerance_ms: int


def verify_cross_modal(plan: SemanticPlan, claims: tuple[Claim, ...],
                       freeze: Freeze) -> str:
    """Forward coverage AND reverse no-extra-claim validation.

    Claims must be extracted by an independent observer; a matching tag alone
    does not establish pixel/audio semantic truth in this synthetic reference.
    """
    freeze.validate()
    require(plan.modalities and len(set(plan.modalities)) == len(plan.modalities)
            and plan.events and plan.tolerance_ms >= 0, "invalid plan")
    expected: dict[str, tuple[str, int, int]] = {}
    prior_end = -1
    for event, entity, start, end in plan.events:
        require(event and entity and start >= prior_end and end > start
                and event not in expected, "invalid/noncanonical plan event")
        expected[event] = (entity, start, end)
        prior_end = end
    seen = set()
    bound_claims = []
    by_event: dict[str, list[tuple[int, int]]] = {}
    for claim in claims:
        require(claim.modality in plan.modalities and claim.event in expected,
                "reverse audit: hallucinated modality/event")
        require(claim.observer == freeze.observer and claim.evidence_digest,
                "untrusted/unbound observer")
        key = (claim.modality, claim.event)
        require(key not in seen, "duplicate claim")
        seen.add(key)
        bound_claims.append((claim.modality, claim.event, claim.entity,
                             claim.start_ms, claim.end_ms, claim.observer,
                             claim.evidence_digest))
        by_event.setdefault(claim.event, []).append((claim.start_ms, claim.end_ms))
        entity, start, end = expected[claim.event]
        require(claim.entity == entity and claim.start_ms >= 0
                and claim.end_ms > claim.start_ms, "entity/timeline conflict")
        require(abs(claim.start_ms - start) <= plan.tolerance_ms
                and abs(claim.end_ms - end) <= plan.tolerance_ms,
                "temporal alignment violation")
    required = set(product(plan.modalities, expected))
    require(seen == required, "forward audit: missing modality/event")
    for bounds in by_event.values():
        require(max(v[0] for v in bounds) - min(v[0] for v in bounds)
                <= plan.tolerance_ms
                and max(v[1] for v in bounds) - min(v[1] for v in bounds)
                <= plan.tolerance_ms, "cross-modal pairwise time drift")
    return digest({"plan": plan.events, "modalities": plan.modalities,
                   "tolerance_ms": plan.tolerance_ms,
                   "claims": sorted(bound_claims),
                   "objective": freeze.objective,
                   "feature_digest": freeze.feature_digest,
                   "generation": freeze.generation})


@dataclass(frozen=True)
class JointSample:
    episode: str
    context: str
    objective: str
    observer: str
    # One actual paired score per candidate on the same independently evaluated
    # input; NOT fabricated counterfactual returns from a model's own critic.
    returns: tuple[float, ...]


@dataclass(frozen=True)
class RiskEstimate:
    means: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    sample_count: int
    context: str
    condition_upper: float
    rank_retained: int


def cholesky(a: list[list[float]], floor: float = 1e-10) -> list[list[float]]:
    n = len(a)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            v = a[i][j] - sum(out[i][k] * out[j][k] for k in range(j))
            if i == j:
                require(v > floor, "rank-deficient or ill-conditioned covariance")
                out[i][j] = sqrt(v)
            else:
                out[i][j] = v / out[j][j]
    return out


def joint_covariance(samples: tuple[JointSample, ...], freeze: Freeze,
                     expected_context: str, shrink: float = 0.2,
                     max_condition: float = 1e6) -> RiskEstimate:
    freeze.validate()
    require(0 <= shrink <= 1 and 1 < max_condition < float("inf"),
            "invalid numeric profile")
    require(samples and samples[0].returns, "missing joint returns")
    k = len(samples[0].returns)
    require(1 <= k <= 6 and len(samples) >= max(20, 5 * k),
            "insufficient independent paired joint samples")
    seen = set()
    for s in samples:
        require(s.episode and s.episode not in seen, "duplicate joint episode")
        seen.add(s.episode)
        require(s.context == expected_context and s.objective == freeze.objective
                and s.observer == freeze.observer, "conditional source drift")
        require(len(s.returns) == k and finite(*s.returns), "missing/nonfinite joint return")
        require(all(-1 <= v <= 1 for v in s.returns), "unbounded reward")
    mus = tuple(mean(s.returns[i] for s in samples) for i in range(k))
    raw = [[sum((s.returns[i] - mus[i]) * (s.returns[j] - mus[j])
                for s in samples) / (len(samples) - 1) for j in range(k)] for i in range(k)]
    # Raw support MUST pass before regularization; ridge must never manufacture
    # identifiability for exactly collinear/constant observations.
    cholesky(raw)
    diagonal = [raw[i][i] for i in range(k)]
    condition_upper = max(diagonal) / min(diagonal)
    require(condition_upper <= max_condition, "unsupported variance scale")
    cov = [[(1 - shrink) * raw[i][j] + (shrink * raw[i][i] if i == j else 0.0)
            for j in range(k)] for i in range(k)]
    chol = cholesky(cov)
    pivots = [chol[i][i] ** 2 for i in range(k)]
    condition_upper = max(condition_upper, max(pivots) / min(pivots))
    require(condition_upper <= max_condition, "covariance condition ceiling")
    return RiskEstimate(mus, tuple(tuple(row) for row in cov), len(samples),
                        expected_context, condition_upper, k)


def low_rank_diagonal(risk: RiskEstimate, rank: int,
                      max_relative_residual: float = 0.5) -> RiskEstimate:
    """Numerically bounded symmetric eigentruncation plus diagonal residual.

    Factor reduction is valid only when held-out factor-adequacy review and
    covariance support pass. This diagnostic is not an identifiability proof.
    """
    k = len(risk.means)
    require(0 <= rank <= k and 0 <= max_relative_residual <= 1,
            "invalid factor profile")
    if rank == k:
        return risk
    a = [list(row) for row in risk.covariance]
    eigvec = [[float(i == j) for j in range(k)] for i in range(k)]
    for _ in range(100 * k * k):
        p, q = max(((i, j) for i in range(k) for j in range(i + 1, k)),
                   key=lambda pair: abs(a[pair[0]][pair[1]]), default=(0, 0))
        if abs(a[p][q]) < 1e-11:
            break
        angle = 0.5 * atan2(2 * a[p][q], a[q][q] - a[p][p])
        c, sn = cos(angle), sin(angle)
        # Rotate columns of the symmetric matrix, then rows; also rotate
        # eigenvector columns. The resulting eigenvectors are orthonormal.
        for i in range(k):
            aip, aiq = a[i][p], a[i][q]
            a[i][p], a[i][q] = c * aip - sn * aiq, sn * aip + c * aiq
        for j in range(k):
            apj, aqj = a[p][j], a[q][j]
            a[p][j], a[q][j] = c * apj - sn * aqj, sn * apj + c * aqj
        for i in range(k):
            vip, viq = eigvec[i][p], eigvec[i][q]
            eigvec[i][p], eigvec[i][q] = c * vip - sn * viq, sn * vip + c * viq
    order = sorted(range(k), key=lambda j: a[j][j], reverse=True)
    require(all(a[j][j] > -1e-9 for j in order), "indefinite eigenmode")
    factor = [[sum(max(0.0, a[t][t]) * eigvec[i][t] * eigvec[j][t]
                   for t in order[:rank]) for j in range(k)] for i in range(k)]
    residual = [risk.covariance[i][i] - factor[i][i] for i in range(k)]
    require(all(v >= -1e-9 for v in residual), "negative diagonal residual")
    approx = [[factor[i][j] + (max(0.0, residual[i]) if i == j else 0.0)
               for j in range(k)] for i in range(k)]
    denom = sqrt(sum(v * v for row in risk.covariance for v in row))
    err = sqrt(sum((approx[i][j] - risk.covariance[i][j]) ** 2
                   for i in range(k) for j in range(k))) / max(denom, 1e-12)
    require(err <= max_relative_residual, "factor approximation not supported")
    cholesky(approx)
    return RiskEstimate(risk.means, tuple(tuple(row) for row in approx),
                        risk.sample_count, risk.context, risk.condition_upper, rank)


@dataclass(frozen=True)
class Action:
    name: str
    modality: str
    work_us: int
    legal: bool = True


@dataclass(frozen=True)
class Allocation:
    weights: tuple[float, ...]
    value: float
    variance: float
    profile: str


def allocate(actions: tuple[Action, ...], risk: RiskEstimate | None,
             budget_us: int, risk_aversion: float, kl_weight: float,
             reference_weights: tuple[float, ...], step: float = 0.25) -> Allocation:
    """Finite-grid Merton-style approximation: weights are route probabilities.

    Never linearly interpolate incompatible output tensors. Deterministic shadow
    fallback picks a cheapest admissible action when joint covariance is absent.
    """
    require(actions and len(actions) <= 6 and budget_us >= 0, "invalid action/budget")
    require(finite(risk_aversion, kl_weight, step) and risk_aversion >= 0
            and kl_weight >= 0 and 0 < step <= 1, "invalid preference profile")
    require(len(reference_weights) == len(actions) and
            all(v > 0 and finite(v) for v in reference_weights)
            and abs(sum(reference_weights) - 1) < 1e-8, "invalid reference weights")
    legal = [i for i, a in enumerate(actions)
             if a.legal and a.work_us >= 0 and a.work_us <= budget_us]
    require(legal, "no feasible generated action: abstain required")
    if risk is None:
        selected = min(legal, key=lambda i: (actions[i].work_us, actions[i].name))
        return Allocation(tuple(float(i == selected) for i in range(len(actions))),
                          0.0, 0.0, "deterministic-fallback")
    require(len(risk.means) == len(actions), "candidate/covariance dimensional drift")
    require(abs(1 / step - round(1 / step)) < 1e-8 and 1 / step <= 20,
            "noncanonical finite grid")
    n = round(1 / step)
    best: Allocation | None = None
    for parts in product(range(n + 1), repeat=len(legal)):
        if sum(parts) != n:
            continue
        w = [0.0] * len(actions)
        for i, units in zip(legal, parts):
            w[i] = units / n
        expected = sum(w[i] * risk.means[i] for i in range(len(actions)))
        variance = sum(w[i] * w[j] * risk.covariance[i][j]
                       for i in range(len(actions)) for j in range(len(actions)))
        require(variance >= -1e-8, "non PSD covariance")
        kl = sum(w[i] * log(w[i] / reference_weights[i])
                 for i in range(len(actions)) if w[i] > 0)
        score = expected - 0.5 * risk_aversion * max(0.0, variance) - kl_weight * kl
        row = Allocation(tuple(w), score, max(0.0, variance), "risk-adjusted-grid")
        if best is None or row.value > best.value + 1e-12 or (
                abs(row.value - best.value) <= 1e-12 and row.weights < best.weights):
            best = row
    require(best is not None, "no allocation")
    return best


@dataclass(frozen=True)
class GenerationState:
    generation: int
    budget_us: int
    remaining_steps: int
    # Small validated state for the shadow recursion, NOT an assertion of
    # sufficiency for multimodal pixels/tokens/audio traces.
    quality: float


def recursive_stop_choice(state: GenerationState, actions: tuple[Action, ...],
                          predicted_gains: Mapping[str, float],
                          continuation_discount: float = 0.95,
                          cost_per_us: float = 0.0,
                          risk_penalty: Mapping[str, float] | None = None,
                          pair_gain: Mapping[frozenset[str], float] | None = None) -> tuple[str, float]:
    """Bounded finite-horizon stopping/continuation Bellman reference.

    Real full stochastic NDU-FBSDE requires qualified owner solver and dynamics;
    this deterministic surrogate never claims to be that solver.
    """
    require(state.generation > 0 and state.budget_us >= 0
            and 0 <= state.remaining_steps <= 8 and finite(state.quality),
            "invalid state")
    require(0 <= continuation_discount <= 1 and cost_per_us >= 0,
            "invalid continuation profile")
    legal = [a for a in actions if a.legal and a.work_us <= state.budget_us
             and a.work_us >= 0 and a.name in predicted_gains]
    require(all(finite(v) for v in predicted_gains.values()), "invalid advantage")
    penalties = risk_penalty or {}
    interactions = pair_gain or {}
    require(all(finite(v) and v >= 0 for v in penalties.values()), "invalid risk")
    require(all(len(pair) == 2 and finite(v) for pair, v in interactions.items()),
            "invalid joint interaction")
    require(len({a.name for a in legal}) == len(legal), "duplicate generation action")

    def solve(budget: int, remaining: int, quality: float,
              options: tuple[Action, ...],
              visited: frozenset[str]) -> tuple[str, float]:
        choice, value = "stop", quality
        if remaining <= 0:
            return choice, value
        for action in options:
            if action.work_us > budget:
                continue
            gain = predicted_gains[action.name] + sum(
                interactions.get(frozenset((action.name, previous)), 0.0)
                for previous in visited)
            successor = tuple(a for a in options if a.name != action.name)
            _, continuation = solve(budget - action.work_us, remaining - 1,
                                    quality + gain, successor,
                                    visited | {action.name})
            score = -(cost_per_us * action.work_us
                      + penalties.get(action.name, 0.0)) + continuation_discount * continuation
            if score > value + 1e-12:
                choice, value = action.name, score
        return choice, value
    return solve(state.budget_us, state.remaining_steps, state.quality,
                 tuple(legal), frozenset())


@dataclass(frozen=True)
class LearningProposal:
    current_generation: int
    candidate_generation: int
    actor: str
    evaluator: str
    critic_digest: str
    kl_divergence: float
    update_norm: float
    future_candidate_lcb: float
    future_baseline_ucb: float
    old_task_degradation: float


def qualify_next_snapshot(row: LearningProposal, freeze: Freeze,
                          max_kl: float = 0.05,
                          max_update_norm: float = 0.1) -> str:
    freeze.validate()
    require(row.current_generation == freeze.generation
            and row.candidate_generation > row.current_generation,
            "current-generation mutation")
    require(row.actor == freeze.actor and row.evaluator == freeze.observer
            and row.critic_digest == freeze.critic_digest, "unfrozen critic/evaluator")
    require(finite(row.kl_divergence, row.update_norm, row.future_candidate_lcb,
                   row.future_baseline_ucb, row.old_task_degradation), "nonfinite gate")
    require(0 <= row.kl_divergence <= max_kl
            and 0 <= row.update_norm <= max_update_norm, "trust region violated")
    require(row.future_candidate_lcb > row.future_baseline_ucb,
            "no independent future-window improvement")
    require(row.old_task_degradation >= -0.02, "old task retention gate")
    return "shadow-qualified-next-snapshot-only"


def global_credit(coalitions: Mapping[frozenset[str], float],
                  cells: tuple[str, ...], observer: str, freeze: Freeze,
                  randomized: bool, min_support: int,
                  max_interaction: float = 0.1) -> dict[str, float]:
    """Exact coalition Shapley allocation, not automatically causal credit."""
    freeze.validate()
    require(observer == freeze.observer and randomized and min_support >= 20,
            "unidentified intervention/observer support")
    require(0 <= max_interaction <= 0.1, "unregistered interaction tolerance")
    n = len(cells)
    require(1 <= n <= 4 and len(set(cells)) == n, "invalid bounded coalition")
    require(set(coalitions) == {frozenset(cells[i] for i in range(n) if mask & (1 << i))
                                for mask in range(1 << n)}, "incomplete joint counterfactuals")
    require(all(finite(v) for v in coalitions.values()), "nonfinite coalition utility")
    empty = coalitions[frozenset()]
    grand = coalitions[frozenset(cells)]
    singles = sum(coalitions[frozenset((c,))] - empty for c in cells)
    require(abs((grand - empty) - singles) <= max_interaction,
            "strong interaction: no independent per-Cell advantage")
    out = {}
    for cell in cells:
        others = [c for c in cells if c != cell]
        result = 0.0
        for mask in range(1 << len(others)):
            subset = frozenset(c for i, c in enumerate(others) if mask & (1 << i))
            weight = factorial(len(subset)) * factorial(n - len(subset) - 1) / factorial(n)
            result += weight * (coalitions[subset | {cell}] - coalitions[subset])
        out[cell] = result
    require(abs(sum(out.values()) - (grand - empty)) < 1e-8,
            "global-to-local utility conservation")
    return out


@dataclass(frozen=True)
class WorkReceipt:
    case_id: str
    physical_work_key: str
    decoder_us: int
    controller_us: int
    verifier_us: int
    peak_rss_bytes: int
    measured_on_host: bool


def compare_work(baseline: tuple[WorkReceipt, ...], candidate: tuple[WorkReceipt, ...]) -> dict[str, float | bool]:
    """Measured physical work; no synthetic data can pass production gate."""
    require(baseline and candidate and len(baseline) == len(candidate), "unpaired resource data")
    bmap, cmap = {}, {}
    work_ids: set[str] = set()
    for bucket, rows in ((bmap, baseline), (cmap, candidate)):
        for r in rows:
            require(r.case_id and r.case_id not in bucket, "duplicate paired episode")
            require(r.physical_work_key and r.physical_work_key not in work_ids,
                    "duplicate physical work")
            work_ids.add(r.physical_work_key)
            require(min(r.decoder_us, r.controller_us, r.verifier_us,
                        r.peak_rss_bytes) >= 0, "invalid metric")
            bucket[r.case_id] = r
    require(set(bmap) == set(cmap), "unmatched physical execution")
    btimes = sorted(r.decoder_us + r.controller_us + r.verifier_us for r in baseline)
    ctimes = sorted(r.decoder_us + r.controller_us + r.verifier_us for r in candidate)
    p95idx = max(0, (len(btimes) * 95 + 99) // 100 - 1)
    saved_decoder = sum(bmap[k].decoder_us - cmap[k].decoder_us for k in bmap)
    extra_controller = sum(cmap[k].controller_us - bmap[k].controller_us for k in bmap)
    measured = all(r.measured_on_host for r in baseline + candidate)
    return {"baseline_p95_us": float(btimes[p95idx]),
            "candidate_p95_us": float(ctimes[p95idx]),
            "decoder_saved_us": float(saved_decoder),
            "extra_controller_us": float(extra_controller),
            "peak_rss_bytes": float(max(r.peak_rss_bytes for r in candidate)),
            "unverified_host_metric_candidate": measured and saved_decoder > extra_controller
            and ctimes[p95idx] < btimes[p95idx],
            # Boolean caller declarations cannot authenticate a hardware host.
            "production_efficiency_evidence": False}


def closure_audit(train: tuple[tuple[float, float, float], ...],
                  future: tuple[tuple[float, float, float], ...],
                  min_rows: int = 20, max_relative_gain: float = 0.05) -> dict[str, float | bool]:
    """Tests whether omitted history predicts next outcome beyond summary.

    Tuples are (compressed-state scalar, history scalar, next observed reward).
    Train fits linear least squares with ridge fixed BEFORE future validation.
    Only a small specified diagnostic; never proof of Markov sufficiency.
    """
    require(len(train) >= min_rows and len(future) >= min_rows,
            "too little independent train/future closure evidence")
    require(0 <= max_relative_gain <= 1 and all(finite(*r) for r in train + future),
            "invalid closure profile")

    def fit(include_history: bool) -> tuple[float, ...]:
        dim = 3 if include_history else 2
        matrix = [[0.0] * dim for _ in range(dim)]
        target = [0.0] * dim
        for x, h, y in train:
            v = (1.0, x, h) if include_history else (1.0, x)
            for i in range(dim):
                target[i] += v[i] * y
                for j in range(dim):
                    matrix[i][j] += v[i] * v[j]
        for i in range(dim):
            matrix[i][i] += 1e-6
        for col in range(dim):
            pivot = max(range(col, dim), key=lambda k: abs(matrix[k][col]))
            require(abs(matrix[pivot][col]) > 1e-12, "singular closure regressor")
            matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
            target[col], target[pivot] = target[pivot], target[col]
            scale = matrix[col][col]
            for j in range(col, dim):
                matrix[col][j] /= scale
            target[col] /= scale
            for row in range(dim):
                if row == col:
                    continue
                scale = matrix[row][col]
                for j in range(col, dim):
                    matrix[row][j] -= scale * matrix[col][j]
                target[row] -= scale * target[col]
        return tuple(target)

    def mse(coef: tuple[float, ...]) -> float:
        return mean((y - sum(a * b for a, b in zip(coef, (1.0, x, h)))) ** 2
                    for x, h, y in future)

    coarse = mse(fit(False))
    extended = mse(fit(True))
    gain = max(0.0, coarse - extended) / max(coarse, 1e-12)
    return {"coarse_mse": coarse, "history_mse": extended,
            "history_gain": gain, "closure_not_rejected": gain <= max_relative_gain}
