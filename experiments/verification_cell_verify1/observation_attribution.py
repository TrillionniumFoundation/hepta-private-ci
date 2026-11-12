"""Describe incremental paid information after the already available effect ACKs.

This is a saved-record variance decomposition, not a fitted risk model, a
generalization test, or a causal estimate of the value of buying a readback.
"""

import argparse
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path


def _number(value):
    return {
        "value": float(value),
        "numerator": value.numerator,
        "denominator": value.denominator,
    }


def _summary(rows):
    count = len(rows)
    prior = Fraction(sum(row["error"] for row in rows), count)
    views = ("initial_ack", "late_acks", "augmented_paid_view")
    cells = {view: defaultdict(list) for view in views}
    for row in rows:
        keys = (row["acks"][:1], row["acks"], row["acks"] + row["presence"])
        for view, key in zip(views, keys):
            cells[view][key].append(row["error"])
    resolution = {}
    for view in views:
        resolution[view] = sum(
            (
                Fraction(len(labels), count)
                * (Fraction(sum(labels), len(labels)) - prior) ** 2
                for labels in cells[view].values()
            ),
            Fraction(0),
        )
    conditional = sum(
        (
            Fraction(len(labels), count)
            * (
                Fraction(sum(labels), len(labels))
                - Fraction(
                    sum(cells["late_acks"][key[:3]]), len(cells["late_acks"][key[:3]])
                )
            )
            ** 2
            for key, labels in cells["augmented_paid_view"].items()
        ),
        Fraction(0),
    )
    if resolution["augmented_paid_view"] - resolution["late_acks"] != conditional:
        raise ValueError("nested-view variance decomposition failed")
    return {
        "rows": count,
        "known_terminal_errors": sum(row["error"] for row in rows),
        "unknown_terminal_labels": 0,
        "empirical_resolution": {
            key: _number(value) for key, value in resolution.items()
        },
        "incremental_paid_resolution_given_late_acks": _number(conditional),
        "paid_increment_observed_in_supplied_rows": conditional > 0,
        "cell_counts": {view: len(values) for view, values in cells.items()},
    }


def attribute_rows(rows):
    """Analyze a complete supplied projection; this function authenticates no source."""
    rows = list(rows)
    if not 0 < len(rows) <= 100000:
        raise ValueError("bounded nonempty attribution rows required")
    seen, phases = set(), {}
    cohorts = defaultdict(list)
    for row in rows:
        if type(row) is not dict or set(row) != {
            "trajectory_id",
            "phase",
            "source_group",
            "acks",
            "presence",
            "error",
        }:
            raise ValueError("attribution fields changed")
        for name in ("trajectory_id", "source_group"):
            if type(row[name]) is not str or not 0 < len(row[name]) <= 256:
                raise ValueError("invalid attribution identity")
        if row["trajectory_id"] in seen:
            raise ValueError("duplicate attribution trajectory")
        seen.add(row["trajectory_id"])
        if row["phase"] not in ("train", "cal", "confirm", "shift"):
            raise ValueError("invalid attribution phase")
        if phases.setdefault(row["source_group"], row["phase"]) != row["phase"]:
            raise ValueError("source reused across phases")
        if type(row["error"]) is not bool:
            raise ValueError(
                "complete boolean terminal labels required; unknown is not clean"
            )
        for name, width in (("acks", 3), ("presence", 2)):
            if (
                type(row[name]) is not tuple
                or len(row[name]) != width
                or any(type(value) is not bool for value in row[name])
            ):
                raise ValueError("invalid public attribution projection")
        cohorts[row["phase"]].append(row)
    result = {}
    for phase, values in sorted(cohorts.items()):
        sources = defaultdict(list)
        for row in values:
            sources[row["source_group"]].append(row)
        summaries = {
            source: _summary(group) for source, group in sorted(sources.items())
        }
        increments = [
            Fraction(
                summary["incremental_paid_resolution_given_late_acks"]["numerator"],
                summary["incremental_paid_resolution_given_late_acks"]["denominator"],
            )
            for summary in summaries.values()
        ]
        result[phase] = {
            "task_weighted": _summary(values),
            "source_groups": len(sources),
            "by_source": summaries,
            "equal_source_mean_incremental_resolution": _number(
                sum(increments) / len(increments)
            ),
        }
    return {
        "schema": "hepta.verify.observation-attribution.v1",
        "probe_rows": len(rows),
        "cohorts": result,
        "initial_view": "first effect ACK",
        "late_free_view": "all three individually retained effect ACKs",
        "augmented_paid_view": "late free view plus paid left/right presence",
        "estimand": "finite supplied-label conditional probability variance",
        "unknown_label_policy": "refuse attribution; never drop or impute",
        "model_fits_executed": 0,
        "model_predictions_executed": 0,
        "actor_executions": 0,
        "population_information_established": False,
        "source_independence_established": False,
        "causal_paid_readback_value_established": False,
        "scientific_admission": "HOLD",
        "production_authority": "NONE",
    }


def attribute_run(directory):
    """Require the retained-run consistency audit before interpreting saved events."""
    from .observation_audit import audit

    directory = Path(directory)
    audit_result = audit(directory)
    # The audit binds the plan, records and events. This projection counts only
    # probe trajectories, never the four repeated policy arms as new samples.
    saved = {}
    for name in ("trajectories.jsonl", "events.jsonl"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != audit_result["inputs"][name]["sha256"]:
            raise ValueError("saved records changed after their consistency audit")
        saved[name] = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    records = saved["trajectories.jsonl"]
    events = defaultdict(list)
    for event in saved["events.jsonl"]:
        if event["kind"] == "effect":
            events[event["trajectory_id"]].append(event["value"]["ack"])
    rows = []
    for record in records:
        if record["arm"] != "probe":
            continue
        acks = tuple(events[record["trajectory_id"]])
        readback = record["features"]["readback"]
        if len(acks) != 3 or readback[0] is not all(acks):
            raise ValueError("retained ACKs contradict the paid-view ACK projection")
        rows.append(
            {
                "trajectory_id": record["trajectory_id"],
                "phase": record["phase"],
                "source_group": record["source_group"],
                "acks": acks,
                "presence": tuple(readback[1:]),
                "error": record["terminal_error"],
            }
        )
    result = attribute_rows(rows)
    result["retained_run_audit"] = audit_result
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = attribute_run(args.input)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
