"""Finite paid witness versus four-modal emission control; research only.

A two-class Bayesian fixture with public easy/hard evidence and a frozen
independent witness channel. Hidden truth is never passed into the policy.
Agreement among four generated modalities is not fact verification.
This is not a deployed verifier or identified human-preference model.
"""
from __future__ import annotations
from fractions import Fraction
from portfolio import Config, conditional_ce

WITNESS_ACCURACY = Fraction(49, 50)
MODES = ("easy", "hard")
REPORT_ZERO_PRIOR = {"easy": Fraction(99, 100), "hard": Fraction(1, 2)}
MANDATORY_OUTPUTS = ("text", "audio", "image", "video")


def prior_from_public(mode: str) -> Fraction:
    if type(mode) is not str or mode not in REPORT_ZERO_PRIOR:
        raise ValueError("unregistered public evidence class")
    return REPORT_ZERO_PRIOR[mode]


def witness_probability(p_zero: Fraction, witness: int) -> Fraction:
    if (type(p_zero) is not Fraction or not Fraction(0) <= p_zero <= Fraction(1)
        or type(witness) is not int or witness not in (0, 1)):
        raise ValueError("invalid witness likelihood request")
    accuracy = WITNESS_ACCURACY
    if witness == 0:
        return p_zero * accuracy + (1 - p_zero) * (1 - accuracy)
    return p_zero * (1 - accuracy) + (1 - p_zero) * accuracy


def posterior(p_zero: Fraction, witness: int) -> Fraction:
    pw = witness_probability(p_zero, witness)
    if not pw:
        raise ValueError("unsupported zero-likelihood observation")
    likelihood_y0 = WITNESS_ACCURACY if witness == 0 else 1 - WITNESS_ACCURACY
    return p_zero * likelihood_y0 / pw


def map_label(p_zero: Fraction) -> int:
    if not Fraction(0) <= p_zero <= Fraction(1):
        raise ValueError("unsupported posterior")
    return 0 if p_zero >= Fraction(1, 2) else 1


def stop_value(p_zero: Fraction, risk_aversion: float) -> float:
    decision = map_label(p_zero)
    p_correct = p_zero if decision == 0 else 1 - p_zero
    return conditional_ce((0.0, -1.0),
                          (float(p_correct), float(1 - p_correct)),
                          risk_aversion)


def query_value(p_zero: Fraction, cfg: Config) -> float:
    values = tuple(stop_value(posterior(p_zero, w), cfg.risk_aversion)
                   for w in (0, 1))
    pw = tuple(float(witness_probability(p_zero, w)) for w in (0, 1))
    return (conditional_ce(values, pw, cfg.risk_aversion)
            - cfg.cost_shadow_price)


def action_for_public(mode: str, remaining: int, cfg: Config) -> str:
    p_zero = prior_from_public(mode)
    if type(remaining) is not int or remaining < cfg.emission_reserve:
        raise ValueError("unfunded four-modal emission")
    # Information acquisition competes with four mandatory decoder units.
    if remaining < cfg.emission_reserve + 1:
        return "EMIT"
    return ("QUERY_INDEPENDENT"
            if query_value(p_zero, cfg) >
               stop_value(p_zero, cfg.risk_aversion) + 1e-12 else "EMIT")


def all_outputs(label: int) -> dict:
    if type(label) is not int or label not in (0, 1):
        raise ValueError("unsupported generated label")
    return {"text": f"symbol:{label}",
            "audio": (label, -label, label, -label),
            "image": ((label, label), (label, label)),
            "video": (((label, label), (label, label)),
                      ((label, label), (label, label)))}


def score_raw_outputs(outputs: dict, truth: int) -> int:
    if (type(outputs) is not dict or set(outputs) != set(MANDATORY_OUTPUTS)
        or type(truth) is not int or truth not in (0, 1)):
        raise ValueError("unverifiable terminal raw output")
    text = outputs["text"]
    if text not in ("symbol:0", "symbol:1"):
        raise ValueError("unsupported text output")
    label = int(text[-1])
    if outputs != all_outputs(label):
        raise ValueError("cross-modal mismatch")
    return int(label != truth)


def weighted_cvar90(losses: list[int], weights: list[Fraction]) -> float:
    if (len(losses) != len(weights) or not losses or sum(weights) != 1
        or any(type(w) is not Fraction or w < 0 for w in weights)):
        raise ValueError("incomplete terminal outcome distribution")
    tail = Fraction(1, 10)
    value = Fraction(0)
    for loss, weight in sorted(zip(losses, weights), reverse=True):
        if loss not in (0, 1):
            raise ValueError("invalid event")
        take = min(tail, weight)
        value += take * loss
        tail -= take
        if tail == 0:
            break
    if tail:
        raise ValueError("unresolved tail")
    return float(value / Fraction(1, 10))


def enumerate_outcomes(mode: str, cfg: Config, remaining: int,
                       policy: str) -> list[tuple[Fraction, int, int]]:
    """Return complete truth-and-witness law as (prob, loss, modeled units)."""
    p_zero = prior_from_public(mode)
    if type(remaining) is not int or remaining < cfg.emission_reserve:
        raise ValueError("unfunded four-output generation")
    if policy == "adaptive":
        chosen = action_for_public(mode, remaining, cfg)
    elif policy == "always_query":
        chosen = "QUERY_INDEPENDENT"
    elif policy == "never_query":
        chosen = "EMIT"
    else:
        raise ValueError("unadmitted witness policy")
    if (chosen == "QUERY_INDEPENDENT"
        and remaining < cfg.emission_reserve + 1):
        raise ValueError("unfunded information acquisition")
    spent = cfg.emission_reserve + int(chosen == "QUERY_INDEPENDENT")
    outcomes = []
    for truth, py in ((0, p_zero), (1, 1 - p_zero)):
        if chosen == "EMIT":
            label = map_label(p_zero)
            outcomes.append((py, score_raw_outputs(all_outputs(label), truth),
                             spent))
            continue
        for witness in (0, 1):
            # Witness arrives AFTER the budgeted query was chosen.
            likelihood = (WITNESS_ACCURACY if witness == truth
                          else 1 - WITNESS_ACCURACY)
            decision = map_label(posterior(p_zero, witness))
            outcomes.append((py * likelihood,
                             score_raw_outputs(all_outputs(decision), truth),
                             spent))
    if sum(row[0] for row in outcomes) != 1:
        raise AssertionError("incomplete joint outcome law")
    return outcomes


def evaluate_policy(cfg: Config, remaining: int, policy: str,
                    mode_weights: tuple[Fraction, Fraction] = (
                        Fraction(1, 2), Fraction(1, 2))) -> dict:
    if (type(mode_weights) is not tuple or len(mode_weights) != 2
        or any(type(w) is not Fraction or w < 0 for w in mode_weights)
        or sum(mode_weights) != 1):
        raise ValueError("invalid public mode distribution")
    rows = []
    for mode, weight in zip(MODES, mode_weights):
        rows.extend((weight * p, loss, paid) for p, loss, paid in
                    enumerate_outcomes(mode, cfg, remaining, policy))
    probabilities = [p for p, _, _ in rows]
    mean_loss = sum(p * loss for p, loss, _ in rows)
    mean_units = sum(p * paid for p, _, paid in rows)
    values = [-loss - cfg.cost_shadow_price * paid
              for _, loss, paid in rows]
    entropic = conditional_ce(tuple(values),
                             tuple(float(p) for p in probabilities),
                             cfg.risk_aversion)
    return {"scope": "FINITE_SYNTHETIC_INDEPENDENT_WITNESS",
            "policy": policy,
            "mean_external_loss": float(mean_loss),
            "mean_paid_units": float(mean_units),
            "mean_net_utility": (-float(mean_loss)
                                 - cfg.cost_shadow_price * float(mean_units)),
            "terminal_entropic_utility": entropic,
            "cvar90_external_loss": weighted_cvar90(
                [loss for _, loss, _ in rows], probabilities),
            "all_four_modalities_required": True}


def shared_wrong_no_new_information_bound(classes: int = 8) -> Fraction:
    # In this specific symmetric construction the common observed wrong report
    # rules out one class and leaves classes-1 equiprobable candidates.
    if type(classes) is not int or classes < 2:
        raise ValueError("invalid declared symmetry model")
    return Fraction(1, classes - 1)
