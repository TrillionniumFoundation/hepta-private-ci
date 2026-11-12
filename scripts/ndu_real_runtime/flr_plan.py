"""Frozen F/L/R opportunities and source partitions; declarations grant no trust."""

from ._causal_checks import COST_UNITS, _fields, _number, _pin, _require, _text


ARMS = ("F", "L", "R")


def validate_plan(plan):
    """Reject unmatched or leaking designs before dispatch or reading outcomes."""
    _fields(plan, (
        "schema", "campaign_id", "source", "initial_model", "initial_learner",
        "generations", "information", "budget", "minimum_gain", "sources",
        "schedule", "audit_sources", "evaluation_owner", "ordinary_entrypoint",
    ), "FLR_PLAN_FIELDS")
    _require(plan["schema"] == "hepta.flr.plan.v1", "FLR_PLAN_SCHEMA")
    _fields(plan["source"], ("commit", "tree"), "FLR_SOURCE_FIELDS")
    _require(all(_pin(value, 40) for value in plan["source"].values()), "FLR_SOURCE_PIN")
    _require(all(_text(plan[key]) for key in (
        "campaign_id", "evaluation_owner", "ordinary_entrypoint",
    )), "FLR_PLAN_IDENTITY")
    _require(all(_pin(plan[key]) for key in (
        "initial_model", "initial_learner", "information",
    )), "FLR_INITIAL_PINS")
    n = plan["generations"]
    _require(type(n) is int and 2 <= n <= 32, "FLR_GENERATIONS")
    _require(_number(plan["minimum_gain"], minimum=0), "FLR_GAIN_THRESHOLD")
    budget = plan["budget"]
    _fields(budget, ("candidate_attempts", "learner_trials", "b_queries", "limits"), "FLR_BUDGET_FIELDS")
    for key, maximum in (("candidate_attempts", 64), ("learner_trials", 64), ("b_queries", 8192)):
        _require(type(budget[key]) is int and 0 < budget[key] <= maximum,
                 "FLR_QUERY_BUDGET")
    _fields(budget["limits"], COST_UNITS, "FLR_BUDGET_UNITS")
    _require(all(_number(value, minimum=0) and value > 0
                 for value in budget["limits"].values()), "FLR_BUDGET_LIMIT")
    sources, groups, digests = plan["sources"], {}, {}
    _require(isinstance(sources, dict) and 4 <= len(sources) <= 8192,
             "FLR_SOURCE_REGISTRY")
    for identity, source in sources.items():
        _fields(source, ("group", "split", "digest"), "FLR_SOURCE_FIELDS")
        _require(_text(identity) and _text(source["group"])
                 and source["split"] in ("A", "B", "C", "D")
                 and _pin(source["digest"]), "FLR_SOURCE_IDENTITY")
        group, split, digest = (source[key] for key in ("group", "split", "digest"))
        _require(groups.setdefault(group, split) == split, "FLR_SOURCE_GROUP_LEAKAGE")
        _require(digests.setdefault(digest, (group, split)) == (group, split),
                 "FLR_SOURCE_DIGEST_ALIAS")
    _require(isinstance(plan["schedule"], list) and len(plan["schedule"]) == n,
             "FLR_FIXED_HORIZON")
    used, future = set(), set()
    schedules = [*plan["schedule"], {"D": plan["audit_sources"]}]
    for index, schedule in enumerate(schedules):
        _fields(schedule, ("D",) if index == n else ("A", "B", "C"),
                "FLR_SCHEDULE_FIELDS")
        for split, ids in schedule.items():
            _require(isinstance(ids, list) and ids and all(_text(x) for x in ids)
                     and len(set(ids)) == len(ids), "FLR_SCHEDULE_SOURCES")
            _require(all(x in sources and sources[x]["split"] == split for x in ids),
                     "FLR_SPLIT_BINDING")
            used.update(ids)
            if split in ("C", "D"):
                pins = {sources[x]["digest"] for x in ids}
                _require(len(pins) == len(ids) and not pins & future,
                         "FLR_REUSED_FUTURE_SAMPLE")
                future.update(pins)
    _require(used == set(sources), "FLR_UNSCHEDULED_SOURCE")
    return plan


def source_mean(scores, sources):
    """Weight original declared groups equally, never seeds, replays or rows."""
    grouped = {}
    for identity, score in scores.items():
        source = sources[identity]
        grouped.setdefault(source["group"], {}).setdefault(source["digest"], []).append(score)
    means = []
    for digests in grouped.values():
        means.append(sum(sum(values) / len(values) for values in digests.values()) / len(digests))
    return sum(means) / len(means) if means else None
