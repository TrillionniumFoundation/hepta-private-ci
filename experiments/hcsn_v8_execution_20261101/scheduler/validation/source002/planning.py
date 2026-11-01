"""Bounded same-target planning over publicly visible causal content.

This is an executable development interface. It does not authorize confirmation
or certify that supplied forecast adapters have been fitted or calibrated.
"""

from dataclasses import dataclass

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import (
    BackendKind, ContractError, CorrectnessValue, CostWeights, Modality,
    StopEvaluation, finite, identity,
)


@dataclass(frozen=True, slots=True)
class Read:
    modality: Modality
    prefix_end: int

    def __post_init__(self):
        if not isinstance(self.modality, Modality):
            raise ContractError("Unknown read modality")
        if type(self.prefix_end) is not int or self.prefix_end <= 0:
            raise ContractError("Read prefix must be a positive integer")

    @property
    def identity(self):
        return f"READ:{self.modality.value}:{self.prefix_end}"


@dataclass(frozen=True, slots=True)
class Wait:
    seconds: float

    def __post_init__(self):
        object.__setattr__(self, "seconds", finite(self.seconds, "wait", 1e-9, 60))

    @property
    def identity(self):
        return f"WAIT:{self.seconds:.17g}"


@dataclass(frozen=True, slots=True)
class Plan:
    steps: tuple

    def __post_init__(self):
        object.__setattr__(self, "steps", tuple(self.steps))
        if not 1 <= len(self.steps) <= 6 or any(type(s) not in (Read, Wait) for s in self.steps):
            raise ContractError("Plans require one to six READ/WAIT steps")

    @property
    def identity(self):
        return "/".join(s.identity for s in self.steps)

    @property
    def requested_reads(self):
        return sum(type(s) is Read for s in self.steps)


@dataclass(frozen=True, slots=True)
class ServiceEstimate:
    additional_seconds: float
    deadline_miss_probability: float

    def __post_init__(self):
        object.__setattr__(self, "additional_seconds", finite(self.additional_seconds, "duration", 0))
        object.__setattr__(self, "deadline_miss_probability", finite(
            self.deadline_miss_probability, "deadline risk", 0, 1))


def validate_plan(content, plan, horizon=6):
    if not isinstance(plan, Plan) or not 1 <= len(plan.steps) <= horizon:
        raise ContractError("Plan exceeds declared horizon")
    levels = {m: content.level(m) for m in Modality}
    prior_wait = False
    for step in plan.steps:
        if type(step) is Wait:
            if prior_wait:
                raise ContractError("Adjacent waits must be one bounded wait")
            prior_wait = True
            continue
        prior_wait = False
        if step.prefix_end != levels[step.modality] + 1 or step.prefix_end > content.budget.max_prefix_end:
            raise ContractError("Plan skips or repeats a source prefix")
        levels[step.modality] = step.prefix_end
    if len(content.accepted_event_ids) + plan.requested_reads > content.budget.max_events:
        raise ContractError("Plan exceeds the common event budget")


def enumerate_plans(content, horizon=2, wait_seconds=()):
    """No service outcomes, future payloads, object labels or model state needed."""
    if type(horizon) is not int or not 1 <= horizon <= 6:
        raise ContractError("Planning horizon must be one to six")
    waits = tuple(Wait(x) for x in wait_seconds)
    if len(waits) > 2 or len({w.seconds for w in waits}) != len(waits):
        raise ContractError("At most two distinct public wait choices are allowed")
    result = []
    frontier = [()]
    for _ in range(horizon):
        new_frontier = []
        for steps in frontier:
            levels = {m: content.level(m) for m in Modality}
            for step in steps:
                if type(step) is Read:
                    levels[step.modality] = step.prefix_end
            candidates = [Read(m, int(levels[m]) + 1) for m in Modality
                          if levels[m] < content.budget.max_prefix_end]
            if not steps or type(steps[-1]) is not Wait:
                candidates += list(waits)
            for candidate in candidates:
                plan = Plan(steps + (candidate,))
                if len(content.accepted_event_ids) + plan.requested_reads > content.budget.max_events:
                    continue
                result.append(plan)
                new_frontier.append(plan.steps)
                if len(result) > 1024:
                    raise ContractError("Too many public plan alternatives")
        frontier = new_frontier
    return tuple(result)


def choose_plan(content, state, head, forecast, service_model, plans, now, deadline,
                costs=CostWeights()):
    """Commit the chosen complete path; no unpriced replanning within the path.

    A forecast predicts correctness after this exact path, including its stated
    timeout rule. Fees/risk/elapsed are deducted once, here. STOP wins ties.
    """
    now = finite(now, "current time", content.last_accepted_at)
    deadline = finite(deadline, "deadline", 0)
    identity(forecast.reader_id, "Forecast identity")
    if forecast.kind == BackendKind.CORE:
        if state is None or state.content_fingerprint != content.fingerprint():
            raise ContractError("Core state does not match visible content")
    elif forecast.kind != BackendKind.DIRECT_HISTORY or state is not None:
        raise ContractError("Direct-history forecasts cannot consume a core state")
    plans = tuple(plans)
    if len(plans) > 1024 or len({p.identity for p in plans}) != len(plans):
        raise ContractError("Duplicated or unbounded plan alternatives")
    for plan in plans:
        validate_plan(content, plan)
    stop = head.evaluate(content)
    if not isinstance(stop, StopEvaluation):
        raise ContractError("Common head must return a validated STOP evaluation")
    stop_value = stop.calibrated_correctness.probability - costs.deadline_miss * (now > deadline)
    scores = []
    if now < deadline:
        for plan in plans:
            future = forecast.evaluate(content, state, plan)
            if not isinstance(future, CorrectnessValue):
                raise ContractError("Forecast must return validated common-head correctness")
            if future.head_id != stop.calibrated_correctness.head_id:
                raise ContractError("Current/future correctness target different heads")
            if plan.requested_reads == 0 and future.probability != stop.calibrated_correctness.probability:
                raise ContractError("WAIT cannot change time-independent common-head correctness")
            service = service_model.estimate(content, plan, now, deadline)
            if not isinstance(service, ServiceEstimate):
                raise ContractError("Service model returned an invalid estimate")
            score = (future.probability - costs.observation * plan.requested_reads
                     - costs.elapsed_second * service.additional_seconds
                     - costs.deadline_miss * service.deadline_miss_probability)
            scores.append({"plan": plan.identity, "correctness": future.probability,
                           "requested_reads": plan.requested_reads,
                           "expected_seconds": service.additional_seconds,
                           "deadline_miss_probability": service.deadline_miss_probability,
                           "score": score, "increment_over_stop": score - stop_value})
    best = max(zip(plans, scores), key=lambda item: (item[1]["score"], item[0].identity), default=None)
    selected = best[0] if best is not None and best[1]["score"] > stop_value else None
    return selected, {"stop_score": stop_value, "plans": scores,
                      "selected": None if selected is None else selected.identity,
                      "backend": forecast.kind.value, "reader_id": forecast.reader_id,
                      "content_fingerprint": content.fingerprint()}
