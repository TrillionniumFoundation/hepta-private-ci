"""Actor-only document acquisition with measured local time and byte costs.

No evaluator is accepted. Global/dense fixed/active use the existing trace
contract; OCR-only, direct ROI and random retain explicit comparator records.
"""

import re
import time

from . import acquisition
from .document_collector import Collector as Collector
from .document_collector import _micros
from .document_collector import regions_for as regions_for
from .experiment import actor_context, communication_cost, validate_trace
from .schema import Cost, Invalid, PHASES, canonical, require, sha

CAP = 4_000_000
READ_QUOTE = 2_000_000


def _target(dataset, episode):
    match = re.search(r"\brectangle\s*\((\d+),(\d+),(\d+),(\d+)\)", episode["task"])
    require(match is not None, "task must explicitly declare its public rectangle")
    x, y, width, height = map(int, match.groups())
    loc = dict(dataset.sources[episode["initial_ids"][0]]["locator"])
    require(
        loc["kind"] == "image"
        and width > 0
        and height > 0
        and x + width <= loc["width"]
        and y + height <= loc["height"],
        "task rectangle escapes its document",
    )
    return dict(loc, x0=x, y0=y, x1=x + width, y1=y + height)


def overlap(source, target):
    """Fraction of a public target rectangle covered by a registered source."""
    a, b = source.get("locator", source), target.get("locator", target)
    if a["origin_sha256"] != b["origin_sha256"]:
        return 0.0
    area = (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])
    require(area > 0, "empty task rectangle")
    return (
        max(0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
        * max(0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    ) / area


def terminal(dataset, episode, observations):
    """Transcribe the last acquired source fully covering the public task ROI."""
    target = _target(dataset, episode)
    selected = next(
        (
            item
            for item in reversed(observations)
            if overlap(dataset.sources[item["source_id"]], target) == 1.0
        ),
        None,
    )
    text = selected["ocr"]["text"] if selected else ""
    return {
        "text": text,
        "fields": {"selected_word": text},
        "evidence_ids": [selected["source_id"]] if selected else [],
    }


def public_features(
    dataset, episode, acquired, candidate_id, prefix, budget, representation
):
    """Only public geometry and already acquired OCR/latent evidence enter here."""
    require(
        representation in ("global", "dense") and acquired,
        "initial observation required",
    )
    require(candidate_id in episode["source_ids"], "candidate outside episode")
    target, candidate = _target(dataset, episode), dataset.sources[candidate_id]
    loc = candidate["locator"]
    covered = [
        item
        for item in acquired
        if overlap(dataset.sources[item["source_id"]], target) == 1.0
    ]
    confidence = covered[-1]["ocr"]["confidence"] if covered else 0.0
    initial = acquired[0]["observation"]
    require(
        acquired[0]["encoded"] and acquired[0]["representation"] == representation,
        "acquisition features require matching executed initial encoder",
    )
    value = {
        "schema": "perc1.acquisition-features.v1",
        "prefix_sha256": prefix if type(prefix) is str else sha(prefix),
        "task_goal": [
            overlap(candidate, target),
            (loc["x0"] - target["x0"]) / loc["width"],
            (loc["y0"] - target["y0"]) / loc["height"],
            (loc["x1"] - loc["x0"]) / loc["width"],
            (loc["y1"] - loc["y0"]) / loc["height"],
        ],
        "coverage": max(
            overlap(dataset.sources[item["source_id"]], target) for item in acquired
        ),
        "source_repeat": float(
            any(
                candidate["sha256"] == dataset.sources[item["source_id"]]["sha256"]
                for item in acquired
            )
        ),
        "remaining_budget": budget,
        "uncertainty": 1.0 - confidence / 100.0,
        "acquired_latent": [v for token in initial["tokens"] for v in token["values"]],
        "acquired_receipt_sha256s": [item["receipt_sha256"] for item in acquired],
    }
    acquisition.features(value)
    return value


def execute(collector, episode, representation, mode, manifest, head, random_seed=0):
    """Acquire the common initial view and at most one quoted continuation."""
    require(
        mode in ("active", "fixed", "random", "direct_roi", "ocr_only"),
        "unknown actor mode",
    )
    require(
        manifest["budget"]["cap"] == CAP and len(episode["initial_ids"]) == 1,
        "document protocol requires one initial view and the frozen cap",
    )
    neural, formal = mode not in ("direct_roi", "ocr_only"), mode in ("active", "fixed")
    dataset, tariff = collector.dataset, manifest["budget"]["tariff"]
    steps, acquired, decisions = [], [], []
    spent, answer_value = 0, None
    seed = manifest["controller"]["training_runs"][0]["seed"]
    for attempt in range(3):
        started = time.perf_counter_ns()
        prefix = actor_context(dataset, episode, steps)
        plan_start = time.perf_counter_ns()
        if attempt == 0 and mode == "direct_roi":
            remaining = [
                s for s in episode["source_ids"] if s not in episode["initial_ids"]
            ]
            require(
                remaining,
                "direct ROI requires a registered original-resolution candidate",
            )
            candidate = max(
                remaining,
                key=lambda item: overlap(
                    dataset.sources[item], _target(dataset, episode)
                ),
            )
            selected = {"action": "ACQUIRE", "candidate_id": candidate}
        elif attempt == 0:
            selected = {"action": "ACQUIRE", "candidate_id": episode["initial_ids"][0]}
        elif attempt == 2 or mode in ("ocr_only", "direct_roi"):
            selected = {"action": "STOP", "candidate_id": None}
        else:
            remaining = [
                s for s in episode["source_ids"] if s not in episode["initial_ids"]
            ]
            candidates = [
                {
                    "id": item,
                    "upper_cost": READ_QUOTE,
                    "features": public_features(
                        dataset,
                        episode,
                        acquired,
                        item,
                        prefix,
                        CAP - spent,
                        representation,
                    ),
                }
                for item in remaining
            ]
            selected = acquisition.choose(head, candidates, mode=mode, seed=random_seed)
        planning_ns = time.perf_counter_ns() - plan_start
        costs = dict.fromkeys(PHASES, 0)
        costs["planning"] = _micros(planning_ns) * tariff["planning"]
        costs["decision"] = (
            _micros(time.perf_counter_ns() - started - planning_ns) * tariff["decision"]
        )
        source_id, item, observation = selected["candidate_id"], None, None
        proposal = (
            None
            if source_id is None
            else {
                "source_id": source_id,
                "operation": "acquire",
                "reason": "public geometry and acquired evidence; bounded document protocol",
                "estimated_gain": 0.0,
            }
        )
        status = "stopped" if source_id is None else "observed"
        quote = (
            READ_QUOTE
            if source_id
            else max(
                1, sum(costs.values()) + communication_cost(None, None, status, tariff)
            )
        )
        if source_id and quote > CAP - spent:
            status = "budget_denied"
        elif source_id:
            item = collector.observe(source_id, representation, encode=neural)
            acquired.append(item)
            observation = item["observation"]
            for phase, amount in collector.accounted_cost(item).items():
                costs[phase] += amount * tariff[phase]
        costs["communication"] += communication_cost(
            proposal, observation, status, tariff
        )
        if status in ("stopped", "budget_denied"):
            terminal_start = time.perf_counter_ns()
            answer_value = terminal(dataset, episode, acquired)
            costs["decision"] += (
                _micros(time.perf_counter_ns() - terminal_start) * tariff["decision"]
            )
            if status == "stopped":
                quote = max(1, sum(costs.values()))
        finished = (
            observation["observed_ns"]
            if observation is not None
            else time.perf_counter_ns()
        )
        billing = {
            "observation_receipt_sha256": item["receipt_sha256"] if item else None,
            "cost": costs,
            "quote": quote,
            "status": status,
            "planning_ns": planning_ns,
        }
        decisions.append(
            {"prefix_sha256": sha(prefix), "selection": selected, "billing": billing}
        )
        step = {
            "attempt_id": f"document-{attempt}",
            "input_sha256": sha(prefix),
            "proposal": proposal,
            "status": status,
            "reservation": quote,
            "cost": costs,
            "billing_receipt_sha256": sha(billing),
            "started_ns": started,
            "finished_ns": finished,
            "observation": observation,
        }
        steps.append(step)
        actual = Cost.parse(costs).total
        if actual > quote or actual > CAP - spent:
            failure = {
                "schema": "perc1.document-budget-overrun.v1",
                "episode_id": episode["id"],
                "mode": mode,
                "quote": quote,
                "actual": actual,
                "prior_spent": spent,
                "steps": steps,
                "decisions": decisions,
                "scientific_qualified": False,
            }
            (
                collector.output / ("budget-overrun-" + sha(failure) + ".json")
            ).write_bytes(canonical(failure) + b"\n")
            raise Invalid("measured cost exceeded reservation; full failure retained")
        spent += actual
        if status in ("stopped", "budget_denied"):
            break
    trace = {
        "schema": "perc1.trace.v1" if formal else "perc1.document-comparator.v1",
        "manifest_sha256": sha(manifest),
        "episode_id": episode["id"],
        "seed": seed,
        "arm": representation + "_" + mode,
        "steps": steps,
        "answer": answer_value,
    }
    if formal:
        validate_trace(trace, manifest, dataset)
    else:
        trace.update(
            comparator=mode,
            valid_native_trace=False,
            encoder_executed=neural,
            fixed_schedule_claim=False,
        )
    result = {
        "mode": mode,
        "representation": representation,
        "trace": trace,
        "spent": spent,
        "decisions": decisions,
        "receipt_sha256s": [item["receipt_sha256"] for item in acquired],
        "valid_native_trace": formal,
    }
    (collector.output / ("execution-" + sha(result) + ".json")).write_bytes(
        canonical(result) + b"\n"
    )
    return result
