#!/usr/bin/env python3
"""Read-only, standard-library arithmetic audit of a retained CTRL factorial report.

This does not import the frozen runtime or readmit native artifacts. Output is
compact JSON; missing outcomes stay unknown and measured net excludes full costs.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

METHODS = ("STOP", "light", "tuned-fixed", "point", "unconditional", "conditional")
MODES = ("frozen", "adapted")
STATUSES = ("NOT_STARTED", "RUNNING", "UNKNOWN", "FAILED", "CANCELLED", "COMPLETED")
METRICS = ("quality", "observed_task_cost_net")
READ_FLAGS = (
    "observation_bytes_changed",
    "candidate_inventory_changed",
    "new_recognized_text",
    "selected_candidate_changed",
    "selected_text_changed",
    "written_text_differs_from_initial_selection",
    "initial_scorer_match_present",
    "finalizer_scorer_match_present",
    "new_reference_matching_candidate",
    "semantic_information_gain",
    "terminal_quality_change",
)
FACTORIAL = {
    "off_off": "frozen/STOP",
    "off_on": "frozen/conditional",
    "on_off": "adapted/STOP",
    "on_on": "adapted/conditional",
}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def context(row):
    return tuple(row[k] for k in ("source_id", "case_id", "seed"))


def source_mean(values):
    groups = defaultdict(list)
    for key, value in values.items():
        groups[key[0]].append(value)
    return (
        math.fsum(math.fsum(items) / len(items) for items in groups.values())
        / len(groups)
        if groups
        else None
    )


def summary(values, planned):
    mean = source_mean(values)
    return {
        "contexts": len(values),
        "sources": len({key[0] for key in values}),
        "primary": mean if len(values) == planned else None,
        "observed_subset": mean,
    }


def equivalent(a, b):
    if number(a) and number(b):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12)
    return type(a) is type(b) and a == b


def summarize(report, *, allow_fixtures=False):
    if report.get("schema") != "ctrl.content-control-factorial-report.v1":
        raise ValueError("Expected the retained factorial REPORT.json")
    plan, stored = report["plan"], report["cohort"]
    cases, arms = plan["contexts"], plan["arms"]
    contexts = {context(case) for case in cases}
    names = [arm["arm_id"] for arm in arms]
    expected_names = [mode + "/" + method for mode in MODES for method in METHODS]
    if (
        len(contexts) != len(cases)
        or not contexts
        or len(names) != 12
        or set(names) != set(expected_names)
        or plan["factorial"] != FACTORIAL
        or stored["plan_sha256"] != digest(plan)
    ):
        raise ValueError("Invalid, duplicated or inconsistent frozen 12-arm roster")
    for source, case, seed in contexts:
        if (
            type(source) is not str
            or not source
            or type(case) is not str
            or not case
            or type(seed) is not int
            or seed < 0
        ):
            raise ValueError("Invalid registered context")
    sources = {key[0] for key in contexts}
    if set(plan["partitions"]["evaluation"]) != sources:
        raise ValueError("Source denominator differs from the registered contexts")
    bindings = {arm["arm_id"]: arm for arm in arms}
    action_inventory = report.get("observed_actions", {})
    if type(action_inventory) is not dict or set(action_inventory) - set(names):
        raise ValueError("Unregistered arm in retained action inventory")
    records, executions, fixture_rows = {}, set(), 0
    for row in report["rows"]:
        if (
            type(row.get("source_id")) is not str
            or type(row.get("case_id")) is not str
            or type(row.get("seed")) is not int
            or row["seed"] < 0
        ):
            raise ValueError("Invalid execution context types")
        key, arm = context(row), row["arm_id"]
        if key not in contexts or arm not in bindings or (key, arm) in records:
            raise ValueError("Unregistered or duplicate execution row")
        if (
            row["status"] not in STATUSES
            or row["shared_sha256"] != digest(plan["shared"])
            or any(
                row[k] != bindings[arm][k]
                for k in ("content_sha256", "critic_context_sha256")
            )
            or type(row["full_cost_observed"]) is not bool
        ):
            raise ValueError("Execution status or declared input binding differs")
        quality, cost, execution = row["quality"], row["task_cost"], row["execution_id"]
        if (
            cost is not None
            and (not number(cost) or cost < 0)
            or row["status"] == "COMPLETED"
            and (not number(quality) or not 0 <= quality <= 1)
            or row["status"] != "COMPLETED"
            and quality is not None
            or row["status"] == "NOT_STARTED"
            and execution is not None
            or row["status"] in ("RUNNING", "FAILED", "COMPLETED")
            and execution is None
        ):
            raise ValueError("Missing outcomes cannot be scored or costs imputed")
        if execution is not None:
            if type(execution) is not str or not execution or execution in executions:
                raise ValueError("One execution cannot stand for multiple rows")
            executions.add(execution)
        if row["evidence_kind"] not in (None, "native_macro", "fixture"):
            raise ValueError("Unknown evidence kind")
        if row["status"] == "COMPLETED" and (
            row["evidence_kind"] is None or row["evidence_sha256"] is None
        ):
            raise ValueError("Completed row lacks its admitted evidence declaration")
        fixture_rows += row["evidence_kind"] == "fixture"
        records[key, arm] = row
    if fixture_rows and not allow_fixtures:
        raise ValueError("Fixture evidence requires explicit --allow-fixtures")
    audit = {"comparisons": 0, "mismatch_count": 0, "mismatches": []}

    def check(path, calculated, actual):
        audit["comparisons"] += 1
        if not equivalent(calculated, actual):
            audit["mismatch_count"] += 1
            if len(audit["mismatches"]) < 12:
                audit["mismatches"].append(
                    {"path": path, "recomputed": calculated, "stored": actual}
                )

    arm_results, metric_values, total_status = {}, {}, Counter()
    registered_source_cases = Counter(key[:2] for key in contexts)
    missing_total = 0
    for arm in names:
        rows = {key: records.get((key, arm)) for key in contexts}
        statuses = Counter(row["status"] if row else "UNKNOWN" for row in rows.values())
        total_status.update(statuses)
        complete = {
            key: row
            for key, row in rows.items()
            if row and row["status"] == "COMPLETED"
        }
        values = {
            "quality": {key: row["quality"] for key, row in complete.items()},
            "observed_task_cost_net": {
                key: row["quality"] - row["task_cost"]
                for key, row in complete.items()
                if row["task_cost"] is not None
            },
        }
        metric_values[arm] = values
        metrics = {
            name: summary(value, len(contexts)) for name, value in values.items()
        }
        costs = [
            row["task_cost"]
            for row in rows.values()
            if row and row["task_cost"] is not None
        ]
        missing = sum(row is None for row in rows.values())
        missing_total += missing
        result = {
            "planned": len(contexts),
            "statuses": {status: statuses[status] for status in STATUSES},
            "missing_records": missing,
            **metrics,
            "observed_task_cost_total_including_failures": math.fsum(costs)
            if costs
            else None,
            "unknown_task_cost_items": len(contexts) - len(costs),
        }
        original = stored["arms"][arm]
        for field, calculated in (
            ("planned", len(contexts)),
            ("planned_sources", len(sources)),
            ("statuses", result["statuses"]),
            ("missing_records", missing),
            ("admitted_completed", len(complete)),
            ("unknown_task_cost_items", result["unknown_task_cost_items"]),
            (
                "observed_task_cost_total",
                result["observed_task_cost_total_including_failures"],
            ),
            ("observed_task_cost_net_items", len(values["observed_task_cost_net"])),
        ):
            check(f"arms/{arm}/{field}", calculated, original.get(field))
        for metric in METRICS:
            calc = metrics[metric]
            check(
                f"arms/{arm}/primary_{metric}",
                calc["primary"],
                original.get("primary_" + metric),
            )
            subset = original["observed_subset"]
            if metric == "quality":
                mean, count, source_count = (
                    subset[metric],
                    subset["contexts"],
                    subset["sources"],
                )
            else:
                part = subset[metric]
                mean, count, source_count = (
                    part["source_equal_mean"],
                    part["contexts"],
                    part["sources"],
                )
            for label, calculated, actual in (
                ("subset_mean", calc["observed_subset"], mean),
                ("subset_contexts", calc["contexts"], count),
                ("subset_sources", calc["sources"], source_count),
            ):
                check(f"arms/{arm}/{metric}/{label}", calculated, actual)
        action_rows = action_inventory.get(arm, [])
        if type(action_rows) is not list:
            raise ValueError("Expected a retained action list for each arm")
        available = Counter(key[:2] for key in complete)
        seen, macros, reasons = Counter(), Counter(), Counter()
        flags = [[0, 0, 0, 0] for _ in READ_FLAGS]
        for action in action_rows:
            key = action["source_id"], action["case_id"]
            seen[key] += 1
            if seen[key] > available[key]:
                raise ValueError(
                    "Action record exceeds completed source/case inventory"
                )
            macro, controller = action["macro"], action.get("controller", {})
            if type(controller) is not dict:
                raise ValueError("Expected the original controller record")
            if macro not in ("READ", "STOP") or controller.get("macro") not in (
                None,
                macro,
            ):
                raise ValueError("Observed macro and controller disagree")
            macros[macro] += 1
            reason = controller.get("reason")
            reasons[reason if type(reason) is str and reason else "UNKNOWN"] += 1
            attribution = action.get("read_attribution")
            if attribution is None:
                attribution = {}
            if type(attribution) is not dict:
                raise ValueError("Expected the retained READ attribution object")
            executed = attribution.get("read_executed")
            if executed is not None and (
                type(executed) is not bool or executed != (macro == "READ")
            ):
                raise ValueError("Observed macro and READ receipt disagree")
            if macro == "READ":
                for index, name in enumerate(READ_FLAGS):
                    value = attribution.get(name)
                    if value is not None and type(value) is not bool:
                        raise ValueError(
                            "Unexpected nonboolean READ attribution witness"
                        )
                    if value is None:
                        flags[index][3] += 1
                    else:
                        flags[index][0] += 1
                        flags[index][1 if value else 2] += 1
        result["actions"] = {
            "scope": "admitted_COMPLETED_only",
            "READ": macros["READ"],
            "STOP": macros["STOP"],
            "missing_for_completed": len(complete) - len(action_rows),
            "matches_completed_multiset": seen == available,
            "unresolved_planned": len(contexts) - len(complete),
            "reason_counts": dict(sorted(reasons.items())),
            "seed_ambiguous_records": sum(
                count for key, count in seen.items() if registered_source_cases[key] > 1
            ),
            "read_flag_counts": flags,
        }
        arm_results[arm] = result

    def contrast(cell_names, signs, original, field, orientation=1):
        output = {}
        for metric in METRICS:
            cells = [metric_values[name][metric] for name in cell_names]
            common = set.intersection(*(set(cell) for cell in cells))
            values = {
                key: math.fsum(sign * cell[key] for sign, cell in zip(signs, cells))
                for key in common
            }
            result = summary(values, len(contexts))
            result["direction_counts"] = [
                sum(value > 0 for value in values.values()),
                sum(value == 0 for value in values.values()),
                sum(value < 0 for value in values.values()),
            ]
            part = original[metric]
            for label, calculated, actual in (
                ("planned_contexts", len(contexts), part["planned_contexts"]),
                ("planned_sources", len(sources), part["planned_sources"]),
                ("paired_contexts", len(common), part["paired_contexts"]),
                ("paired_sources", result["sources"], part["paired_sources"]),
                (
                    "primary",
                    result["primary"],
                    None if part[field] is None else orientation * part[field],
                ),
                (
                    "subset_mean",
                    result["observed_subset"],
                    None
                    if part["observed_subset"][field] is None
                    else orientation * part["observed_subset"][field],
                ),
                ("subset_contexts", len(common), part["observed_subset"]["contexts"]),
                (
                    "subset_sources",
                    result["sources"],
                    part["observed_subset"]["sources"],
                ),
            ):
                check(
                    f"contrast/{'+'.join(cell_names)}/{metric}/{label}",
                    calculated,
                    actual,
                )
            output[metric] = result
        return output

    contrasts = {}
    for mode in MODES:
        candidate = mode + "/conditional"
        for policy in ("STOP", "tuned-fixed"):
            baseline = mode + "/" + policy
            matches = [
                row
                for row in stored["paired_contrasts"]
                if {row["candidate"], row["baseline"]} == {candidate, baseline}
            ]
            if len(matches) != 1:
                raise ValueError("Missing or duplicate stored comparison")
            original = matches[0]
            contrasts[candidate + " minus " + baseline] = contrast(
                [candidate, baseline],
                [1, -1],
                original,
                "source_equal_difference",
                1 if original["candidate"] == candidate else -1,
            )
    did = contrast(
        [FACTORIAL[key] for key in ("on_on", "on_off", "off_on", "off_off")],
        [1, -1, -1, 1],
        stored["factorial"],
        "source_equal_interaction",
    )
    planned = len(contexts) * len(names)
    check("planned_executions", planned, stored["planned_executions"])
    completed_contexts = {
        key
        for key in contexts
        if all(
            records.get((key, arm), {}).get("status") == "COMPLETED" for arm in names
        )
    }
    check(
        "matched_initial_physical_frontiers",
        len({key for (key, _), row in records.items() if row["status"] == "COMPLETED"}),
        report.get("matched_initial_physical_frontiers"),
    )
    if report.get("execution_order") is not None:
        for field, calculated in (
            ("planned_executions", planned),
            ("verified_started_prefix", len(executions)),
        ):
            check(
                "execution_order/" + field,
                calculated,
                report["execution_order"].get(field),
            )
    audit["all_match"] = audit["mismatch_count"] == 0
    return {
        "schema": "ctrl.factorial-readonly-summary.v1",
        "factorial_sha256": report["factorial_sha256"],
        "denominators": {
            "independent_source_units": len(sources),
            "registered_contexts": len(contexts),
            "arms": len(names),
            "planned_executions": planned,
            "provided_rows": len(records),
            "missing_records": missing_total,
            "contexts_completed_all_arms": len(completed_contexts),
            "sources_completed_all_arms": sum(
                all(key in completed_contexts for key in contexts if key[0] == source)
                for source in sources
            ),
            "statuses": {status: total_status[status] for status in STATUSES},
            "matches_16_sources_48_contexts_576_executions": (
                len(sources),
                len(contexts),
                planned,
            )
            == (16, 48, 576),
            "contexts_per_source_distribution": dict(
                sorted(Counter(Counter(key[0] for key in contexts).values()).items())
            ),
        },
        "arms": arm_results,
        "conditional_contrasts": contrasts,
        "factorial_DID": {
            "formula": "(adapted/conditional - adapted/STOP) - (frozen/conditional - frozen/STOP)",
            **did,
        },
        "read_flag_columns": list(READ_FLAGS),
        "read_flag_count_order": ["known", "true", "false", "unknown"],
        "read_flag_scope": "admitted READ executions only; zero READ is no READ evidence",
        "direction_count_order": ["positive", "zero", "negative"],
        "weighting": "paired contexts within each source, then equal source means; primary requires every planned context",
        "stored_mean_audit": audit,
        "execution_order": report.get("execution_order"),
        "matched_initial_physical_frontiers": report.get(
            "matched_initial_physical_frontiers"
        ),
        "limits": {
            "observed_net": "terminal quality minus executor task_cost, including initialization/actions/scoring/admission",
            "excluded_costs": ["provider", "energy", "fit", "calibration", "tuning"],
            "action_records_omit_seed": True,
            "action_counts_for_unresolved_executions": "unknown; report retains completed action traces only",
            "within_run_score_change": "unknown; policy contrasts are matched executed outcomes, selected READ subsets are not randomized",
            "native_artifacts_readmitted": False,
            "original_start_order_rechecked": False,
            "started_prefix_scope": "START count, not COMPLETED count",
            "matched_frontiers_scope": "contexts with at least one completed row, not twelve-arm completion",
            "full_cost_benefit_established": False,
            "new_source_confirmation": False,
            "recursive_ndu_qualified": False,
            "production_admission": False,
            "fixture_rows": fixture_rows,
            "decision": "NoUpdate",
        },
    }


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field: " + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Nonfinite JSON number: " + value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--expected-report-sha256")
    parser.add_argument("--allow-fixtures", action="store_true")
    args = parser.parse_args()
    try:
        path = Path(args.report)
        if not 0 < path.stat().st_size <= 64 * 1024 * 1024:
            raise ValueError("Report must be a nonempty file no larger than 64 MiB")
        raw = path.read_bytes()
        pin = hashlib.sha256(raw).hexdigest()
        if (
            args.expected_report_sha256 is not None
            and pin != args.expected_report_sha256
        ):
            raise ValueError("Report differs from expected raw-byte SHA256")
        report = json.loads(
            raw, object_pairs_hook=strict_object, parse_constant=reject_constant
        )
        result = summarize(report, allow_fixtures=args.allow_fixtures)
        result["report_sha256"] = pin
        result["analysis_script_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        result["external_report_pin_checked"] = args.expected_report_sha256 is not None
        print(
            json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
        return 0 if result["stored_mean_audit"]["all_match"] else 3
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "ctrl.factorial-summary-error.v1",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
