"""V8 causal executor with an explicit bounded finalization reservation.

Copied from v8 execution.py; source identity and exact diff are retained.
A declared budget is checked after actual work, not a preemption guarantee for
unbounded heads, sinks, Python scheduling, or operating-system stalls.
"""

from dataclasses import dataclass
import hashlib
import json
import time

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, ContractError, CoreSnapshot, CostWeights, Modality, VisibleContent, finite,
)
from experiments.hcsn_v8_execution_20261101.scheduler.planning import (
    Plan, Read, Wait, choose_plan, enumerate_plans, validate_plan,
)


class RealClock:
    def __init__(self):
        self.origin_ns = time.monotonic_ns()

    def now(self):
        return (time.monotonic_ns() - self.origin_ns) / 1e9

    def wait_until(self, target):
        delay = target - self.now()
        if delay > 0:
            time.sleep(min(delay, 60))


class LogicalClock:
    """Deterministic developmental replay; never a measured service clock."""

    origin_ns = None

    def __init__(self):
        self.time = 0.0

    def now(self):
        return self.time

    def wait_until(self, target):
        self.time = max(self.time, target)


@dataclass(frozen=True, slots=True)
class ReadResult:
    observation: object = None
    error: str | None = None

    def __post_init__(self):
        if (self.observation is None) == (self.error is None):
            raise ContractError("A read returns exactly one observation or error")


def source_increments(content, observation):
    """V8 global source clock; a second modality at the same window adds no time."""
    prior = max(content.level(modality) for modality in Modality)
    return (observation.prefix_end - content.level(observation.modality),
            max(prior, observation.prefix_end) - prior)


@dataclass(frozen=True, slots=True)
class FinalizationBudget:
    head_seconds: float = .08
    serialization_seconds: float = .04
    sink_seconds: float = .08
    guard_seconds: float = .20

    def __post_init__(self):
        for name in ("head_seconds", "serialization_seconds", "sink_seconds", "guard_seconds"):
            object.__setattr__(self, name, finite(getattr(self, name), name, 0, 10))

    @property
    def reserve_seconds(self):
        return self.head_seconds + self.serialization_seconds + self.sink_seconds + self.guard_seconds


def run_episode(object_id, budget, head, forecast, service_model, service, output_sink,
                clock=None, core=None, deadline=4.0, horizon=2, wait_seconds=(),
                max_requests=6, max_decisions=16, costs=CostWeights(), fixed_plans=None,
                finalization_budget=FinalizationBudget()):
    """Adapter interfaces: request(Read,clock)->pending; pending.wait_until(t,clock).

    pending.wait_until returns ReadResult only after actual completion, or None
    at timeout. pending.drain(clock) waits for and discards the late result.
    output_sink receives serialized bytes and must return after a real flush.
    Only request invokes the feature service. A controller sees accepted cache,
    declared core and public alternatives, never the service or pending result.
    core.accept receives global max-prefix time increment; the observation still
    updates content when that increment is zero. This explicitly versioned V8
    convention does not assert recovery of the missing V6 input-local dynamics.
    """
    clock = RealClock() if clock is None else clock
    deadline = finite(deadline, "deadline", 0, 60)
    hard_deadline = deadline
    if not isinstance(finalization_budget, FinalizationBudget):
        raise ContractError("Explicit validated finalization budget required")
    deadline = hard_deadline - finalization_budget.reserve_seconds
    if deadline <= 0:
        raise ContractError("Finalization reserve consumes the entire deadline")
    if type(max_requests) is not int or not 1 <= max_requests <= 6:
        raise ContractError("One to six requested observations are allowed")
    if type(max_decisions) is not int or not 1 <= max_decisions <= 64:
        raise ContractError("One to 64 decisions are allowed")
    if (forecast.kind == BackendKind.CORE) != (core is not None):
        raise ContractError("A core forecast requires exactly one core adapter")
    content = VisibleContent(object_id, budget)
    state = core.initial(content) if core else None
    if core and (not isinstance(state, CoreSnapshot) or state.content_fingerprint != content.fingerprint()):
        raise ContractError("Core initialization must bind 32 scalars to the empty cache")
    traces, decisions, updates, pending_drain = [], [], [], []
    requests = 0
    terminate = False
    fixed = iter(fixed_plans) if fixed_plans is not None else None

    def read(step, mandatory=False):
        nonlocal content, state, requests, terminate
        validate_plan(content, Plan((step,)))
        requests += 1
        trace = {"kind": "read", "request": requests, "mandatory": mandatory,
                 "action": step.identity, "requested_at": clock.now(),
                 "status": "requested", "before": content.fingerprint()}
        traces.append(trace)
        pending = None
        try:
            pending = service.request(step, clock)
            result = pending.wait_until(deadline, clock)
        except Exception as error:
            if pending is not None:
                pending_drain.append(pending)
            trace.update(status="failed", reason=f"{type(error).__name__}: {error}"[:512],
                         completed_at=clock.now(), after=content.fingerprint())
            terminate = True
            return
        if result is None:
            trace.update(status="timed_out", observed_at=clock.now(), after=content.fingerprint())
            pending_drain.append(pending)
            terminate = True
            return
        if not isinstance(result, ReadResult):
            raise ContractError("Feature service returned an invalid result")
        if result.error is not None:
            trace.update(status="failed", reason=result.error[:512], completed_at=clock.now(),
                         after=content.fingerprint())
            terminate = True
            return
        observation = result.observation
        now = clock.now()
        try:
            if now > deadline or observation.completed_at > deadline:
                raise ContractError("Late completion is excluded from output")
            if observation.modality != step.modality or observation.prefix_end != step.prefix_end:
                raise ContractError("Response differs from the requested prefix")
            modality_increment, global_increment = source_increments(content, observation)
            updated = content.accept(observation, now)
            next_state = core.accept(state, updated, observation, global_increment) if core else None
            if core and (not isinstance(next_state, CoreSnapshot) or next_state.content_fingerprint != updated.fingerprint()):
                raise ContractError("Core update is not bound to accepted content")
            content, state = updated, next_state
            updates.append({"modality": observation.modality.value,
                            "modality_prefix_increment": modality_increment,
                            "global_source_increment": global_increment,
                            "global_source_time": max(updated.level(m) for m in Modality),
                            "accepted_event_id": observation.event_id})
            trace.update(status="accepted", completed_at=observation.completed_at,
                         accepted_at=now, after=content.fingerprint())
        except Exception as error:
            trace.update(status="rejected", reason=f"{type(error).__name__}: {error}"[:512],
                         completed_at=now, after=content.fingerprint())
            terminate = True

    # The common first audio request is real work, even if it fails or times out.
    read(Read(Modality.AUDIO, 1), mandatory=True)
    for index in range(max_decisions):
        if terminate or requests >= max_requests or clock.now() >= deadline:
            break
        plans = tuple(p for p in enumerate_plans(content, horizon, wait_seconds)
                      if requests + p.requested_reads <= max_requests)
        if fixed is None:
            selected, decision = choose_plan(content, state, head, forecast, service_model,
                                             plans, clock.now(), deadline, costs)
            decisions.append(decision)
        else:
            selected = next(fixed, None)
            if selected is not None:
                validate_plan(content, selected, horizon)
                if requests + selected.requested_reads > max_requests:
                    raise ContractError("Fixed plan exceeds the requested observation budget")
            decisions.append({"selected": selected.identity if selected else None,
                              "mode": "fixed", "content_fingerprint": content.fingerprint()})
        if selected is None:
            break
        for step in selected.steps:
            if clock.now() >= deadline or terminate:
                terminate = True
                break
            if type(step) is Read:
                read(step)
            else:
                before = content.fingerprint()
                prior_state = state
                start = clock.now()
                clock.wait_until(min(deadline, start + step.seconds))
                traces.append({"kind": "wait", "started_at": start, "ended_at": clock.now(),
                               "before": before, "after": content.fingerprint(),
                               "core_unchanged": prior_state == state})

    drains = []
    try:
        # Freeze and flush before draining. Even a failed head/sink drains owned work.
        finalization_started = clock.now()
        stop = head.evaluate(content)
        head_completed = clock.now()
        output = {"kind": "episode_prediction", "episode_id": object_id,
                  "predicted_class": stop.predicted_class, "probabilities": stop.class_probabilities,
                  "head_id": stop.calibrated_correctness.head_id,
                  "content_fingerprint": content.fingerprint(),
                  "accepted_event_ids": content.accepted_event_ids,
                  "scientific_confirmation": False}
        serialized = (json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        serialized_at = clock.now()
        output_sink(serialized)
        output_at = clock.now()
        flush_ns = time.monotonic_ns() if clock.origin_ns is not None else None
    finally:
        for pending in pending_drain:
            before = clock.now()
            try:
                pending.drain(clock)
                drains.append({"start": before, "end": clock.now(), "status": "discarded_after_output_attempt"})
            except Exception as error:
                drains.append({"start": before, "end": clock.now(), "status": "drain_error",
                               "reason": f"{type(error).__name__}: {error}"[:512]})
    return {"schema": "hcsn-v10-reserved-causal-execution.v1", "purpose": "development_support",
            "scientific_confirmation": False, "clock": type(clock).__name__,
            "service_mode": service.mode, "source_monotonic_ns": clock.origin_ns,
            "output_flush_monotonic_ns": flush_ns, "output_elapsed_seconds": output_at,
            "post_drain_elapsed_seconds": clock.now(), "timely_output": output_at <= hard_deadline,
            "deadline_seconds": hard_deadline, "service_deadline_seconds": deadline,
            "finalization": {"started_at": finalization_started, "head_completed_at": head_completed,
                "serialized_at": serialized_at, "sink_completed_at": output_at,
                "head_seconds": head_completed-finalization_started,
                "serialization_seconds": serialized_at-head_completed,
                "sink_seconds": output_at-serialized_at,
                "reserve_seconds": finalization_budget.reserve_seconds,
                "budget": {name: getattr(finalization_budget, name) for name in
                    ("head_seconds", "serialization_seconds", "sink_seconds", "guard_seconds")},
                "budget_satisfied": (head_completed-finalization_started <= finalization_budget.head_seconds
                    and serialized_at-head_completed <= finalization_budget.serialization_seconds
                    and output_at-serialized_at <= finalization_budget.sink_seconds
                    and finalization_started <= deadline+finalization_budget.guard_seconds)},
            "requested_observations": requests,
            "observation_fee": requests * costs.observation,
            "latency_fee": output_at * costs.elapsed_second,
            "deadline_penalty": costs.deadline_miss * (output_at > hard_deadline),
            "output": output, "serialized_output_sha256": hashlib.sha256(serialized).hexdigest(),
            "events": traces, "decisions": decisions, "source_window_updates": updates,
            "late_drains": drains, "cache_storage": content.storage_accounting()}
