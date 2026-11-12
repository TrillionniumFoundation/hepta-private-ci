"""Publishable, answer-free CORD synthesis from frozen reports and raw results.

Never opens annotations, images or OCR; publishes equality only and stays HOLD.
"""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

METRICS = ("inclusive_wall_ns", "process_cpu_ns", "terminated_child_cpu_ns")
STATUSES = ("COMPLETED", "UNKNOWN", "FAILED", "CANCELLED")
COMPARISONS = {
    "learned_vs_zero_visual": ("learned", "zero_visual"),
    "learned_vs_fixed_selection": ("learned", "fixed_selection"),
    "fixed_selection_vs_fixed_region": ("fixed_selection", "fixed_region"),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path, expected=None):
    require(path.is_file() and not path.is_symlink(), "regular report required")
    require(0 < path.stat().st_size <= 8 * 1024 * 1024, "report byte bound")
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    require(len(raw) <= 8 * 1024 * 1024, "report grew beyond byte bound")
    pin = hashlib.sha256(raw).hexdigest()
    require(expected is None or pin == expected, "raw SHA mismatch: " + path.name)

    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda _: require(False, "nonfinite JSON"),
    )
    return value, pin


def total(values):
    for value in values:
        require(
            value is None
            or (type(value) in (int, float) and math.isfinite(value) and value >= 0),
            "invalid measured cost",
        )
    return sum(values) if all(v is not None for v in values) else None


def statistics(rows):
    return dict(
        tasks=len(rows),
        statuses={s: sum(r["status"] == s for r in rows) for s in STATUSES},
        correct=sum(r["quality"] == 1 for r in rows),
        unknown_quality=sum(r["quality"] is None for r in rows),
        quality_mean=sum(r["quality"] for r in rows) / len(rows)
        if all(r["quality"] is not None for r in rows)
        else None,
        totals={k: total([r.get("cost", {}).get(k) for r in rows]) for k in METRICS},
    )


def validate_result(record, row):
    require(
        record["status"] == row["status"] and record["status"] in STATUSES,
        "result status mismatch",
    )
    quality = row["quality"]
    require(
        quality is None or (type(quality) in (int, float) and quality in (0, 1)),
        "invalid terminal quality",
    )
    require(
        record["status"] == "COMPLETED" or quality is None, "failure quality invented"
    )


def pilot(args):
    report, report_pin = read(args.pilot / "REPORT.json", args.report_sha256)
    done, done_pin = read(args.pilot / "ACTOR_DONE.json", args.actor_done_sha256)
    plan, plan_pin = read(args.pilot / "PLAN.json", done["plan_file_sha256"])
    require(report["schema"] == "perc1.cord-pilot-report.v1", "wrong pilot report")
    require(
        done["all_results_retained"] and done["source_unchanged"], "incomplete pilot"
    )
    require(
        report["scientific_status"] == "HOLD"
        and report["measured_net_benefit"] is None,
        "unexpected pilot qualification",
    )
    arms, tasks = plan["arms"], {r["task_id"] for r in done["results"]}
    require(len(tasks) == 12 and len(set(arms)) == len(arms), "fixed panel changed")
    for name in list(tasks) + arms:
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name), "unsafe ID")
    expected = {(task, arm) for task in tasks for arm in arms}

    def key(row):
        return row["task_id"], row["arm"]

    for rows in (done["results"], report["rows"]):
        require(
            len(rows) == len(expected) and {key(r) for r in rows} == expected,
            "incomplete or duplicate paired roster",
        )
    scored = {key(r): r for r in report["rows"]}
    records = {}
    for entry in done["results"]:
        task, arm = key(entry)
        record, pin = read(
            args.pilot / "results" / f"{task}-{arm}.json", entry["sha256"]
        )
        row = scored[(task, arm)]
        require(
            key(record) == (task, arm)
            and record["seed"] == plan["seed"]
            and row["actor_sha256"] == pin
            and row["status"] == entry["status"],
            "actor binding mismatch",
        )
        validate_result(record, row)
        require(
            row["inclusive_wall_ns"] == record.get("cost", {}).get("inclusive_wall_ns"),
            "report cost differs from original",
        )
        records[(task, arm)] = {**record, "quality": row["quality"]}
    return (
        records,
        sorted(tasks),
        arms,
        dict(
            report_sha256=report_pin, actor_done_sha256=done_pin, plan_sha256=plan_pin
        ),
    )


def comparison(records, tasks, left, right):
    rows = []
    for task in tasks:
        a, b = records[(task, left)], records[(task, right)]
        complete = a["status"] == b["status"] == "COMPLETED"
        rows.append(
            dict(
                task_id=task,
                statuses=[a["status"], b["status"]],
                answer_equal=a.get("answer") == b.get("answer") if complete else None,
                answers_present=[
                    a.get("answer") is not None,
                    b.get("answer") is not None,
                ],
                selection_equal=a["selected"] == b["selected"]
                if complete and "selected" in a and "selected" in b
                else None,
                observations_equal=a["observed_source_ids"] == b["observed_source_ids"]
                if complete
                and "observed_source_ids" in a
                and "observed_source_ids" in b
                else None,
                quality_delta=a["quality"] - b["quality"]
                if a["quality"] is not None and b["quality"] is not None
                else None,
            )
        )
    known = all(r["quality_delta"] is not None for r in rows)
    return dict(
        left=left,
        right=right,
        tasks=len(rows),
        rows=rows,
        mean_quality_delta=sum(r["quality_delta"] for r in rows) / len(rows)
        if known
        else None,
        unknown_pairs=sum(r["quality_delta"] is None for r in rows),
    )


def oracle(args, inputs, tasks):
    require(args.oracle_report_sha256 is not None, "oracle report raw SHA required")
    report, pin = read(args.oracle / "REPORT.json", args.oracle_report_sha256)
    plan, _ = read(args.oracle / "PLAN.json", report["plan_file_sha256"])
    require(
        report["schema"] == "perc1.cord-oracle-report.v1"
        and report["all_results_retained"]
        and report["frozen_inputs_unchanged"]
        and report["fair_comparator"] is False,
        "incomplete or misclassified oracle",
    )
    require(
        all(plan[k] == inputs[k] for k in ("actor_done_sha256", "plan_sha256")),
        "oracle belongs to a different pilot",
    )
    roster = report["results"]
    require(
        len(roster) == len(tasks) and {r["task_id"] for r in roster} == set(tasks),
        "oracle roster differs from pilot",
    )
    rows = []
    for entry in roster:
        task = entry["task_id"]
        require(entry["relative_path"] == task + "/RESULT.json", "unsafe oracle path")
        record, _ = read(args.oracle / entry["relative_path"], entry["sha256"])
        require(
            record["task_id"] == task
            and record["classification"] == "oracle_upper_bound"
            and record["fair_comparator"] is False,
            "oracle identity/classification changed",
        )
        validate_result(record, {**record, "status": entry["status"]})
        rows.append(record)
    return dict(
        report_sha256=pin,
        classification="oracle_upper_bound",
        fair_comparator=False,
        summary=statistics(rows),
        measured_net_benefit=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pilot", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("report-sha256", "actor-done-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--oracle-report-sha256")
    args = parser.parse_args()
    records, tasks, arms, inputs = pilot(args)
    require(
        {arm for pair in COMPARISONS.values() for arm in pair} <= set(arms)
        and "full_ocr" in arms,
        "required comparison arms missing",
    )
    summaries = {
        arm: statistics([records[(task, arm)] for task in tasks]) for arm in arms
    }
    for summary in summaries.values():
        baseline = summaries["full_ocr"]["totals"]
        summary["cost_ratios_vs_full_ocr"] = {
            key: value / baseline[key]
            if value is not None and baseline[key] is not None and baseline[key] > 0
            else None
            for key, value in summary["totals"].items()
        }
    result = dict(
        schema="perc1.cord-public-synthesis.v1",
        scientific_status="HOLD",
        adoption="NoUpdate",
        inputs=inputs,
        tasks=len(tasks),
        arms=summaries,
        comparisons={
            name: comparison(records, tasks, *pair)
            for name, pair in COMPARISONS.items()
        },
        oracle=oracle(args, inputs, tasks) if args.oracle else None,
        measured_net_benefit=None,
        full_cost_qualified=False,
        source_independence_verified=False,
        native_daemon_integrated=False,
        interpretation={
            "zero_visual": "Same frozen head with visual inputs zeroed after real encoding; actual selected observation executes. This is an input intervention, not a separately retrained model without vision.",
            "fixed_selection": "Neural encoding and OCR decoder remain; the observation policy is fixed to the lower band. Learned-minus-fixed quality tests this policy choice on the frozen tasks.",
            "encoder_cost": "fixed_selection versus fixed_region holds observations and decoder fixed when per-task equality checks pass. Wall cost measures the encoder path, including model load, latent/wire retention and cold verification, not only neural compute.",
            "decoder": "All arms use OCR and fixed lexical rules. Neural decoder contribution and a learned-decoder ablation were not evaluated.",
            "cost": "Ratios are measured invocation envelopes, never sums of nested phases. Learned also retains and cold-verifies its active decision; zero_visual timing does not isolate visual-input cost. Shared preparation, energy, billing and prior capture remain outside complete net-benefit accounting.",
            "quality": "Digit-string equality after punctuation and leading-zero removal; UNKNOWN remains null. Deltas are left minus right; means become null if any pair is unknown. No answers or OCR text are published.",
        },
    )
    with args.output.open("x") as stream:
        json.dump(
            result,
            stream,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        stream.write("\n")


if __name__ == "__main__":
    main()
