"""Research-only joint Bayesian information purchase + four-modality allocation.

This finite, auditable pilot does not use natural pretrained media, real-world
witness evidence, production authority, identified preferences or a neural FBSDE.
The controller sees only public posterior, observed synthetic generation levels,
remaining modeled budget, time and activation state. Truth is private to scorer.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from typing import Callable

from portfolio import (
    Allocation, Config, Decoded, SHOCK_PROBS, State, actions, advance,
    charge, conditional_ce, decode_all, decoded_external_loss, feasible,
)
from information_acquisition import (
    WITNESS_ACCURACY, all_outputs, map_label, posterior,
    prior_from_public, score_raw_outputs, witness_probability,
)

QUERY = "QUERY_INDEPENDENT"
EMIT = "EMIT_ALL_FOUR"
SHOCK_EXACT = (Fraction(1, 5), Fraction(1, 4), Fraction(11, 20))
FACT_ERROR_PER_FOUR = 4


@dataclass(frozen=True)
class JointState:
    generation: State
    p_zero: Fraction
    witness_seen: bool = False

    def __post_init__(self) -> None:
        if (type(self.p_zero) is not Fraction
            or not Fraction(0) <= self.p_zero <= Fraction(1)
            or type(self.witness_seen) is not bool):
            raise ValueError("unsupported public belief-state")


def admitted_actions(s: JointState, cfg: Config, *, allow_query: bool = True,
                     query_cost: int = 1) -> tuple[str | Allocation, ...]:
    if type(query_cost) is not int or query_cost < 1:
        raise ValueError("unadmitted information cost")
    options: list[str | Allocation] = [EMIT]
    if (allow_query and not s.witness_seen and s.generation.step < cfg.horizon
        and s.generation.remaining >= cfg.emission_reserve + query_cost):
        options.append(QUERY)
    options.extend(action for action in actions(s.generation, cfg) if not action.stop)
    return tuple(options)


def query_successor(s: JointState, cfg: Config, observed: int,
                    query_cost: int = 1) -> JointState:
    if QUERY not in admitted_actions(s, cfg, query_cost=query_cost):
        raise ValueError("query not feasible under exact physical reserve")
    if type(observed) is not int or observed not in (0, 1):
        raise ValueError("invalid independent witness observation")
    g = s.generation
    return JointState(
        State(g.levels, g.remaining - query_cost, g.step + 1, g.active_mask),
        posterior(s.p_zero, observed), True,
    )


def generation_successor(s: JointState, a: Allocation, shock: int,
                         cfg: Config) -> JointState:
    if not isinstance(a, Allocation) or a.stop or not feasible(s.generation, a, cfg):
        raise ValueError("invalid generation portfolio")
    return JointState(advance(s.generation, a, shock, cfg),
                      s.p_zero, s.witness_seen)


def terminal_value(s: JointState, cfg: Config) -> float:
    """Registered conditional terminal utility; hidden truth is not observed."""
    if s.generation.remaining < cfg.emission_reserve:
        raise ValueError("unfunded four-output emission")
    predicted = map_label(s.p_zero)
    quality_loss = decoded_external_loss(decode_all(s.generation), cfg.sync_penalty)
    base = -quality_loss - cfg.cost_shadow_price * cfg.emission_reserve
    return conditional_ce(
        (base - FACT_ERROR_PER_FOUR * (predicted != 0),
         base - FACT_ERROR_PER_FOUR * (predicted != 1)),
        (float(s.p_zero), float(1 - s.p_zero)), cfg.risk_aversion,
    )


class JointController:
    """Exact finite conditional entropic Bellman controller, research only."""

    def __init__(self, cfg: Config, *, allow_query: bool = True,
                 query_cost: int = 1, max_states: int = 16_384):
        if (type(allow_query) is not bool or type(query_cost) is not int
            or query_cost < 1 or type(max_states) is not int
            or not 1 <= max_states <= 250_000):
            raise ValueError("unadmitted joint control options")
        self.cfg = cfg
        self.allow_query = allow_query
        self.query_cost = query_cost
        self.max_states = max_states
        # Local to the owner instance: no shared global memo across episodes.
        self._memo: dict[JointState, tuple[str | Allocation, float]] = {}
        self._state_evaluations = 0
        self._candidate_evaluations = 0

    def resource_receipt(self) -> dict:
        # Algorithmic work units, NOT physical wall/CPU/energy measurements.
        return {"visited_states": self._state_evaluations,
                "compared_actions": self._candidate_evaluations,
                "cached_states": len(self._memo),
                "max_states": self.max_states,
                "units": "logical_bellman_evaluations_not_physical_cost"}

    def solve(self, s: JointState) -> tuple[str | Allocation, float]:
        if s.generation.step > self.cfg.horizon:
            raise ValueError("generation horizon exceeded")
        previous = self._memo.get(s)
        if previous is not None:
            return previous
        if self._state_evaluations >= self.max_states:
            raise RuntimeError("joint NDU solver state budget exceeded")
        self._state_evaluations += 1
        candidates = admitted_actions(s, self.cfg,
                                      allow_query=self.allow_query,
                                      query_cost=self.query_cost)
        self._candidate_evaluations += len(candidates)
        best, best_value = EMIT, terminal_value(s, self.cfg)
        for action in candidates[1:]:
            if action == QUERY:
                branch_values = tuple(self.solve(query_successor(
                    s, self.cfg, obs, self.query_cost))[1] for obs in (0, 1))
                branch_probs = tuple(float(witness_probability(s.p_zero, obs))
                                     for obs in (0, 1))
                paid = self.query_cost
            else:
                assert isinstance(action, Allocation)
                branch_values = tuple(self.solve(generation_successor(
                    s, action, shock, self.cfg))[1] for shock in (0, 1, 2))
                branch_probs = SHOCK_PROBS
                paid = charge(s.generation, action, self.cfg)
            value = (-self.cfg.cost_shadow_price * paid
                     + conditional_ce(branch_values, branch_probs,
                                      self.cfg.risk_aversion))
            if value > best_value + 1e-12:
                best, best_value = action, value
        self._memo[s] = (best, best_value)
        return best, best_value


def materialize_four(s: JointState) -> dict:
    """Four separately materialized toy media with the same posterior-based claim."""
    label = map_label(s.p_zero)
    claims = all_outputs(label)
    render = decode_all(s.generation)
    return {
        "text": {"claim": claims["text"], "render": render.text},
        "audio": {"claim": claims["audio"], "render": render.audio},
        "image": {"claim": claims["image"], "render": render.image},
        "video": {"claim": claims["video"], "render": render.video},
    }


def independent_fixture_score(raw: dict, truth: int, cfg: Config) -> int:
    """Separate terminal scorer; the controller NEVER receives truth or its loss."""
    if type(raw) is not dict or set(raw) != {"text", "audio", "image", "video"}:
        raise ValueError("missing required raw modality")
    if any(type(raw[k]) is not dict or set(raw[k]) != {"claim", "render"}
           for k in raw):
        raise ValueError("malformed raw output material")
    facts = {key: raw[key]["claim"] for key in raw}
    quality = Decoded(*(raw[key]["render"]
                        for key in ("text", "audio", "image", "video")))
    fact_wrong = score_raw_outputs(facts, truth)
    return (FACT_ERROR_PER_FOUR * fact_wrong
            + decoded_external_loss(quality, cfg.sync_penalty))


def full_outcome_audit(initial: JointState, cfg: Config,
                       choose: Callable[[JointState], str | Allocation],
                       *, query_cost: int = 1,
                       witness_channel: str = "declared_independent") -> dict:
    """Externally enumerate truth, witness, joint shocks and actual emitted loss.

    The law is small and exact: each event's probability uses Fractions. Truth
    is used to draw witness likelihoods and independently score terminal media;
    it is not passed into the policy's observation/state object.
    """
    if initial.generation.step != 0 or initial.generation.remaining < cfg.emission_reserve:
        raise ValueError("invalid first decision boundary")
    if type(query_cost) is not int or query_cost < 1:
        raise ValueError("invalid query budget")
    if witness_channel not in ("declared_independent", "shared_report_zero"):
        raise ValueError("unregistered external witness law")
    rows: list[tuple[Fraction, int, int, bool, int, str]] = []
    # A policy supplied to this scorer is part of the observed-source claim.
    # A changing or history/hidden-truth-dependent callback can otherwise
    # declare one first_action, execute another, and launder the discrepancy
    # into a perfectly normalized outcome/cost receipt. Markov actions must be
    # reproducible from the same *public* JointState across every truth path.
    observed_actions: dict[JointState, str | Allocation] = {}

    def observed_policy_action(s: JointState) -> str | Allocation:
        action = choose(s)
        if s in observed_actions and observed_actions[s] != action:
            raise ValueError("non-deterministic public-state policy replay")
        observed_actions[s] = action
        return action

    action_at_initial = observed_policy_action(initial)

    def visit(s: JointState, truth: int, probability: Fraction, spent: int,
              ever_queried: bool, generator_calls: int):
        if not probability:
            return
        action = observed_policy_action(s)
        if action == EMIT:
            raw = materialize_four(s)
            loss = independent_fixture_score(raw, truth, cfg)
            paid = spent + cfg.emission_reserve
            if spent != initial.generation.remaining - s.generation.remaining:
                raise AssertionError("modeled cost and transition budget disagree")
            if paid > initial.generation.remaining:
                raise AssertionError("actual execution overdrew the physical budget")
            digest = hashlib.sha256(json.dumps(
                raw, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            rows.append((probability, loss, paid, ever_queried, generator_calls, digest))
            return
        if action == QUERY:
            if QUERY not in admitted_actions(s, cfg, query_cost=query_cost):
                raise ValueError("unfunded or repeated witness query")
            for obs in (0, 1):
                likelihood = ((WITNESS_ACCURACY if obs == truth else 1 - WITNESS_ACCURACY)
                              if witness_channel == "declared_independent"
                              else Fraction(int(obs == 0)))
                visit(query_successor(s, cfg, obs, query_cost), truth,
                      probability * likelihood, spent + query_cost,
                      True, generator_calls)
            return
        if (not isinstance(action, Allocation) or action.stop
            or not feasible(s.generation, action, cfg)):
            raise ValueError("illegal or incomplete generation control")
        paid = charge(s.generation, action, cfg)
        for shock, p_shock in enumerate(SHOCK_EXACT):
            visit(generation_successor(s, action, shock, cfg), truth,
                  probability * p_shock, spent + paid,
                  ever_queried, generator_calls + 1)

    for truth, p in ((0, initial.p_zero), (1, 1 - initial.p_zero)):
        visit(initial, truth, p, 0, False, 0)
    if not rows or sum(row[0] for row in rows) != 1:
        raise AssertionError("incomplete independently enumerated outcome law")
    probs = tuple(float(row[0]) for row in rows)
    losses = [row[1] for row in rows]
    costs = [row[2] for row in rows]
    values = tuple(-loss - cfg.cost_shadow_price * paid
                   for loss, paid in zip(losses, costs))
    # Use exact fractional tail mass, not ceil(10% of number of rows).
    tail = Fraction(1, 10)
    tail_numerator = Fraction(0)
    for weight, loss in sorted(((r[0], r[1]) for r in rows),
                               key=lambda row: row[1], reverse=True):
        take = min(tail, weight)
        tail_numerator += take * loss
        tail -= take
        if not tail:
            break
    if tail:
        raise AssertionError("insufficient tail mass")
    return {
        "scope": "RESEARCH_ONLY_SHADOW_DENY_ALL",
        "witness_channel": witness_channel,
        "unmodeled_channel_shift_has_no_robustness_guarantee": True,
        "outcomes": len(rows),
        "first_action": (action_at_initial.units if isinstance(action_at_initial, Allocation)
                         else action_at_initial),
        "recursive_fullpath_utility": conditional_ce(values, probs, cfg.risk_aversion),
        "mean_external_loss": float(sum(p * loss for p, loss, *_ in rows)),
        "cvar90_external_loss": float(tail_numerator / Fraction(1, 10)),
        "mean_modeled_cost": float(sum(p * paid for p, _, paid, *_ in rows)),
        "query_probability": float(sum(p for p, _, _, query, *_ in rows if query)),
        "mean_generator_calls": float(sum(p * n for p, _, _, _, n, _ in rows)),
        "four_outputs_emitted": True,
        "budget_violations": 0,
        "distinct_decoded_hashes": len({row[5] for row in rows}),
    }


def mode_state(mode: str, levels: tuple[int, int, int, int],
               budget: int) -> JointState:
    return JointState(State(levels, budget), prior_from_public(mode))
