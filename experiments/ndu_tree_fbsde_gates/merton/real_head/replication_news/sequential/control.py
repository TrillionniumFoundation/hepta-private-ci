"""Prefix-only, pre-execution investment decisions. Not an optimal FBSDE solver."""
from __future__ import annotations

from fractions import Fraction as Q

STEPS = (0, 8, 32, 128)
PROFILES = ("neutral", "fixed", "ndu")


def rational(value):
    if type(value) not in (int, str, Q):
        raise ValueError("exact nonnegative quote required")
    out = Q(value)
    if out < 0:
        raise ValueError("negative quote")
    return out


def validate(history, scenario, profile):
    if profile not in PROFILES:
        raise ValueError("unknown utility profile")
    if set(scenario) != {"name", "horizon", "step_fee", "calibration_fee", "budget"}:
        raise ValueError("unknown scenario field")
    if not isinstance(scenario['name'], str) or not scenario['name']:
        raise ValueError("scenario identity required")
    if type(scenario['horizon']) is not int or not 1 <= scenario['horizon'] <= 1024:
        raise ValueError("invalid reuse horizon")
    if type(scenario['budget']) is not int or not 0 <= scenario['budget'] <= 128:
        raise ValueError("invalid hard budget")
    rational(scenario['step_fee']); rational(scenario['calibration_fee'])
    if not history or len(history) > 4:
        raise ValueError("observed prefix required")
    for i, row in enumerate(history):
        if set(row) != {'step', 'counts'} or type(row['step']) is not int or row['step'] != STEPS[i]:
            raise ValueError("not a consecutive observed checkpoint prefix")
        if row['step'] > scenario['budget']:
            raise ValueError("history exceeds budget")
        if len(row['counts']) != 4 or any(type(n) is not int or not 0 <= n <= 8 for n in row['counts']):
            raise ValueError("invalid four-block observation")


def alpha_for(history, profile):
    if profile not in PROFILES:
        raise ValueError("unknown profile")
    if profile == 'neutral':
        return Q(0)
    if profile == 'fixed':
        return Q(1, 4)
    alpha = Q(1, 4)
    for row in history:
        alpha = max(Q(0), min(Q(1, 2), alpha + (1 - 2*Q(sum(row['counts']), 32))/8))
    return alpha


def utility(counts, alpha):
    return (1-alpha)*Q(sum(counts), 32) + alpha*Q(min(counts), 8)


def decision(history, scenario, profile):
    """Only past checkpoint counts are inputs; no later weights or loss curve."""
    validate(history, scenario, profile)
    alpha = alpha_for(history, profile)
    values = [utility(r['counts'], alpha) for r in history]
    best = max(values)
    current = history[-1]['step']
    nxt = STEPS[len(history)] if len(history) < len(STEPS) else None
    quote = Q(0) if nxt is None else (nxt-current)*rational(scenario['step_fee']) + rational(scenario['calibration_fee'])
    headroom = scenario['horizon']*(1-best)
    projected = None
    if nxt is None:
        reason = 'checkpoint_limit'
    elif nxt > scenario['budget']:
        reason = 'hard_budget'
    elif headroom <= quote:
        reason = 'perfect_payoff_cannot_repay'
    elif len(history) == 1:
        reason = 'bounded_first_pilot'
    else:
        gain = max(Q(0), values[-1]-values[-2])
        projected = scenario['horizon']*min(1-best, gain*Q(nxt-current, current-history[-2]['step']))
        reason = 'projected_gain_pays' if projected > quote else 'empirical_slope_stop'
    proceed = reason in ('bounded_first_pilot', 'projected_gain_pays')
    return {'action': 'continue' if proceed else 'stop', 'from_step': current,
            'to_step': nxt if proceed else None, 'reason': reason, 'alpha': str(alpha),
            'next_quote': str(quote), 'perfect_gain_ceiling': str(headroom),
            'projected_gain': None if projected is None else str(projected)}


def select(history, scenario, profile):
    validate(history, scenario, profile)
    alpha = alpha_for(history, profile)
    winner = max(history, key=lambda r: utility(r['counts'], alpha))
    return winner['step']
