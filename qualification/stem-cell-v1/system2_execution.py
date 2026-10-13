"""Bounded generate/verify/revise research execution and continuation algebra.

Callbacks are read-only adapters to existing model/verifier/value owners. This
module grants no effects, installs no model and is NOT a general FBSDE solver.
The linear-discounted continuation helper is intentionally profile-specific.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from next_round_matrix import _digest


@dataclass(frozen=True)
class PublicTask:
    prompt: str
    as_of_ns: int
    observations: tuple[tuple[str, int], ...] = ()

    def validate(self):
        _text(self.prompt)
        if type(self.as_of_ns) is not int or self.as_of_ns < 1 or len(self.observations) > 64:
            raise ValueError("bounded causal input required")
        for text, available_at_ns in self.observations:
            _text(text)
            if type(available_at_ns) is not int or not 0 < available_at_ns <= self.as_of_ns:
                raise ValueError("future observations cannot enter the public task")


@dataclass(frozen=True)
class Verification:
    accepted: bool
    feedback: str

    def validate(self):
        if type(self.accepted) is not bool:
            raise ValueError("typed verification result required")
        _text(self.feedback)


def _text(text):
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 65_536:
        raise ValueError("bounded nonempty text required")


def run_reasoning(task: PublicTask, *, propose: Callable, verify: Callable,
                  continue_values: Callable, value_profile: str,
                  max_rounds: int = 8, max_calls: int = 24):
    """Actually call proposer/verifier, then revise using returned feedback.

    continue_values(task, candidate, feedback, rounds_left) returns
    (continue_value, stop_value) in a named, already cost-inclusive utility
    profile. It must use a frozen/cross-fitted estimator, not final eval labels.
    The call ceiling is NOT a FLOP/latency equivalence claim. Failed and invalid
    callback attempts are retained and charged. Final evaluation is separate.
    """
    task.validate()
    _text(value_profile)
    if type(max_rounds) is not int or not 1 <= max_rounds <= 64:
        raise ValueError("bounded rounds required")
    if type(max_calls) is not int or not 2 <= max_calls <= 192:
        raise ValueError("bounded callback count required")
    trace, candidate, feedback, calls = [], None, None, 0
    started = time.perf_counter_ns()

    def finish(status):
        return {"schema": "hepta.stem.executed-reasoning.v1", "status": status,
                "candidate": candidate, "calls": calls, "trace": trace,
                "elapsed_ns": time.perf_counter_ns() - started,
                "value_profile": value_profile, "measured_flops": None,
                "general_fbsde_solved": False, "independent_success_established": False,
                "production_authorized": False}

    def invoke(kind, function, *args):
        nonlocal calls
        calls += 1
        before = time.perf_counter_ns()
        entry = {"kind": kind, "call": calls, "elapsed_ns": 0, "status": "unknown"}
        trace.append(entry)
        try:
            result = function(*args)
            if kind == "propose":
                _text(result)
                entry["output_digest"] = _digest(result)
            elif kind == "verify":
                if not isinstance(result, Verification):
                    raise ValueError("verifier returned an untyped result")
                result.validate()
                entry["output_digest"] = _digest([result.accepted, result.feedback])
            else:
                if (not isinstance(result, tuple) or len(result) != 2
                        or any(type(v) not in (float, int) or not math.isfinite(v) for v in result)):
                    raise ValueError("finite continuation and stop values required")
                entry["output_digest"] = _digest(result)
            entry["status"] = "completed"
            return result
        except Exception as exc:
            # No raw provider error, credentials, or fabricated retry success.
            entry["status"] = "failed"
            entry["error_type"] = type(exc).__name__
            raise
        finally:
            entry["elapsed_ns"] = time.perf_counter_ns() - before

    for round_index in range(max_rounds):
        if calls + 2 > max_calls:
            return finish("budget_exhausted")
        try:
            candidate = invoke("propose", propose, task, candidate, feedback)
            checked = invoke("verify", verify, task, candidate)
            feedback = checked.feedback
            if checked.accepted:
                return finish("verifier_accepted_not_independent_eval")
            if round_index + 1 == max_rounds:
                return finish("depth_exhausted")
            # One valuation plus at least proposer+verifier must remain.
            if calls + 3 > max_calls:
                return finish("budget_exhausted")
            continuation, stop = invoke("value", continue_values, task, candidate,
                                        feedback, max_rounds - round_index - 1)
            if continuation <= stop:
                return finish("utility_stop")
        except Exception:
            return finish("callback_failed")
    return finish("depth_exhausted")


def discounted_segments(segments, *, terminal_value, discount_rate):
    """Backward continuation for U=start_reward+exp(-rate*duration)*U_next.

    Each segment is (already-discounted within-segment reward, actual duration).
    The outgoing segment value is the incoming continuation of its predecessor;
    boundaries are not reset to zero and hierarchy depth is not elapsed time.
    """
    if (not isinstance(segments, (list, tuple)) or not 1 <= len(segments) <= 512
            or type(terminal_value) not in (int, float) or not math.isfinite(terminal_value)
            or type(discount_rate) not in (int, float) or not math.isfinite(discount_rate)
            or discount_rate < 0):
        raise ValueError("invalid linear-discounted continuation profile")
    result = [float(terminal_value)]
    for reward, duration in reversed(segments):
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (reward, duration)) or duration <= 0:
            raise ValueError("finite reward and positive duration required")
        value = reward + math.exp(-discount_rate * duration) * result[-1]
        if not math.isfinite(value):
            raise ValueError("nonfinite continuation")
        result.append(value)
    return list(reversed(result))


def aggregate_children(values, *, node_kind, probabilities=None):
    """Chance expectation and choice optimization are deliberately distinct."""
    if (not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 64
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
        raise ValueError("bounded finite child values required")
    if node_kind == "choice":
        if probabilities is not None:
            raise ValueError("choice node cannot smuggle chance probabilities")
        return max(values)
    if node_kind != "chance" or not isinstance(probabilities, (list, tuple)) or len(probabilities) != len(values):
        raise ValueError("chance node requires explicit probabilities")
    if any(type(p) not in (float, int) or not math.isfinite(p) or p < 0 for p in probabilities):
        raise ValueError("invalid chance probability")
    if not math.isclose(sum(probabilities), 1., rel_tol=0., abs_tol=1e-12):
        raise ValueError("chance probabilities must sum to one")
    return math.fsum(p * v for p, v in zip(probabilities, values, strict=True))
