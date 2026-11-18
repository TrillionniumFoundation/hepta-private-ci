"""Structural admission for a NEW prospective B comparison, never old-run rescoring.

A digest binds declared provenance; it does not authenticate a source or establish
statistical independence. External custody/review remains an execution prerequisite.
"""

import hashlib
import json
from pathlib import Path

COSTS = (
    "model_calls",
    "verifier_calls",
    "input_tokens",
    "output_tokens",
    "training_tokens",
)


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def freeze(spec, destination):
    """Create once; callers must retain the digest outside the experiment directory."""
    validate(spec)
    frozen = {
        "plan": spec,
        "sha256": digest(spec),
        "execution_status": "NOT_READY_EXTERNAL_SOURCE_REVIEW",
    }
    with Path(destination).open("xb") as stream:
        stream.write(encoded(frozen) + b"\n")
    return frozen["sha256"]


def validate(p):
    require(p["schema"] == "hepta.prospective-b.v1", "wrong protocol")
    require(
        isinstance(p["run_id"], str) and bool(p["run_id"].strip()),
        "new run id required",
    )
    for key in (
        "source_closure",
        "runtime",
        "protocol",
        "information",
        "panel",
        "custody_review",
    ):
        require(sha(p[key]), "missing digest: " + key)
    require(p["historical_run_modified"] is False, "historical results are immutable")
    tasks = p["tasks"]
    require(isinstance(tasks, list) and len(tasks) > 0, "empty B panel")
    require(len({t["id"] for t in tasks}) == len(tasks), "duplicate task")
    prior = set(p["development_source_groups"])
    require(bool(prior), "development lineage inventory required")
    for t in tasks:
        require(isinstance(t["id"], str) and bool(t["id"]), "invalid task id")
        require(
            isinstance(t["source_group"], str) and bool(t["source_group"]),
            "source group missing",
        )
        require(t["source_group"] not in prior, "B overlaps development lineage")
        require(sha(t["content"]) and sha(t["provenance"]), "task identity missing")
        require(t["prior_model_exposure"] is False, "exposed B is not prospective")
    require(len({t["content"] for t in tasks}) == len(tasks), "duplicate content")
    require(p["panel"] == digest(tasks), "panel content changed")
    arms = p["arms"]
    require(
        set(arms) == {"initial", "candidate", "matched_control"},
        "three pinned arms required",
    )
    require(len({a["model"] for a in arms.values()}) == 3, "duplicate models")
    for a in arms.values():
        require(sha(a["model"]), "model identity missing")
        require(a["information"] == p["information"], "information differs")
        require(a["protocol"] == p["protocol"], "protocol differs")
    require(p["selection"] == "report_all_no_adoption", "selection not implemented")
    require(
        p["cost_interpretation"] == "shared_caps_not_equal_actual_cost",
        "caps are not cost matching",
    )
    require(set(p["caps"]) == set(COSTS), "all cost caps required")
    for v in p["caps"].values():
        require(type(v) is int and v >= 0, "invalid cost cap")
    require(p["maximum_attempts"] in (1, 2), "bounded attempts required")


def review(frozen, expected_digest, receipts):
    """Validate a complete new-run panel; failures stay in the denominator.

    Returns descriptive counts, never independence, equal-cost or adoption approval.
    The external expected digest must come from pre-execution custody, not this file.
    """
    p = frozen["plan"]
    validate(p)
    require(
        sha(expected_digest) and digest(p) == expected_digest == frozen["sha256"],
        "freeze changed",
    )
    expected = {(a, t["id"]) for a in p["arms"] for t in p["tasks"]}
    seen, totals, successes = set(), {}, {}
    for r in receipts:
        key = (r["arm"], r["task"])
        require(key in expected and key not in seen, "duplicate or unplanned receipt")
        seen.add(key)
        require(
            r["run_id"] == p["run_id"] and r["plan"] == expected_digest, "wrong run"
        )
        require(r["model"] == p["arms"][r["arm"]]["model"], "wrong model")
        require(
            r["protocol"] == p["protocol"] and r["panel"] == p["panel"],
            "wrong evaluation",
        )
        require(
            type(r["attempts"]) is int and 0 <= r["attempts"] <= p["maximum_attempts"],
            "attempt cap exceeded",
        )
        require(
            r["status"] in ("success", "task_failure", "rejected", "incomplete"),
            "unknown outcome",
        )
        require(
            r["status"] != "success" or (r["executed"] is True and r["attempts"] > 0),
            "unexecuted success",
        )
        require(sha(r["original_receipt"]), "original receipt missing")
        require(set(r["cost"]) == set(COSTS), "missing cost dimension")
        total = totals.setdefault(r["arm"], dict.fromkeys(COSTS, 0))
        for k, v in r["cost"].items():
            require(v is None or (type(v) is int and v >= 0), "invalid cost")
            total[k] = None if v is None or total[k] is None else total[k] + v
        successes[r["arm"]] = successes.get(r["arm"], 0) + (r["status"] == "success")
    complete = seen == expected and all(r["status"] != "incomplete" for r in receipts)
    costs_known = complete and all(
        v is not None for c in totals.values() for v in c.values()
    )
    within_caps = costs_known and all(
        v <= p["caps"][k] for c in totals.values() for k, v in c.items()
    )
    equal_vector = (
        costs_known and len({tuple(c[k] for k in COSTS) for c in totals.values()}) == 1
    )
    return {
        "plan": expected_digest,
        "complete": complete,
        "missing": sorted(expected - seen),
        "successes": successes,
        "tasks_per_arm": len(p["tasks"]),
        "costs": totals,
        "within_shared_caps": within_caps,
        "equal_measured_cost_vector": equal_vector,
        "independence_established": False,
        "full_system_cost_complete": False,
        "adoption_eligible": False,
        "execution_status": "NOT_READY_EXTERNAL_SOURCE_REVIEW",
    }
