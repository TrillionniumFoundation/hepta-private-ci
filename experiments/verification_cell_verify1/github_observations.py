"""Describe saved provider jobs; these receipts grant no evaluator authority.

Hashes bind supplied bytes, not provider authentication or capture chronology.
Provider outcomes are not independently adjudicated terminal business labels.
"""

import argparse
from collections import Counter
import hashlib
import json
from io import StringIO
from itertools import islice
from pathlib import Path
import re

SCHEMA = "hepta.verify.github-observations.v1"
RULE = "success_vs_failure_or_timeout_other_unknown"
ACTIVE = ("queued", "in_progress", "waiting", "pending", "requested")
STEPS = ("pending", "in_progress", "completed", "queued", "waiting")
CONCLUSIONS = (
    "success",
    "failure",
    "timed_out",
    "cancelled",
    "skipped",
    "neutral",
    "action_required",
    "stale",
    "startup_failure",
)
FEATURES = (
    tuple("job_" + s for s in ACTIVE)
    + ("steps_available", "step_count")
    + tuple("steps_" + s for s in STEPS)
)
IDENTITY = {"repository", "head_sha", "run_id", "run_attempt", "job_id"}
ENVELOPE = (IDENTITY - {"job_id"}) | {"observation_index", "payload", "payload_sha256"}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _positive(value):
    return type(value) is int and 0 < value <= 2**63 - 1


def _identity(row):
    _require(
        type(row["repository"]) is str
        and len(row["repository"]) <= 256
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", row["repository"])
        is not None,
        "invalid repository",
    )
    _require(
        type(row["head_sha"]) is str
        and re.fullmatch("[0-9a-f]{40}", row["head_sha"]) is not None,
        "invalid source head",
    )
    _require(
        _positive(row["run_id"])
        and (row["run_attempt"] is None or _positive(row["run_attempt"])),
        "invalid run/attempt",
    )
    return tuple(row[k] for k in ("repository", "head_sha", "run_id", "run_attempt"))


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON: " + value)


def strict_json(raw):
    _require(
        type(raw) is str
        and 0 < len(raw) <= 1_000_000
        and len(raw.encode()) <= 1_000_000,
        "bounded original JSON required",
    )
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    _canonical(value)
    return value


def _job(job, scope):
    _require(
        type(job) is dict
        and _positive(job.get("id"))
        and type(job.get("run_id")) is int
        and job["run_id"] == scope[2],
        "job/run binding changed",
    )
    _require(
        {"head_sha", "run_attempt", "url"} <= job.keys()
        and _positive(job["run_attempt"]),
        "full provider identity required",
    )
    for name, expected in (("head_sha", scope[1]), ("run_attempt", scope[3])):
        if name in job and expected is not None:
            _require(
                type(job[name]) is type(expected) and job[name] == expected,
                "provider " + name + " changed",
            )
    if "url" in job:
        expected_url = (
            f"https://api.github.com/repos/{scope[0]}/actions/jobs/{job['id']}"
        )
        _require(job["url"] == expected_url, "provider repository URL changed")
    status, conclusion = job.get("status"), job.get("conclusion")
    _require(status in ACTIVE + ("completed",), "unsupported job status")
    _require(
        conclusion in CONCLUSIONS if status == "completed" else conclusion is None,
        "invalid conclusion",
    )
    steps = job.get("steps")
    _require(
        steps is None or type(steps) is list and len(steps) <= 1000, "invalid step list"
    )
    counts = Counter()
    for step in steps or []:
        _require(
            type(step) is dict and step.get("status") in STEPS, "invalid step status"
        )
        counts[step["status"]] += 1
    features = (
        [int(status == name) for name in ACTIVE]
        + [int(steps is not None), len(steps or [])]
        + [counts[name] for name in STEPS]
    )
    return status, conclusion, features


def evaluate_saved(plan, envelopes):
    """Keep every frozen job and explicit UNKNOWN terminal outcomes."""
    _require(
        type(plan) is dict and set(plan) == {"schema", "label_rule", "roster"},
        "plan fields changed",
    )
    _require(
        plan["schema"] == SCHEMA and plan["label_rule"] == RULE,
        "unsupported target rule",
    )
    _require(
        type(plan["roster"]) is list and 0 < len(plan["roster"]) <= 128,
        "bounded roster required",
    )
    roster, scopes = {}, {}
    for row in plan["roster"]:
        _require(
            type(row) is dict and set(row) == IDENTITY and _positive(row["job_id"]),
            "invalid roster identity",
        )
        scope = _identity(row)
        _require(row["job_id"] not in roster, "duplicate frozen job")
        roster[row["job_id"]] = dict(row)
        scopes.setdefault(scope, set()).add(row["job_id"])
    _require(
        type(envelopes) is list and 0 < len(envelopes) <= 256,
        "bounded envelopes required",
    )
    observations, terminal, seen, receipts = {}, {}, set(), []
    previous, total = 0, 0
    for envelope in envelopes:
        _require(
            type(envelope) is dict and set(envelope) == ENVELOPE,
            "envelope fields changed",
        )
        index = envelope["observation_index"]
        _require(_positive(index) and index > previous, "capture order changed")
        previous, scope = index, _identity(envelope)
        _require(scope in scopes, "unplanned source/head/run/attempt")
        raw = envelope["payload"]
        payload = strict_json(raw)
        total += len(raw.encode())
        _require(
            total <= 16_000_000 and envelope["payload_sha256"] == _sha(raw.encode()),
            "payload byte/hash bound changed",
        )
        _require(
            type(payload) is dict
            and type(payload.get("jobs")) is list
            and len(payload["jobs"]) <= 1000,
            "bounded jobs payload required",
        )
        jobs = {}
        for job in payload["jobs"]:
            value = _job(job, scope)
            _require(job["id"] not in jobs, "duplicate provider job")
            jobs[job["id"]] = value
        if scope not in seen:
            _require(scopes[scope] <= jobs.keys(), "initial snapshot omits planned job")
            _require(
                all(jobs[key][0] != "completed" for key in scopes[scope]),
                "initial snapshot already terminal",
            )
        seen.add(scope)
        receipt = {
            "observation_index": index,
            "payload_sha256": envelope["payload_sha256"],
            "payload_bytes": len(raw.encode()),
        }
        receipts.append(receipt)
        for key in scopes[scope] & jobs.keys():
            status, conclusion, features = jobs[key]
            if key in terminal:
                _require(
                    status == "completed" and conclusion == terminal[key]["conclusion"],
                    "terminal outcome changed or reopened",
                )
            elif status == "completed":
                terminal[key] = dict(conclusion=conclusion, **receipt)
            else:
                observations.setdefault(key, []).append(
                    dict(features=features, **receipt)
                )
    _require(seen == set(scopes), "no initial snapshot for planned source")
    rows = []
    for key, identity in roster.items():
        endpoint = terminal.get(key)
        conclusion = endpoint["conclusion"] if endpoint else None
        error = (
            False
            if conclusion == "success"
            else True
            if conclusion in ("failure", "timed_out")
            else None
        )
        rows.append(
            dict(
                identity=identity,
                source_group=list(_identity(identity)),
                observations=observations[key],
                terminal_receipt=endpoint,
                provider_target_error=error,
                label_status="KNOWN_PROVIDER_TARGET"
                if error is not None
                else "UNKNOWN",
                attempt_identity_verified=False,
            )
        )
    known = sum(row["provider_target_error"] is not None for row in rows)
    return dict(
        schema=SCHEMA,
        plan_sha256=_sha(_canonical(plan).encode()),
        label_rule=RULE,
        feature_names=list(FEATURES),
        input_schema_sha256=_sha(_canonical(FEATURES).encode()),
        planned_jobs=len(rows),
        jobs_with_preterminal_observations=len(observations),
        known_provider_labels=known,
        unknown_provider_labels=len(rows) - known,
        rows=rows,
        receipts=receipts,
        identity_binding="caller envelope matched to full payload job/run/head/attempt/URL; authentication not established",
        chronology_authenticated=False,
        provider_authentication_established=False,
        evaluator_independence_established=False,
        source_independence_established=False,
        new_independent_real_tasks=0,
        model_fits_executed=0,
        model_predictions_executed=0,
        actor_executions=0,
        signed_journal_labels_created=0,
        scientific_admission="HOLD",
        production_authority="NONE",
        learning_decision="NoUpdate",
    )


def _read(path, limit):
    _require(path.is_file() and not path.is_symlink(), "regular direct input required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit, "input exceeds byte bound")
    return raw.decode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    for name in ("plan", "envelopes", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    plan = strict_json(_read(args.plan, 65536))
    lines = list(islice(StringIO(_read(args.envelopes, 17_000_000)), 257))
    _require(len(lines) <= 256, "envelope row bound exceeded")
    envelopes = [strict_json(line) for line in lines]
    result = evaluate_saved(plan, envelopes)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(_canonical(result) + "\n")


if __name__ == "__main__":
    main()
