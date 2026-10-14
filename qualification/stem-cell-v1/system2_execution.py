"""Bounded generate/verify/revise research execution and continuation algebra.

Callbacks are read-only adapters to existing model/verifier/value owners. This
module grants no effects, installs no model and is NOT a general FBSDE solver.
The linear-discounted continuation helper is intentionally profile-specific.
"""
from __future__ import annotations

import math
import copy
import contextlib
import sys
import time
from dataclasses import asdict, dataclass
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
                  max_rounds: int = 8, max_calls: int = 24,
                  ndu_policy=None, meter=None, clock=time.time_ns, paired_start=None, fixed_policy=None):
    """Actually call proposer/verifier, then revise using returned feedback.

    continue_values(task, candidate, feedback, rounds_left) returns
    (continue_value, stop_value) in a named, already cost-inclusive utility
    profile. It must use a frozen/cross-fitted estimator, not final eval labels.
    The call ceiling is NOT a FLOP/latency equivalence claim. Failed and invalid
    callback attempts are retained and charged. Final evaluation is separate.

    Opt-in ndu_policy requires a matching value_profile and live WorkLedger.
    Its value callback receives a frozen DecisionContext instead of rounds_left,
    and returns a ContinuationEstimate (or None for unsupported). Proposed
    values are not assumed to be learned, calibrated or independently attested.
    All three callback kinds consume the search budget; ATen metering covers
    this process only, never uninstrumented subprocess/API/tokenizer work.
    """
    task.validate()
    policy = copy.deepcopy(ndu_policy)
    fixed = copy.deepcopy(fixed_policy)
    if sum(x is not None for x in (policy, paired_start, fixed)) > 1:
        raise ValueError("paired collection, fixed control and NDU policies are mutually exclusive")
    if fixed is not None:
        from reasoning_baselines import validate_baseline
        validate_baseline(fixed, task, meter, max_rounds, max_calls, value_profile, continue_values)
    if paired_start is not None:
        from paired_capture import PairedStart
        if type(paired_start) is not PairedStart:
            raise ValueError("typed registered pair start required")
        paired_start = copy.deepcopy(paired_start)
        paired_start.validate(task, meter, max_rounds, max_calls, value_profile, continue_values)
    bounded = policy is not None or paired_start is not None or fixed is not None
    expiry = policy["expires_at_ns"] if policy is not None else (paired_start.expires_at_ns if paired_start else (fixed["expires_at_ns"] if fixed else None))
    task = copy.deepcopy(task) if bounded else task
    fixed_task_id = _digest(asdict(task))
    if policy is not None:
        from ndu_continuation import validate_policy, PROFILE
        validate_policy(policy, task_as_of_ns=task.as_of_ns)
        if meter is None or value_profile != PROFILE:
            raise ValueError("NDU control requires an actual work meter and its exact utility profile")
        actual = {"max_calls": max_calls, "max_rounds": max_rounds,
                  "meter_policy": meter.policy, "phase_caps": meter.caps}
        if _digest(actual) != _digest(policy["execution"]):
            raise ValueError("reasoning executor differs from the frozen resource contract")
        now = clock()
        if type(now) is not int or not task.as_of_ns <= now < policy["expires_at_ns"]:
            raise ValueError("reasoning policy is not valid at the current task boundary")
    elif meter is not None and paired_start is None and fixed is None:
        raise ValueError("metered reasoning requires a bound NDU policy")
    _text(value_profile)
    if type(max_rounds) is not int or not 1 <= max_rounds <= 64:
        raise ValueError("bounded rounds required")
    if type(max_calls) is not int or not 2 <= max_calls <= 192:
        raise ValueError("bounded callback count required")
    if policy is not None and policy.get("empirical_protocol_id") is not None:
        from empirical_continuation import FrozenPairedCritic
        if type(continue_values) is not FrozenPairedCritic:
            raise ValueError("empirical policy requires the fitted frozen critic adapter")
        continue_values.validate_binding(policy, propose, verify)
    trace, candidate, feedback, calls = [], None, None, 0
    if paired_start is not None:
        candidate, feedback = paired_start.candidate, paired_start.feedback
    decisions, pending_context, segment_start = [], None, None
    scope = meter.scope if meter is not None else lambda *args: contextlib.nullcontext()
    started = time.perf_counter_ns()

    def finish(status):
        result = {"schema": "hepta.stem.executed-reasoning.v1", "status": status,
                "candidate": candidate, "calls": calls, "trace": trace,
                "elapsed_ns": time.perf_counter_ns() - started,
                "value_profile": value_profile, "measured_flops": None,
                "general_fbsde_solved": False, "independent_success_established": False,
                "production_authorized": False}
        if policy is not None:
            result.update(schema="hepta.stem.executed-reasoning.v2", ndu_policy=policy,
                          task_sha256=fixed_task_id, ndu_decisions=decisions,
                          work_observation=meter.report(),
                          accounting_gaps=["external_process_or_tool_work", "python_scalar_arithmetic",
                                           "independent_final_evaluation", "process_energy"],
                          native_ndu_owner_integrated=False, learned_critic_validated=False,
                          full_cost_qualification=False)
        if policy is not None and policy.get("empirical_protocol_id") is not None:
            result["empirical_critic"] = continue_values.receipt()
        if fixed is not None:
            result.update(schema="hepta.stem.fixed-control-execution.v1", fixed_policy=fixed,
                          task_sha256=fixed_task_id, work_observation=meter.report(),
                          common_ceiling_is_not_equal_work=True, full_cost_qualification=False)
        if paired_start is not None:
            result.update(schema="hepta.stem.paired-segment-execution.v1", capture_id=paired_start.capture_id,
                          task_sha256=fixed_task_id, work_observation=meter.report(),
                          full_cost_qualification=False, utility_labels_loaded=False)
        return result

    def invoke(kind, function, *args):
        nonlocal calls
        calls += 1
        before = time.perf_counter_ns()
        entry = {"kind": kind, "call": calls, "elapsed_ns": 0, "status": "unknown"}
        trace.append(entry)
        # Preserve bounded generation observations in the SAME callback trace.
        causal_module = sys.modules.get("causal_generation")
        local_generator = (kind == "propose" and causal_module is not None
                           and type(function) is getattr(causal_module, "LocalCausalProposer", None))
        prior_generation = function.receipt()["last_generation"] if local_generator else None
        try:
            component = {"propose": "proposer", "verify": "verifier", "value": "value"}[kind]
            with scope("search", component):
                if bounded:
                    boundary = clock()
                    if type(boundary) is not int or not task.as_of_ns <= boundary < expiry:
                        raise ValueError("reasoning policy expired before callback")
                result = function(*args)
                if fixed is not None and clock() >= expiry:
                    raise ValueError("fixed control expired during callback")
                if bounded and _digest(asdict(task)) != fixed_task_id:
                    raise ValueError("callback mutated the fixed public task")
                if kind == "propose":
                    _text(result)
                    entry["output_digest"] = _digest(result)
                elif kind == "verify":
                    if not isinstance(result, Verification):
                        raise ValueError("verifier returned an untyped result")
                    result.validate()
                    entry["output_digest"] = _digest([result.accepted, result.feedback])
                elif policy is not None:
                    from ndu_continuation import ContinuationEstimate
                    expected_type = ContinuationEstimate
                    if policy.get("empirical_protocol_id") is not None:
                        from empirical_continuation import EmpiricalEstimate
                        expected_type = EmpiricalEstimate
                    if result is not None:
                        if type(result) is not expected_type:
                            raise ValueError("a typed context-bound continuation estimate is required")
                        result.validate()
                    entry["output_digest"] = _digest(asdict(result) if result is not None else None)
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
            if local_generator:
                generated = function.receipt()["last_generation"]
                if generated != prior_generation:
                    entry["generation"] = generated
            entry["elapsed_ns"] = time.perf_counter_ns() - before

    for round_index in range(max_rounds):
        if calls + 2 > max_calls:
            return finish("budget_exhausted")
        try:
            if policy is not None and clock() >= policy["expires_at_ns"]:
                return finish("ndu_stop:expired_policy")
            candidate = invoke("propose", propose, task, candidate, feedback)
            checked = invoke("verify", verify, task, candidate)
            feedback = checked.feedback
            if policy is not None and segment_start is not None:
                after = meter.budget_state("search")
                last = decisions[-1]
                used = (segment_start["remaining_formula_work"] - after["remaining_formula_work"]
                        if after["remaining_formula_work"] is not None else None)
                duration = segment_start["remaining_wall_ns"] - after["remaining_wall_ns"]
                last.update(observed_segment_formula_work=used, observed_segment_wall_ns=duration,
                            realized_support_bounds_satisfied=used is not None and
                            0 <= used <= last["worst_branch_formula_work"] and
                            0 <= duration <= last["worst_branch_duration_ns"])
                segment_start = None
                if not last["realized_support_bounds_satisfied"]:
                    return finish("ndu_stop:continuation_support_violated")
            if checked.accepted:
                return finish("verifier_accepted_not_independent_eval")
            if round_index + 1 == max_rounds:
                return finish("depth_exhausted")
            if fixed is not None:
                # A true fixed-depth control never calls a dummy value callback.
                continue
            # One valuation plus at least proposer+verifier must remain.
            if calls + 3 > max_calls:
                return finish("budget_exhausted")
            if policy is None:
                continuation, stop = invoke("value", continue_values, task, candidate,
                                            feedback, max_rounds - round_index - 1)
                if continuation <= stop:
                    return finish("utility_stop")
            else:
                from ndu_continuation import DecisionContext, decide
                resources = meter.budget_state("search")
                at = clock()
                if type(at) is not int or at < task.as_of_ns:
                    raise ValueError("invalid causal decision clock")
                pending_context = DecisionContext(
                    policy["policy_id"], fixed_task_id, _digest(candidate), _digest(feedback),
                    _digest(trace), at, max_rounds - round_index - 1, max_calls - calls,
                    resources["remaining_formula_work"], resources["remaining_wall_ns"])
                context_id = pending_context.context_id
                estimate = invoke("value", continue_values, task, candidate, feedback, pending_context)
                if pending_context.context_id != context_id:
                    raise ValueError("critic mutated its fixed decision context")
                segment_start = meter.budget_state("search")
                decision = decide(policy, pending_context, estimate, now_ns=clock(), resources=segment_start)
                decisions.append(decision)
                if not decision["continue_computation"]:
                    return finish("ndu_stop:" + decision["reason"])
        except Exception as exc:
            if bounded:
                from execution_meter import BudgetStop
                if isinstance(exc, BudgetStop):
                    return finish("resource_budget_stop")
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


def aggregate_children(values, *, node_kind, probabilities=None, required_ids=None):
    """Distinguish choice, chance, and *complete* mandatory-proof conjunctions.

    An AND node is a Boolean feasibility check, NOT a numeric utility
    aggregator. Its full obligation inventory must be fixed independently;
    a favorable subset of children cannot stand in for all requirements.
    This helper is not a learned FBSDE solver or a production verifier.
    """
    if node_kind == "and":
        if (probabilities is not None or type(required_ids) is not tuple
                or not 1 <= len(required_ids) <= 64
                or any(type(i) is not str or not 1 <= len(i.encode("utf-8")) <= 128
                       for i in required_ids)
                or len(set(required_ids)) != len(required_ids)
                or not isinstance(values, (list, tuple)) or len(values) != len(required_ids)):
            raise ValueError("AND requires an exact externally fixed obligation inventory")
        observed = {}
        for item in values:
            if (not isinstance(item, (tuple, list)) or len(item) != 2
                    or type(item[0]) is not str or type(item[1]) is not bool
                    or item[0] in observed):
                raise ValueError("AND requires distinct typed obligation verdicts")
            observed[item[0]] = item[1]
        if set(observed) != set(required_ids):
            raise ValueError("missing, replaced, or extra AND obligation")
        return all(observed.values())
    if required_ids is not None:
        raise ValueError("numeric choice/chance nodes cannot accept AND requirements")
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
