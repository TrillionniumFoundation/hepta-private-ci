"""Explicit metered no-search/fixed-depth controls, without a fake NDU critic.

Fixed-depth is an upper bound: all modes stop on the same verifier acceptance.
Common ceilings do not imply equal ACTUAL work or a matched-quality experiment.
"""
from __future__ import annotations

from next_round_matrix import _digest
from paired_execution import PHASES, _integer, _sha

PROFILE = "fixed_computation_control.v1"
SCHEMA = "hepta.system2.fixed-compute-policy.v1"


def freeze_baseline(*, strategy, objective_sha256, callback_profile_sha256,
                    expires_at_ns, meter_policy, phase_caps, max_rounds):
    from execution_meter import validate_policy
    validate_policy(meter_policy)
    for value in (objective_sha256, callback_profile_sha256):
        _sha(value, "fixed control identity")
    _integer(expires_at_ns, "fixed control expiry", 1)
    _integer(max_rounds, "fixed depth", 1)
    if (strategy not in ("no_search", "fixed_depth") or max_rounds > 64
            or (strategy == "no_search" and max_rounds != 1)
            or (strategy == "fixed_depth" and max_rounds < 2)):
        raise ValueError("explicit no-search or bounded fixed depth required")
    if not isinstance(phase_caps, dict) or set(phase_caps) != set(PHASES):
        raise ValueError("all phase caps required")
    for cap in phase_caps.values():
        _integer(cap, "fixed control work cap")
    import copy
    body = copy.deepcopy(dict(schema=SCHEMA, strategy=strategy, objective_sha256=objective_sha256,
                              callback_profile_sha256=callback_profile_sha256, expires_at_ns=expires_at_ns,
                              meter_policy=meter_policy, phase_caps=phase_caps,
                              max_rounds=max_rounds, max_calls=2*max_rounds, stop_on_verified=True))
    return {**body, "policy_id": _digest(body)}


def validate_baseline(policy, task, meter, max_rounds, max_calls, value_profile, continue_values):
    fields = ("strategy", "objective_sha256", "callback_profile_sha256", "expires_at_ns",
              "meter_policy", "phase_caps", "max_rounds")
    try:
        expected = freeze_baseline(**{k: policy[k] for k in fields})
    except (TypeError, KeyError) as exc:
        raise ValueError("complete fixed computation policy required") from exc
    if (_digest(policy) != _digest(expected) or meter is None or continue_values is not None
            or value_profile != PROFILE or max_rounds != policy["max_rounds"]
            or max_calls != policy["max_calls"] or task.as_of_ns >= policy["expires_at_ns"]
            or _digest(meter.policy) != _digest(policy["meter_policy"])
            or _digest(meter.caps) != _digest(policy["phase_caps"])):
        raise ValueError("fixed control must use its frozen depth, no critic, and actual meter")
