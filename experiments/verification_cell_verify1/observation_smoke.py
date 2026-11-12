"""Paid partial observations and four policies in the existing finite fixture.

The partial readback sees resource names, never values, fault names or labels.
Training uses only the train phase, after an observed-information diagnostic.
The frequency baseline is not an LLM or a calibrated neural verifier. All arms
retain fresh mandatory host acceptance; optional checks cannot grant authority.
"""

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from . import runtime
from .experiment import Recorder, append, source_manifest
from .observation_diagnostics import analyze_observations
from .shadow_risk import Snapshot, Target, TerminalLabel, fit_risk_table


ARMS = ("no_optional_check", "fixed_readback", "risk_triggered", "oracle_information")
OPTIONAL_OPERATION_LIMIT = 3
PHASES = (("train", 3), ("cal", 2), ("confirm", 3), ("shift", 2))
SCHEMAS = {
    "ack": runtime.sha(["step1_ack"]),
    "readback": runtime.sha(["all_effect_acks", "left_present", "right_present"]),
}
TARGET = Target(
    "sqlite_two_field_engineering_fixture_v1",
    "terminal_goal_value_error",
    4,
    runtime.sha(
        "three effects; optional observation only; mandatory check and ACK reconciliation"
    ),
)


def plan_cases():
    cases = []
    for phase_index, (phase, groups) in enumerate(PHASES):
        faults = (
            runtime.FAULTS if phase != "shift" else ("clean",) * 5 + ("semantic_error",)
        )
        for group in range(groups):
            for slot, fault in enumerate(faults):
                identity = f"{phase}/{group}/{slot}"
                cases.append(
                    {
                        "case_id": runtime.sha(identity)[:20],
                        "phase": phase,
                        "source_group": f"{phase}/template-group/{group}",
                        "fault": fault,
                        "left": 10000 * phase_index + 100 + group,
                        "right": 10000 * phase_index + 200 + group,
                    }
                )
    return cases


def collect(output, recorder, case, arm, model, prior):
    trajectory = f"{case['case_id']}-{arm}"
    path = output / "state" / (trajectory + ".sqlite")
    goal = {"task_id": trajectory, "left": case["left"], "right": case["right"]}
    clock_origin = time.perf_counter_ns()
    features, probabilities, snapshots = {}, {}, {}
    model_identities = {"ack": runtime.sha({"constant_train_prior": prior})}
    selected, optional, oracle_label = False, None, None
    optional_operations = 0

    def measured(kind, operation):
        nonlocal optional_operations
        if kind in (
            "partial_readback",
            "frequency_prediction",
            "oracle_information_read",
            "optional_property_check",
        ):
            if optional_operations >= OPTIONAL_OPERATION_LIMIT:
                raise ValueError("optional operation budget exhausted")
            optional_operations += 1
        with recorder.meter(trajectory, arm, kind):
            value = operation()
        append(
            output / "events.jsonl",
            {
                "trajectory_id": trajectory,
                "kind": kind,
                "value": value,
                "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                "available_monotonic_ns": time.perf_counter_ns() - clock_origin,
                "clock_domain": "calling_process_monotonic_relative_to_trajectory",
            },
        )
        return value

    measured("initialize", lambda: runtime.initialize(path, goal))
    acks = []
    for step in (1, 2, 3):
        reply = measured(
            "effect", lambda: runtime.execute_step(path, goal, case["fault"], step)
        )
        acks.append(reply["ack"])
        if step == 1:
            features["ack"] = [reply["ack"]]
            probabilities["ack"] = prior
    if arm in ("probe", "risk_triggered"):

        def read_partial():
            with closing(
                sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as db:
                db.execute("BEGIN")
                frontier = db.execute("SELECT epoch,tick FROM meta").fetchone()
                if frontier != (3, 3):
                    raise ValueError("partial readback frontier changed")
                names = {row[0] for row in db.execute("SELECT name FROM resources")}
            return [all(acks), "left" in names, "right" in names]

        features["readback"] = measured("partial_readback", read_partial)
        snapshot = Snapshot(
            trajectory,
            case["source_group"],
            runtime.sha(goal),
            TARGET,
            3,
            tuple(float(value) for value in features["readback"]),
        )
        snapshots["readback"] = snapshot
        if model is not None:
            prediction = measured(
                "frequency_prediction", lambda: asdict(model.predict(snapshot))
            )
            probabilities["readback"] = prediction["probability"]
        else:
            probabilities["readback"] = None
        model_identities["readback"] = (
            model.model_sha256 if model is not None else runtime.sha("not_fitted")
        )
    if arm == "fixed_readback":
        selected = True
    elif arm == "risk_triggered":
        risk = probabilities["readback"]
        selected = risk is None or risk >= 0.6
    elif arm == "oracle_information":
        oracle_label = measured(
            "oracle_information_read", lambda: runtime.outcome(path, goal)
        )
        selected = oracle_label
    if selected:
        optional = measured(
            "optional_property_check", lambda: runtime.inspect(path, goal, 3)
        )
    terminal = measured(
        "mandatory_terminal_check", lambda: runtime.inspect(path, goal, 4, accept=True)
    )
    if terminal["reason"] == "missing_ack_requires_readback":
        measured("mandatory_reconciliation", lambda: runtime.reconcile(path, goal, 4))
        terminal = measured(
            "mandatory_terminal_readback",
            lambda: runtime.inspect(path, goal, 4, accept=True),
        )
    error = measured("terminal_label", lambda: runtime.outcome(path, goal))
    label = TerminalLabel(
        trajectory,
        case["source_group"],
        runtime.sha(goal),
        TARGET,
        "accept" if terminal["accepted"] else "reject",
        error,
        4,
        runtime.sha({"goal": goal, "error": error, "terminal": terminal}),
        None,
    )
    result = {
        "trajectory_id": trajectory,
        "case_id": case["case_id"],
        "source_group": case["source_group"],
        "phase": case["phase"],
        "arm": arm,
        "accepted": terminal["accepted"],
        "terminal_error": error,
        "selected_optional_check": selected,
        "optional_report": optional,
        "oracle_information": oracle_label,
        "features": features,
        "probabilities": probabilities,
        "model_identities": model_identities,
        "terminal_label": asdict(label),
    }
    append(output / "trajectories.jsonl", result)
    return result, snapshots.get("readback"), label


def diagnostic_rows(records):
    rows = []
    for record in records:
        for view, features in record["features"].items():
            probability = record["probabilities"][view]
            rows.append(
                {
                    "case_id": record["trajectory_id"],
                    "source_group": record["source_group"],
                    "phase": record["phase"],
                    "view_kind": view,
                    "feature_key": features,
                    "terminal_error": record["terminal_error"],
                    "risk_probability": probability,
                    "decision": "check"
                    if probability is None or probability >= 0.6
                    else "skip",
                    "available_step": 1 if view == "ack" else 3,
                    "decision_step": 1 if view == "ack" else 3,
                    "model_sha256": record["model_identities"][view],
                    "input_schema_sha256": SCHEMAS[view],
                }
            )
    return rows


def _run_created(output):
    (output / "state").mkdir()
    cases = plan_cases()
    roster = [dict(case_id=c["case_id"], arm="probe") for c in cases]
    roster += [
        dict(case_id=c["case_id"], arm=a)
        for c in cases
        if c["phase"] == "confirm"
        for a in ARMS
    ]
    manifest = {
        "schema": "hepta.verify.observation-smoke.v1",
        "target": asdict(TARGET),
        "cases": cases,
        "roster": roster,
        "feature_schemas": SCHEMAS,
        "risk_threshold": 0.6,
        "sources": source_manifest(),
        "scope": "controlled_fixture_not_independent_real_tasks",
        "source_independence_established": False,
        "production_authority": "NONE",
        "label_trust": "separate_SQL_transaction_same_host_and_two_field_rubric",
        "optional_check_changes_state": False,
        "diagnostic_decisions": "shadow_threshold_summaries_not_executed_checks",
        "checker_runtime": "Python_runtime.inspect_not_Rust_or_Agentd_native",
        "common_optional_operation_limit": OPTIONAL_OPERATION_LIMIT,
        "budget_unit": "one read, frequency prediction or property check; physical costs separately measured",
        "oracle_scope": "terminal_values_fixed_after_step3_under_frozen_continuation",
        "false_accept_loss": "reported_count_no_invented_monetary_conversion",
        "full_physical_cost_complete": False,
    }
    (output / "PLAN.json").write_text(
        runtime.canonical(manifest) + "\n", encoding="utf-8"
    )
    recorder = Recorder(output)
    records, probes, snapshots, labels = [], [], [], []
    model, prior, information_gate = None, None, None
    started = time.perf_counter_ns()
    phases = []
    for phase, _ in PHASES:
        phases.append(
            {"phase": phase, "started_monotonic_ns": time.perf_counter_ns() - started}
        )
        for case in (c for c in cases if c["phase"] == phase):
            record, snapshot, label = collect(
                output, recorder, case, "probe", model, prior
            )
            records.append(record)
            probes.append(record)
            if phase == "train":
                snapshots.append(snapshot)
                labels.append(label)
            if phase == "confirm":
                for arm in ARMS:
                    result, _, _ = collect(output, recorder, case, arm, model, prior)
                    records.append(result)
        if phase == "train":
            information_gate = analyze_observations(diagnostic_rows(probes))
            resolution = information_gate["cohorts"]["train/readback"]["information"][
                "empirical_probability_resolution_known"
            ]
            if resolution is None or resolution <= 0:
                raise ValueError(
                    "no observed probability resolution; do not fit risk model"
                )
            train_groups = sorted(
                {c["source_group"] for c in cases if c["phase"] == "train"}
            )
            evaluation_groups = sorted(
                {c["source_group"] for c in cases if c["phase"] != "train"}
            )
            with recorder.meter("frozen_train", "training", "frequency_fit"):
                model = fit_risk_table(
                    snapshots, labels, TARGET, train_groups, evaluation_groups
                )
                prior = (sum(label.error for label in labels) + 1) / (len(labels) + 2)
            (output / "MODEL.json").write_text(
                runtime.canonical(asdict(model)) + "\n", encoding="utf-8"
            )
        phases[-1]["completed_monotonic_ns"] = time.perf_counter_ns() - started
    expected = {(r["case_id"], r["arm"]) for r in roster}
    observed = [(r["case_id"], r["arm"]) for r in records]
    if len(set(observed)) != len(observed) or set(observed) != expected:
        raise ValueError("planned denominator mismatch")
    diagnostics = analyze_observations(diagnostic_rows(probes))
    (output / "DIAGNOSTICS.json").write_text(
        runtime.canonical(diagnostics) + "\n", encoding="utf-8"
    )
    arms = {}
    for arm in ARMS:
        selected = [r for r in records if r["arm"] == arm]
        costs = [c for c in recorder.costs if c["arm"] == arm]
        arms[arm] = {
            "rows": len(selected),
            "known_terminal_labels": sum(
                type(r["terminal_error"]) is bool for r in selected
            ),
            "accepted": sum(r["accepted"] for r in selected),
            "accepted_known_value_errors": sum(
                r["accepted"] and r["terminal_error"] is True for r in selected
            ),
            "rejected_known_clean_terminal_values": sum(
                not r["accepted"] and r["terminal_error"] is False for r in selected
            ),
            "causal_false_rejection_rate": None,
            "optional_checks": sum(r["selected_optional_check"] for r in selected),
            "optional_missed_errors": sum(
                not r["selected_optional_check"] and r["terminal_error"] is True
                for r in selected
            ),
            "known_clean_optional_checks": sum(
                r["selected_optional_check"] and r["terminal_error"] is False
                for r in selected
            ),
            "measured_operation_wall_ns": sum(c["wall_ns"] for c in costs),
            "measured_calling_process_cpu_ns": sum(c["cpu_ns"] for c in costs),
            "operations": dict(Counter(c["kind"] for c in costs)),
            "energy_joules": None,
        }
    result = {
        "schema": manifest["schema"],
        "plan_sha256": runtime.sha(manifest),
        "model_sha256": model.model_sha256,
        "planned_trajectories": len(roster),
        "completed_trajectories": len(records),
        "missing_terminal_labels": 0,
        "template_groups": sum(n for _, n in PHASES),
        "phase_timings": phases,
        "information_before_fit": information_gate,
        "arms": arms,
        "actual_frequency_model_fits": 1,
        "actual_frequency_predictions": sum(
            c["kind"] == "frequency_prediction" for c in recorder.costs
        ),
        "neural_model_inferences_executed": 0,
        "new_independent_real_tasks": 0,
        "training_and_probe_costs": [c for c in recorder.costs if c["arm"] not in ARMS],
        "overall_wall_ns": time.perf_counter_ns() - started,
        "overall_wall_scope": "phase_execution_and_reporting_after_PLAN_write",
        "full_physical_cost_complete": False,
        "scientific_admission": "HOLD",
        "production_authority": "NONE",
        "learning_decision": "NoUpdate",
    }
    (output / "RESULT.json").write_text(
        runtime.canonical(result) + "\n", encoding="utf-8"
    )
    return result


def run(output):
    """Create one run; failures preserve the original planned denominator."""
    output.mkdir(parents=True, exist_ok=False)
    try:
        return _run_created(output)
    except BaseException as error:
        plan_path = output / "PLAN.json"
        plan = (
            json.loads(plan_path.read_text(encoding="utf-8"))
            if plan_path.exists()
            else {}
        )
        rows_path, costs_path = output / "trajectories.jsonl", output / "costs.jsonl"
        records = (
            [
                json.loads(line)
                for line in rows_path.read_text(encoding="utf-8").splitlines()
            ]
            if rows_path.exists()
            else []
        )
        costs = (
            [
                json.loads(line)
                for line in costs_path.read_text(encoding="utf-8").splitlines()
            ]
            if costs_path.exists()
            else []
        )
        completed = {(r["case_id"], r["arm"]) for r in records}
        started = {r["trajectory_id"] for r in costs}
        events_path = output / "events.jsonl"
        events = (
            [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            if events_path.exists()
            else []
        )
        accepted = {
            event["trajectory_id"]: event["value"]["accepted"]
            for event in events
            if event["kind"]
            in ("mandatory_terminal_check", "mandatory_terminal_readback")
        }
        missing = [
            {
                **r,
                "status": "UNKNOWN"
                if f"{r['case_id']}-{r['arm']}" in started
                else "NOT_STARTED",
                "terminal_error": None,
                "accepted": accepted.get(f"{r['case_id']}-{r['arm']}"),
            }
            for r in plan.get("roster", [])
            if (r["case_id"], r["arm"]) not in completed
        ]
        failure = {
            "schema": "hepta.verify.observation-smoke-failure.v1",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "planned_trajectories": len(plan.get("roster", [])),
            "completed_trajectories": len(records),
            "missing": missing,
            "accepted_with_unknown_terminal_label": sum(
                r["accepted"] is True for r in missing
            ),
            "scientific_admission": "HOLD",
            "production_authority": "NONE",
        }
        (output / "FAILURE.json").write_text(
            runtime.canonical(failure) + "\n", encoding="utf-8"
        )
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    result = run(parser.parse_args().output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "planned_trajectories",
                    "completed_trajectories",
                    "missing_terminal_labels",
                    "actual_frequency_model_fits",
                    "actual_frequency_predictions",
                    "arms",
                    "scientific_admission",
                    "production_authority",
                    "learning_decision",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
