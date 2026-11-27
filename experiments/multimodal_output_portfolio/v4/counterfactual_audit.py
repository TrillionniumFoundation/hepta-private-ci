"""Independent full-path counterfactual evaluation of the v4 finite controller.

RESEARCH_ONLY / DENY_ALL. This enumerates every joint synthetic shock path,
materializes all four toy outputs, scores them AFTER emission and charges
activations and all mandatory decoders. It is not natural model evaluation.
"""
from __future__ import annotations

from itertools import product
import math
from typing import Callable

from portfolio import (
    Allocation, Config, Controller, SHOCK_PROBS, STOP, State,
    advance, charge, conditional_ce, decode_all,
    decoded_external_loss, feasible,
)


def check_joint_law(law: tuple[float, float, float]) -> None:
    if (type(law) is not tuple or len(law) != 3
        or any(type(p) not in (int, float) or not math.isfinite(p) or p < 0
               for p in law)
        or not math.isclose(math.fsum(law), 1.0, rel_tol=0, abs_tol=1e-12)):
        raise ValueError("invalid joint shock law")


def scenarios(horizon: int, law: tuple[float, float, float]):
    check_joint_law(law)
    if type(horizon) is not int or not 1 <= horizon <= 3:
        raise ValueError("unadmitted enumeration horizon")
    for path in product(range(3), repeat=horizon):
        probability = math.prod(law[shock] for shock in path)
        # A positive supported path must not disappear from the tail audit.
        # Zero factors are impossible events; positive products rounded to zero
        # exceed this float enumerator's domain and must fail closed instead.
        if probability == 0 and all(law[shock] > 0 for shock in path):
            raise ValueError("positive path probability underflow")
        if probability > 0:
            yield path, probability


def check_dependence_regime(regime) -> None:
    if type(regime) is not tuple or not 1 <= len(regime) <= 8:
        raise ValueError("unregistered joint dependence regime")
    seen = set()
    total = 0.0
    for row in regime:
        if type(row) is not tuple or len(row) != 2:
            raise ValueError("malformed joint dependence row")
        shock, probability = row
        if (type(shock) is not tuple or len(shock) != 4
            or any(type(k) is not int or k not in (0, 1, 2) for k in shock)
            or shock in seen or type(probability) not in (int, float)
            or not math.isfinite(probability) or probability < 0):
            raise ValueError("invalid joint dependence law")
        seen.add(shock)
        total += probability
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-12):
        raise ValueError("invalid joint dependence normalization")


def advance_joint(state: State, action: Allocation,
                  innovation: tuple[int, int, int, int], cfg: Config) -> State:
    if (type(innovation) is not tuple or len(innovation) != 4
        or any(type(k) is not int or k not in (0, 1, 2)
               for k in innovation)
        or action.stop or not feasible(state, action, cfg)):
        raise ValueError("unadmitted joint generation action")
    next_levels = tuple(min(2, old + min(units, shock))
                        for old, units, shock in zip(state.levels, action.units,
                                                     innovation))
    return State(next_levels, state.remaining - charge(state, action, cfg),
                 state.step + 1, action.mask)


def dependent_scenarios(horizon: int, regime):
    check_dependence_regime(regime)
    if type(horizon) is not int or not 1 <= horizon <= 3:
        raise ValueError("unadmitted enumeration horizon")
    for rows in product(regime, repeat=horizon):
        probability = math.prod(row[1] for row in rows)
        if probability == 0 and all(row[1] > 0 for row in rows):
            raise ValueError("positive path probability underflow")
        if probability > 0:
            yield tuple(row[0] for row in rows), probability


def rollout(initial: State, cfg: Config,
            path: tuple[int | tuple[int, int, int, int], ...],
            policy: Callable[[State], Allocation]) -> dict:
    if len(path) != cfg.horizon:
        raise ValueError("incomplete or overlong stochastic path")
    state = initial
    chosen = []
    for shock in path:
        action = policy(state)
        if not isinstance(action, Allocation) or not feasible(state, action, cfg):
            raise ValueError("unadmitted counterfactual action")
        chosen.append(action.units)
        if action.stop:
            break
        state = (advance(state, action, shock, cfg) if type(shock) is int
                 else advance_joint(state, action, shock, cfg))
    else:
        # One final STOP is not an extra random draw or a charged model call.
        final_action = policy(state)
        if final_action != STOP:
            raise ValueError("policy did not terminate at horizon")
        chosen.append(final_action.units)
    output = decode_all(state)
    loss = decoded_external_loss(output, cfg.sync_penalty)
    paid = initial.remaining - state.remaining + cfg.emission_reserve
    if (state.remaining < cfg.emission_reserve
        or paid > initial.remaining
        or state.remaining - cfg.emission_reserve < 0):
        raise AssertionError("missing mandatory modality emission reserve")
    return {"utility": -loss - cfg.cost_shadow_price * paid,
            "loss": float(loss), "paid_units": paid,
            "allocation_trace": tuple(chosen),
            "remaining_after_emission": state.remaining - cfg.emission_reserve,
            "decoded_modalities": tuple(output._fields),
            "terminal_levels": state.levels}


def empirical_cvar90(losses: list[float], probabilities: list[float]) -> float:
    if (not losses or len(losses) != len(probabilities)
        or any(not math.isfinite(x) for x in losses)
        or any(not math.isfinite(p) or p < 0 for p in probabilities)
        or not math.isclose(math.fsum(probabilities), 1.0, rel_tol=0, abs_tol=1e-12)):
        raise ValueError("invalid decoded-output tail distribution")
    tail_mass = 0.1
    total = 0.0
    for loss, probability in sorted(zip(losses, probabilities),
                                    key=lambda pair: pair[0], reverse=True):
        weight = min(tail_mass, probability)
        total += loss * weight
        tail_mass -= weight
        if tail_mass <= 1e-14:
            break
    if tail_mass > 1e-12:
        raise ValueError("insufficient upper-tail probability mass")
    return total / 0.1


def _public_state_policy(
    policy: Callable[[State], Allocation],
) -> Callable[[State], Allocation]:
    """Reject path-order dependent actions when replaying one public state.

    Each scenario separately traverses the same finite tree. Reusing an opaque,
    stateful callback without this guard could compare different decisions at
    identical observable states and falsely report a single feedback policy.
    This checks reproducibility, not provenance against hostile Python code.
    """
    observed: dict[State, Allocation] = {}

    def checked(state: State) -> Allocation:
        action = policy(state)
        if state in observed and observed[state] != action:
            raise ValueError(
                "non-deterministic public-state counterfactual policy")
        observed[state] = action
        return action

    return checked


def evaluate(initial: State, cfg: Config,
             policy: Callable[[State], Allocation],
             law: tuple[float, float, float] = SHOCK_PROBS) -> dict:
    if (not isinstance(initial, State) or initial.step != 0
        or initial.remaining < cfg.emission_reserve):
        raise ValueError("unfunded four-modal emission")
    checked = _public_state_policy(policy)
    records = [(rollout(initial, cfg, path, checked), prob)
               for path, prob in scenarios(cfg.horizon, law)]
    return summarize_records(cfg, records)


def evaluate_dependence(initial: State, cfg: Config,
                        policy: Callable[[State], Allocation], regime) -> dict:
    if (not isinstance(initial, State) or initial.step != 0
        or initial.remaining < cfg.emission_reserve):
        raise ValueError("unfunded or noninitial four-modal emission")
    checked = _public_state_policy(policy)
    records = [(rollout(initial, cfg, path, checked), prob)
               for path, prob in dependent_scenarios(cfg.horizon, regime)]
    return summarize_records(cfg, records)


def summarize_records(cfg: Config, records: list[tuple[dict, float]]) -> dict:
    values = tuple(row[0]["utility"] for row in records)
    weights = tuple(row[1] for row in records)
    losses = [row[0]["loss"] for row in records]
    mean_loss = math.fsum(p * x for p, x in zip(weights, losses))
    mean_cost = math.fsum(p * row["paid_units"] for row, p in records)
    return {"conditional_utility": conditional_ce(values, weights, cfg.risk_aversion),
            "mean_loss": mean_loss,
            "mean_paid_units": mean_cost,
            "cvar90_decoded_loss": empirical_cvar90(losses, list(weights)),
            "support_paths": len(records),
            "complete_outputs": all(set(row[0]["decoded_modalities"])
                                    == {"text", "audio", "image", "video"}
                                    for row in records),
            "all_budget_feasible": all(row[0]["remaining_after_emission"] >= 0
                                       for row in records),
            "distinct_allocation_traces": len({row[0]["allocation_trace"]
                                                for row in records})}


def fixed_plan_policy(plan: tuple[Allocation, ...]):
    def choose(state: State) -> Allocation:
        return plan[state.step] if state.step < len(plan) else STOP
    return choose


def _admissible_fixed_plan(initial: State, cfg: Config,
                           plan: tuple[Allocation, ...]) -> bool:
    # Feasibility depends on budget, time and previous activation, not
    # shock-dependent levels. Shock 0 suffices for the budget screen only.
    state = initial
    stopped = False
    for action in plan:
        if stopped:
            if not action.stop:
                return False
            continue
        if not feasible(state, action, cfg):
            return False
        if action.stop:
            stopped = True
        else:
            state = advance(state, action, 0, cfg)
    return True


def best_open_loop(initial: State, cfg: Config,
                   law: tuple[float, float, float] = SHOCK_PROBS) -> tuple[tuple[Allocation, ...], dict]:
    """Choose a full precommitted action schedule, without observed feedback."""
    check_joint_law(law)
    # Enumerate every admitted vector, including those that become affordable
    # after prior activation. Do not weaken the comparator by using only the
    # initially feasible subset.
    menu = (STOP,) + tuple(Allocation(x) for x in product(range(3), repeat=4)
                            if 0 < sum(x) <= cfg.max_units_per_step)
    if len(menu) ** cfg.horizon > 5000:
        raise ValueError("exact open-loop search exceeds declared resource cap")
    best_plan = None
    best_summary = None
    for plan in product(menu, repeat=cfg.horizon):
        if not _admissible_fixed_plan(initial, cfg, plan):
            continue
        summary = evaluate(initial, cfg, fixed_plan_policy(plan), law)
        if (best_summary is None or summary["conditional_utility"]
                > best_summary["conditional_utility"] + 1e-12):
            best_plan, best_summary = plan, summary
    if best_plan is None or best_summary is None:
        raise AssertionError("no admissible STOP plan")
    return best_plan, best_summary


def paired_nominal_shift(initial: State, cfg: Config,
                         shifted_law: tuple[float, float, float]) -> dict:
    """Freeze both nominal policies then reweight the same outcome paths."""
    check_joint_law(shifted_law)
    frozen_open_loop, nominal_static = best_open_loop(initial, cfg, SHOCK_PROBS)
    feedback = Controller(cfg)

    def dynamic_policy(s):
        return feedback.solve(s)[0]

    nominal_dynamic = evaluate(initial, cfg, dynamic_policy, SHOCK_PROBS)
    # Exact finite tree parity is checked against independent materialized
    # outputs and total cost, not just the controller's recursive internal sums.
    native_value = feedback.solve(initial)[1]
    if (abs(native_value - nominal_dynamic["conditional_utility"]) > 1e-8
        or nominal_dynamic["conditional_utility"] + 1e-8
           < nominal_static["conditional_utility"]):
        raise AssertionError("independent full-path Bellman parity failed")
    return {"scope": "FINITE_SYNTHETIC_DENY_ALL",
            "nominal_dynamic": nominal_dynamic,
            "nominal_open_loop": nominal_static,
            "shift_dynamic": evaluate(initial, cfg, dynamic_policy, shifted_law),
            "shift_open_loop": evaluate(initial, cfg,
                                        fixed_plan_policy(frozen_open_loop), shifted_law),
            "frozen_open_loop": tuple(a.units for a in frozen_open_loop),
            "nominal_exact_bellman_parity": True,
            "no_claim_of_shift_superiority": True}


def paired_dependence_shift(initial: State, cfg: Config, regime) -> dict:
    """Select policies on nominal law; evaluate the altered joint noise law."""
    check_dependence_regime(regime)
    plan, _ = best_open_loop(initial, cfg, SHOCK_PROBS)
    feedback = Controller(cfg)
    new_dynamic = evaluate_dependence(initial, cfg,
                                      lambda s: feedback.solve(s)[0], regime)
    new_static = evaluate_dependence(initial, cfg,
                                     fixed_plan_policy(plan), regime)
    return {"scope": "FINITE_SYNTHETIC_DENY_ALL",
            "dependence_dynamic": new_dynamic,
            "dependence_open_loop": new_static,
            "no_out_of_envelope_robustness_claim": True,
            "frozen_nominal_plan": tuple(a.units for a in plan)}
