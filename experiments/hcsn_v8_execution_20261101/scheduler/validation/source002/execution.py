"""Serial causal execution with a frozen output before any late-work drain."""

from dataclasses import dataclass
import hashlib
import json
import time

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, ContractError, CoreSnapshot, CostWeights, Modality, VisibleContent, finite,
)
from .planning import Plan, Read, Wait, choose_plan, enumerate_plans, validate_plan


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


def run_episode(object_id, budget, head, forecast, service_model, service, output_sink,
                clock=None, core=None, deadline=4.0, horizon=2, wait_seconds=(),
                max_requests=6, max_decisions=16, costs=CostWeights(), fixed_plans=None):
    """Adapter interfaces: request(Read,clock)->pending; pending.wait_until(t,clock).

    pending.wait_until returns ReadResult only after actual completion, or None
    at timeout. pending.drain(clock) waits for and discards the late result.
    output_sink receives serialized bytes and must return after a real flush.
    Only request invokes the feature service. A controller sees accepted cache,
    declared core and public alternatives, never the service or pending result.
    """
    clock = RealClock() if clock is None else clock
    deadline = finite(deadline, "deadline", 0, 60)
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
            increment = observation.prefix_end - content.level(observation.modality)
            updated = content.accept(observation, now)
            next_state = core.accept(state, updated, observation, increment) if core else None
            if core and (not isinstance(next_state, CoreSnapshot) or next_state.content_fingerprint != updated.fingerprint()):
                raise ContractError("Core update is not bound to accepted content")
            content, state = updated, next_state
            updates.append({"modality": observation.modality.value, "source_increment": increment,
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
        stop = head.evaluate(content)
        output = {"kind": "episode_prediction", "episode_id": object_id,
                  "predicted_class": stop.predicted_class, "probabilities": stop.class_probabilities,
                  "head_id": stop.calibrated_correctness.head_id,
                  "content_fingerprint": content.fingerprint(),
                  "accepted_event_ids": content.accepted_event_ids,
                  "scientific_confirmation": False}
        serialized = (json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
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
    return {"schema": "hcsn-v8-causal-execution.v1", "purpose": "development_support",
            "scientific_confirmation": False, "clock": type(clock).__name__,
            "service_mode": service.mode, "source_monotonic_ns": clock.origin_ns,
            "output_flush_monotonic_ns": flush_ns, "output_elapsed_seconds": output_at,
            "post_drain_elapsed_seconds": clock.now(), "timely_output": output_at <= deadline,
            "deadline_seconds": deadline, "requested_observations": requests,
            "observation_fee": requests * costs.observation,
            "latency_fee": output_at * costs.elapsed_second,
            "deadline_penalty": costs.deadline_miss * (output_at > deadline),
            "output": output, "serialized_output_sha256": hashlib.sha256(serialized).hexdigest(),
            "events": traces, "decisions": decisions, "source_window_updates": updates,
            "late_drains": drains, "cache_storage": content.storage_accounting()}
