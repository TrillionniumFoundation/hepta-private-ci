#!/usr/bin/env python3
"""Prerecorded two-group LoRA clock counterbalance plan, no model training.

Actual model results require independent owner/evaluator provenance and a real
trainer consuming this exact plan.  No synthetic outcome or efficacy is emitted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import random

SCHEMA = "hpca.clock-opportunity-matched-plan.v2"
ARMS = ("interleaved", "bursty")
STEPS = 12


class PlanError(ValueError):
    pass


def _hash(record: object) -> str:
    return sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf8")).hexdigest()


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value)


@dataclass(frozen=True)
class TrainingEvent:
    event_id: str
    source_sha256: str
    input_tokens: int


@dataclass(frozen=True)
class PlannedStep:
    step: int
    group: int
    event_id: str
    source_sha256: str
    input_tokens: int


@dataclass(frozen=True)
class PairPlan:
    seed: int
    arm_order: tuple[str, str]
    interleaved: tuple[PlannedStep, ...]
    bursty: tuple[PlannedStep, ...]
    frozen_source_digest: str
    model_digest: str
    source_tree_digest: str
    plan_digest: str
    authority: str = "DENY_ALL"
    inference_status: str = "NOT_RUN"


def _schedule(arm: str) -> tuple[int, ...]:
    if arm == "interleaved":
        return (0, 1) * (STEPS // 2)
    if arm == "bursty":
        return (0, 0, 0, 1, 1, 1) * (STEPS // 6)
    raise PlanError("unregistered arm")


def _stream(seed: int, group: int, events: tuple[TrainingEvent, ...], salt: str
            ) -> tuple[TrainingEvent, ...]:
    # Fixed per-group ordered source events. The two arms only alter *when* the
    # same group receives each event; neither arm gets extra data or updates.
    rng_seed = int(_hash([SCHEMA, "stream", seed, group, salt]), 16)
    rng = random.Random(rng_seed)
    return tuple(events[rng.randrange(len(events))] for _ in range(STEPS // 2))


def _steps(arm: str, streams: tuple[tuple[TrainingEvent, ...], ...]
           ) -> tuple[PlannedStep, ...]:
    cursor = [0, 0]
    result = []
    for index, group in enumerate(_schedule(arm)):
        event = streams[group][cursor[group]]
        cursor[group] += 1
        result.append(PlannedStep(index, group, event.event_id,
                                  event.source_sha256, event.input_tokens))
    if cursor != [STEPS // 2, STEPS // 2]:
        raise PlanError("group opportunity budget mismatch")
    return tuple(result)


def verify_pair(pair: PairPlan) -> None:
    if pair.arm_order not in (("interleaved", "bursty"), ("bursty", "interleaved")):
        raise PlanError("invalid arm execution order")
    if not all(_sha(x) for x in (pair.frozen_source_digest, pair.model_digest,
                                 pair.source_tree_digest, pair.plan_digest)):
        raise PlanError("unbound plan identity")
    for arm in ARMS:
        steps = getattr(pair, arm)
        if len(steps) != STEPS or tuple(x.group for x in steps) != _schedule(arm):
            raise PlanError("wrong clock pattern or number of updates")
        if tuple(x.step for x in steps) != tuple(range(STEPS)):
            raise PlanError("noncanonical step order")
        for step in steps:
            if not step.event_id or not _sha(step.source_sha256) or (
                type(step.input_tokens) is not int or step.input_tokens < 1
            ):
                raise PlanError("invalid source event")
    for group in (0, 1):
        left = tuple((s.event_id, s.source_sha256, s.input_tokens)
                     for s in pair.interleaved if s.group == group)
        right = tuple((s.event_id, s.source_sha256, s.input_tokens)
                      for s in pair.bursty if s.group == group)
        if left != right or len(left) != STEPS // 2:
            raise PlanError("group source exposure or optimizer writes unequal")
    expected = _hash({key: value for key, value in asdict(pair).items()
                      if key != "plan_digest"})
    if expected != pair.plan_digest:
        raise PlanError("stale plan digest or tampered metadata")


def make_cohort(seeds: tuple[int, ...], events: tuple[TrainingEvent, ...], *,
                model_digest: str, source_tree_digest: str,
                randomization_salt: str) -> tuple[PairPlan, ...]:
    """Return exact, fixed opportunity plans. Does not execute training.

    Even seed counts are required to give equal AB/BA order allocations;
    the salt must be committed before observing model outcomes. Dataset and
    model digests remain declarations, not authentication or independent data.
    """
    if (len(seeds) < 2 or len(seeds) % 2 or len(set(seeds)) != len(seeds)
            or any(type(s) is not int or s < 0 for s in seeds)):
        raise PlanError("need distinct, nonnegative, even number of paired seeds")
    if (not events or len(events) > 65536
            or len({x.event_id for x in events}) != len(events)
            or any(not e.event_id or not _sha(e.source_sha256)
                   or type(e.input_tokens) is not int or e.input_tokens < 1
                   for e in events)):
        raise PlanError("invalid training event inventory")
    if (not _sha(model_digest) or not _sha(source_tree_digest)
            or not randomization_salt or len(randomization_salt) > 128):
        raise PlanError("missing frozen model/source or randomization salt")
    events = tuple(sorted(events, key=lambda e: e.event_id))
    inventory_digest = _hash([asdict(e) for e in events])
    # Seed-order labels are assigned by a single pre-committed permutation,
    # not by whichever arm happens to finish first or yields the better score.
    ranked = sorted(seeds, key=lambda s: (_hash([SCHEMA, "order", randomization_salt, s]), s))
    order = {s: ARMS if i % 2 == 0 else tuple(reversed(ARMS))
             for i, s in enumerate(ranked)}
    results = []
    for seed in sorted(seeds):
        streams = tuple(_stream(seed, group, events, randomization_salt)
                        for group in (0, 1))
        data = dict(seed=seed, arm_order=order[seed],
                    interleaved=_steps("interleaved", streams),
                    bursty=_steps("bursty", streams),
                    frozen_source_digest=inventory_digest,
                    model_digest=model_digest,
                    source_tree_digest=source_tree_digest,
                    authority="DENY_ALL", inference_status="NOT_RUN")
        pair = PairPlan(**data, plan_digest=_hash({
            key: [asdict(v) for v in value] if key in ARMS else value
            for key, value in data.items()
        }))
        verify_pair(pair)
        results.append(pair)
    return tuple(results)
