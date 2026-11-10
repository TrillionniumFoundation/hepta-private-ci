"""Execute a frozen development roster; retain failures and interrupted work.

This runner consumes existing FP64 reference kernels. It does not admit learning
requests, verify external observations, or grant native model adoption.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from .protocol import (
    AttemptSpec,
    canonical_digest,
    source_inventory,
    summarize_attempts,
)

SEEDS = (11, 29, 47)
ROOT = Path(__file__).resolve().parents[2]
IDENTITY = ("attempt_id", "family", "method", "seed")
TERMINAL = {"completed", "failed", "cancelled"}


def inventory():
    paths = [
        path.relative_to(ROOT).as_posix() for path in Path(__file__).parent.glob("*.py")
    ]
    return source_inventory(ROOT, paths)


def write_new(path, value):
    """Create one finite JSON record without replacing an earlier observation."""
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def declared_experiments():
    from .credit_axes import credit_axes_specs, run_credit_axes_attempt
    from .learning_clocks import clock_specs, run_clock_attempt
    from .memory_replay import replay_specs, run_replay_attempt

    specs = credit_axes_specs(SEEDS) + clock_specs(SEEDS) + replay_specs(SEEDS)
    return specs, {
        "credit_axes": run_credit_axes_attempt,
        "learning_clocks": run_clock_attempt,
        "memory_replay": run_replay_attempt,
    }


def git_identity():
    result = {}
    for key, arguments in (
        ("commit", ["rev-parse", "HEAD"]),
        ("tree", ["rev-parse", "HEAD^{tree}"]),
        ("status", ["status", "--porcelain"]),
    ):
        observed = subprocess.run(
            ["git", "-C", str(ROOT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        result[key] = observed.stdout.strip() if observed.returncode == 0 else None
    return result


def _returned_result(raw, spec):
    if not isinstance(raw, dict) or raw.get("status") not in TERMINAL:
        raise ValueError("executor must return one terminal outcome")
    if not all(key in raw for key in spec) or canonical_digest(
        {key: raw[key] for key in spec}
    ) != canonical_digest(spec):
        raise ValueError("executor changed the declared full specification")


def _event(kind, binding_digest, spec, record):
    return {
        "schema": "hepta.neuroscience-attempt-event.v1",
        "kind": kind,
        "binding_digest": binding_digest,
        "spec_digest": canonical_digest(spec),
        "record": record,
        "record_digest": canonical_digest(record),
    }


def inspect_run(directory):
    """Reconcile plan, events and final source observation without execution.

    These checksums detect corruption and inconsistent records; they are not
    signatures, authenticated owner evidence, or protection against an author who
    rewrites every record and checksum. RESULT.json is a derived report, not the
    source of recovery truth. Without RUN_END the final source identity is unknown.
    """
    directory = Path(directory)
    plan = json.loads((directory / "PLAN.json").read_text(encoding="utf-8"))
    if set(plan) != {"plan", "plan_digest", "source", "git", "binding_digest"}:
        raise ValueError("unknown plan envelope")
    if plan["plan_digest"] != canonical_digest(plan["plan"]):
        raise ValueError("plan digest mismatch")
    binding = {key: plan[key] for key in ("plan", "source", "git")}
    if plan["binding_digest"] != canonical_digest(binding):
        raise ValueError("source/plan/git binding digest mismatch")
    if plan["plan"].get("schema") != "hepta.neuroscience-development-plan.v1":
        raise ValueError("unknown plan schema")
    specs = plan["plan"]["roster"]
    roster = [AttemptSpec(**{key: spec[key] for key in IDENTITY}) for spec in specs]
    summarize_attempts(roster, [])
    expected_paths = {
        canonical_digest(spec["attempt_id"]) + suffix
        for spec in specs
        for suffix in (".started.json", ".finished.json")
    }
    for path in (directory / "attempts").iterdir():
        if path.name not in expected_paths or path.is_symlink() or not path.is_file():
            raise ValueError("unplanned or nonregular attempt event")
    records, event_digests = [], {}
    for spec in specs:
        stem = canonical_digest(spec["attempt_id"])
        started = directory / "attempts" / (stem + ".started.json")
        finished = directory / "attempts" / (stem + ".finished.json")
        if finished.exists() and not started.exists():
            raise ValueError("finished outcome lacks original start event")
        parsed = {}
        for kind, path in (("started", started), ("finished", finished)):
            if not path.exists():
                continue
            event = json.loads(path.read_text(encoding="utf-8"))
            if set(event) != {
                "schema",
                "kind",
                "binding_digest",
                "spec_digest",
                "record",
                "record_digest",
            }:
                raise ValueError("unknown attempt event envelope")
            if (
                event["schema"] != "hepta.neuroscience-attempt-event.v1"
                or event["kind"] != kind
                or event["binding_digest"] != plan["binding_digest"]
            ):
                raise ValueError("attempt event type/run binding mismatch")
            if event["spec_digest"] != canonical_digest(spec):
                raise ValueError("attempt no longer matches the original plan")
            record = event["record"]
            if event["record_digest"] != canonical_digest(record):
                raise ValueError("attempt record digest mismatch")
            if canonical_digest(
                {key: record.get(key) for key in IDENTITY}
            ) != canonical_digest({key: spec[key] for key in IDENTITY}):
                raise ValueError("attempt identity mismatch")
            if kind == "started":
                expected = {**{key: spec[key] for key in IDENTITY}, "status": "running"}
                if canonical_digest(record) != canonical_digest(expected):
                    raise ValueError("start event is not an original running record")
            else:
                if record.get("status") not in TERMINAL:
                    raise ValueError("finished event is not terminal")
                raw = record.get("result")
                if raw is not None:
                    _returned_result(raw, spec)
                    if raw["status"] != record["status"] or raw.get(
                        "reason"
                    ) != record.get("reason"):
                        raise ValueError(
                            "nested outcome conflicts with terminal envelope"
                        )
            parsed[kind] = record
            event_digests[path.name] = canonical_digest(event)
        if parsed:
            records.append(parsed.get("finished", parsed["started"]))
    summary = summarize_attempts(roster, records)
    end_path = directory / "RUN_END.json"
    source_after, unchanged = None, None
    if end_path.exists():
        final = json.loads(end_path.read_text(encoding="utf-8"))
        if set(final) != {"end", "end_digest"} or final[
            "end_digest"
        ] != canonical_digest(final["end"]):
            raise ValueError("run-end digest mismatch")
        end = final["end"]
        if (
            set(end) != {"schema", "binding_digest", "source_after", "event_digests"}
            or end["schema"] != "hepta.neuroscience-run-end.v1"
            or end["binding_digest"] != plan["binding_digest"]
        ):
            raise ValueError("run-end binding mismatch")
        if end["event_digests"] != event_digests:
            raise ValueError("retained attempt events differ from run-end observation")
        source_after = end["source_after"]
        unchanged = canonical_digest(plan["source"]) == canonical_digest(source_after)
    return {
        "plan_digest": plan["plan_digest"],
        "binding_digest": plan["binding_digest"],
        "source": plan["source"],
        "source_after": source_after,
        "source_unchanged": unchanged,
        "run_end_present": end_path.exists(),
        "execution_complete": summary["complete"] and unchanged is True,
        "event_digests": event_digests,
        "attempt_summary": summary,
        "attempt_records": records,
    }


def execute(directory, specs, executors):
    """Persist the entire roster before invoking a single experiment."""
    directory = Path(directory)
    specs, executors = copy.deepcopy(specs), dict(executors)
    roster = [AttemptSpec(**{key: spec[key] for key in IDENTITY}) for spec in specs]
    summarize_attempts(roster, [])  # Reject duplicate identities before any work.
    if any(not callable(executors.get(spec.family)) for spec in roster):
        raise ValueError("missing experiment executor")
    before = inventory()
    git = git_identity()
    plan = {
        "schema": "hepta.neuroscience-development-plan.v1",
        "roster": specs,
        "scope": "synthetic_mechanism_development",
        "seeds_are_independent_real_tasks": False,
        "confirmation_data_consumed": False,
        "independent_real_task_count": 0,
        "tuning_trials": 0,
        "comparison_policy": (
            "compare paired methods within feedback timing, coverage and horizon; "
            "dense supervision is not label-budget equivalent to terminal feedback; "
            "BPTT is a full-gradient reference; clock budgets count group updates; "
            "replay budgets count actual payload timesteps"
        ),
    }
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "attempts").mkdir()
    binding = {"plan": plan, "source": before, "git": git}
    binding_digest = canonical_digest(binding)
    write_new(
        directory / "PLAN.json",
        {
            **binding,
            "plan_digest": canonical_digest(plan),
            "binding_digest": binding_digest,
        },
    )
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    interrupted = None
    for spec in specs:
        identity = {key: spec[key] for key in IDENTITY}
        stem = canonical_digest(spec["attempt_id"])
        write_new(
            directory / "attempts" / (stem + ".started.json"),
            _event("started", binding_digest, spec, {**identity, "status": "running"}),
        )
        attempt_wall, attempt_cpu = time.perf_counter(), time.process_time()
        try:
            request = copy.deepcopy(spec)
            raw = copy.deepcopy(executors[spec["family"]](request))
            if canonical_digest(request) != canonical_digest(spec):
                raise ValueError("executor mutated the frozen request")
            _returned_result(raw, spec)
            record = {
                **identity,
                "status": raw["status"],
                "reason": raw.get("reason"),
                "result": raw,
            }
            summarize_attempts([AttemptSpec(**identity)], [record])
        except BaseException as error:
            if not isinstance(error, Exception):
                interrupted = error
            record = {
                **identity,
                "status": "cancelled" if interrupted else "failed",
                "reason": type(error).__name__ + ": " + (str(error) or "<no message>"),
                "result": None,
                "partial_work_counts": None,
                "partial_work_status": "unknown_after_executor_exception",
            }
        record["execution_wall_seconds"] = time.perf_counter() - attempt_wall
        record["execution_cpu_seconds"] = time.process_time() - attempt_cpu
        write_new(
            directory / "attempts" / (stem + ".finished.json"),
            _event("finished", binding_digest, spec, record),
        )
        if interrupted:
            break
    retained = inspect_run(directory)
    after = inventory()
    end = {
        "schema": "hepta.neuroscience-run-end.v1",
        "binding_digest": binding_digest,
        "source_after": after,
        "event_digests": retained["event_digests"],
    }
    write_new(
        directory / "RUN_END.json", {"end": end, "end_digest": canonical_digest(end)}
    )
    retained = inspect_run(directory)
    complete = retained["execution_complete"]
    report = {
        "schema": "hepta.neuroscience-development-result.v1",
        "status": "DEVELOPMENT_EXECUTION_COMPLETED"
        if complete
        else "DEVELOPMENT_EXECUTION_INCOMPLETE",
        **retained,
        "git": git,
        "runtime": {
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "process_cpu_seconds": time.process_time() - started_cpu,
            "energy_joules": None,
            "measurement_window": "all attempts and event serialization; excludes setup and final report serialization",
        },
        "scientific_acceptance": "HOLD",
        "production_adoption": "not_granted",
        "independent_real_task_count": 0,
        "unclosed_gates": [
            "ordinary ACT/CTRL task collection and independent semantic evaluation",
            "native Q24 equivalence and learning owner consumption",
            "predeclared task/source-cluster confirmation with costs and old-task retention",
            "cross-process native checkpoint/CURRENT recovery and rollback",
        ],
    }
    write_new(directory / "RESULT.json", report)
    if interrupted:
        raise interrupted
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path, help="new directory; never reused")
    group.add_argument(
        "--inspect", type=Path, help="read retained outcomes without execution"
    )
    args = parser.parse_args()
    if args.inspect:
        result = inspect_run(args.inspect)
    else:
        specs, executors = declared_experiments()
        result = execute(args.output, specs, executors)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "plan_digest",
                    "binding_digest",
                    "attempt_summary",
                    "run_end_present",
                    "source_unchanged",
                    "execution_complete",
                )
            },
            sort_keys=True,
        )
    )
    return 0 if result["execution_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
