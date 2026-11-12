"""Read-only, float reference for real-time credit; no owner or training authority."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import islice
import json
import math

from study import ARMS, ContractError, FrozenCreditView


def _us(*values):
    if any(type(x) is not int or not 0 <= x <= 2**63 - 1 for x in values):
        raise ContractError("invalid microsecond time")


def _numbers(*values):
    if any(type(x) not in (int, float) or not -1e300 <= x <= 1e300 for x in values):
        raise ContractError("invalid finite number")


def _ids(values):
    return type(values) is tuple and bool(values) and all(
        type(x) is str and 0 < len(x) <= 256 for x in values)


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _bounded(values):
    result = list(islice(values, 65_537))
    if len(result) > 65_536:
        raise ContractError("raw input exceeds size limit")
    return result


@dataclass(frozen=True)
class ClockSpec:
    owner_id: str
    clock_domain: str
    boot_id: str
    reward_discount_tau_us: int
    state_response_tau_us: int
    parameter_update_interval_us: int
    eligibility_tau_us: int

    @property
    def identity(self):
        return (self.owner_id, self.clock_domain, self.boot_id)

    def __post_init__(self):
        times = (self.reward_discount_tau_us, self.state_response_tau_us,
                 self.parameter_update_interval_us, self.eligibility_tau_us)
        _us(*times)
        if not _ids(self.identity) or min(times) == 0:
            raise ContractError("invalid clock identity or timescale")


def reward_discount(clock, *, value, decision_us, reward_us):
    """Discount at the reward's occurrence, including an action-end reward."""
    _us(decision_us, reward_us)
    _numbers(value)
    if reward_us < decision_us:
        raise ContractError("reward precedes decision")
    return value * math.exp(-(reward_us - decision_us) / clock.reward_discount_tau_us)


def state_response(clock, *, previous, observed, elapsed_us):
    _us(elapsed_us)
    _numbers(previous, observed)
    weight = -math.expm1(-elapsed_us / clock.state_response_tau_us)
    return (1 - weight) * previous + weight * observed


def update_due(clock, *, last_update_us, now_us):
    """A timing opportunity only, never permission to update or adopt."""
    _us(last_update_us, now_us)
    if now_us < last_update_us:
        raise ContractError("update clock regression")
    return now_us - last_update_us >= clock.parameter_update_interval_us


@dataclass(frozen=True)
class TimedAction:
    action_id: str
    source_digest: str
    model_version: str
    clock_identity: tuple[str, str, str]
    action_us: int
    group_ids: tuple[str, ...]
    eligibility: tuple[float, ...]
    split: str = "train"


@dataclass(frozen=True)
class TimedFeedback:
    receipt_digest: str
    action_id: str
    source_digest: str
    model_version: str
    clock_identity: tuple[str, str, str]
    action_us: int
    outcome_us: int
    available_us: int
    group_ids: tuple[str, ...]
    modulator: tuple[float, ...]


def frozen_real_time_credit(actions, feedback, *, clock, model_version, arm,
                            cutoff_us, max_lag_us, per_group_limit=0.5,
                            global_l1_limit=1.0):
    """Bind the clock envelope, then freeze availability before other payloads.

    Eligibility decays until feedback becomes available, independently of reward
    occurrence discounting. A foreign clock cannot establish a future timestamp.
    Remaining future payloads never enter the candidate view/digest. Identities
    are self-declared; raw-input limits can reject even future-only streams.
    """
    _us(cutoff_us, max_lag_us)
    _numbers(per_group_limit, global_l1_limit)
    if (type(clock) is not ClockSpec or not _ids((model_version,))
            or arm not in ARMS or min(per_group_limit, global_l1_limit) <= 0):
        raise ContractError("invalid clock, model, arm or trust region")
    action_list, observed = _bounded(actions), []
    for item in _bounded(feedback):
        if type(item) is not TimedFeedback or item.clock_identity != clock.identity:
            raise ContractError("invalid feedback clock envelope")
        available = item.available_us
        _us(available)
        if available <= cutoff_us:
            observed.append(item)
    by_id = {}
    groups = None
    for action in action_list:
        if type(action) is not TimedAction:
            raise ContractError("invalid action")
        _us(action.action_us)
        if (not _ids((action.action_id,)) or action.action_id in by_id
                or not _hash(action.source_digest) or action.model_version != model_version
                or action.clock_identity != clock.identity or action.split != "train"
                or action.action_us > cutoff_us or not _ids(action.group_ids)
                or len(set(action.group_ids)) != len(action.group_ids)
                or not 1 <= len(action.group_ids) <= 64
                or type(action.eligibility) is not tuple
                or len(action.eligibility) != len(action.group_ids)):
            raise ContractError("invalid action identity, clock, version or groups")
        _numbers(*action.eligibility)
        if (any(abs(x) > 1 for x in action.eligibility)
                or sum(map(abs, action.eligibility)) > 4
                or (groups is not None and groups != action.group_ids)):
            raise ContractError("invalid eligibility or changed groups")
        groups = action.group_ids
        by_id[action.action_id] = action
    if groups is None or (arm == "shuffled" and len(groups) < 2):
        raise ContractError("empty actions or insufficient routing groups")
    if any(type(f) is not TimedFeedback or not _hash(f.receipt_digest) for f in observed):
        raise ContractError("invalid visible feedback")
    accum, receipts, targets = [0.0] * len(groups), set(), set()
    matched = expired = 0
    for fb in sorted(observed, key=lambda f: f.receipt_digest):
        _us(fb.action_us, fb.outcome_us, fb.available_us)
        if not _ids((fb.action_id,)) or fb.action_id not in by_id:
            raise ContractError("unknown feedback action")
        action = by_id[fb.action_id]
        if (fb.receipt_digest in receipts or fb.action_id in targets
                or (fb.source_digest, fb.model_version, fb.clock_identity, fb.action_us, fb.group_ids)
                != (action.source_digest, model_version, clock.identity, action.action_us, groups)
                or not fb.action_us <= fb.outcome_us <= fb.available_us
                or type(fb.modulator) is not tuple or len(fb.modulator) != len(groups)):
            raise ContractError("feedback binding, chronology or duplication failure")
        _numbers(*fb.modulator)
        if any(abs(x) > 1 for x in fb.modulator):
            raise ContractError("invalid modulator")
        receipts.add(fb.receipt_digest)
        targets.add(fb.action_id)
        lag = fb.available_us - action.action_us
        if lag > max_lag_us:
            expired += 1
            continue
        matched += 1
        vector = (fb.modulator if arm == "routed" else
                  fb.modulator[1:] + fb.modulator[:1] if arm == "shuffled" else
                  (sum(fb.modulator) / len(groups),) * len(groups) if arm == "scalar" else
                  (0.0,) * len(groups))
        for i, (eligibility, modulator) in enumerate(zip(action.eligibility, vector)):
            accum[i] += math.exp(-lag / clock.eligibility_tau_us) * eligibility * modulator
    projected = [min(per_group_limit, max(-per_group_limit, x)) for x in accum]
    scale = min(1.0, global_l1_limit / sum(map(abs, projected))) if any(projected) else 1.0
    payload = dict(clock=asdict(clock), model_version=model_version, arm=arm,
                   cutoff_us=cutoff_us, max_lag_us=max_lag_us,
                   per_group_limit=per_group_limit, global_l1_limit=global_l1_limit,
                   actions=[asdict(a) for a in sorted(action_list, key=lambda a: a.action_id)],
                   feedback=[asdict(f) for f in sorted(observed, key=lambda f: f.receipt_digest)])
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return FrozenCreditView(arm, tuple(x * scale for x in projected), matched, expired, digest)
