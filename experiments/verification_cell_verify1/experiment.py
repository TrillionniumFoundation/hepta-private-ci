"""Frozen, paired engineering experiment; model-based arms require real inputs."""

import argparse
import base64
from collections import defaultdict
from contextlib import contextmanager
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import time

from . import contracts as c
from . import metrics
from . import runtime


ARMS = (
    "deterministic_rules",
    "historical_frequency",
    "fixed_check_time",
    "external_each_step",
)
MODEL_ARMS = (
    "single_step_self_evaluation",
    "shared_base_roles",
    "distinct_adapters",
    "distinct_bases",
)
INJECTION_STEP = {
    fault: (None if fault == "clean" else 3 if fault == "stale_read" else 2)
    for fault in runtime.FAULTS
}


def append(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(c.canonical_json(value) + "\n")
        stream.flush()


def source_manifest():
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path(__file__).parent.glob("*.py"))
    }


def records(path):
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


def effect_streams(stdout, stderr):
    result = {}
    for name, value in (("stdout", stdout), ("stderr", stderr)):
        result[name] = (
            value.decode("utf-8", errors="replace")
            if isinstance(value, bytes)
            else value
        )
        if isinstance(value, bytes):
            result[name + "_base64"] = base64.b64encode(value).decode("ascii")
    return result


class Recorder:
    def __init__(self, directory):
        self.directory = directory
        self.costs = []
        self.serial = 0

    @contextmanager
    def meter(self, trajectory, arm, kind):
        self.serial += 1
        operation_id = f"meter/{self.serial}"
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        status = "completed"
        try:
            yield
        except BaseException as error:
            status = "cancelled" if isinstance(error, KeyboardInterrupt) else "failed"
            raise
        finally:
            row = {
                "operation_id": operation_id,
                "trajectory_id": trajectory,
                "arm": arm,
                "kind": kind,
                "wall_ns": time.perf_counter_ns() - started,
                "cpu_ns": time.process_time_ns() - cpu,
                "units": 1,
                "energy_joules": None,
                "status": status,
            }
            self.costs.append(row)
            append(self.directory / "costs.jsonl", row)


def probability(history, public_observations):
    """Laplace-smoothed prior from frozen training outcomes and public ACKs."""
    feature = (
        "missing_ack"
        if any(not item["ack"] for item in public_observations)
        else "ack_present"
    )
    count, errors = history.get(feature, (0, 0))
    return (errors + 1) / (count + 2)


def check_selected(arm, risk, public_observations, tick, remaining_budget):
    # This function cannot inspect a fault name, goal value, oracle label or DB.
    if arm == "deterministic_rules":
        requested = not public_observations[-1]["ack"]
    elif arm == "historical_frequency":
        return c.select_check(risk, 0.2, 1.0, remaining_budget) == "check"
    elif arm == "fixed_check_time":
        requested = tick == 3
    elif arm == "external_each_step":
        requested = True
    else:
        raise ValueError("unknown executable baseline")
    return requested and remaining_budget >= 0.2


def make_scope(goal, arm, tick, epoch):
    return c.Scope(
        goal["task_id"],
        arm,
        runtime.sha(goal),
        epoch,
        "sqlite_two_field_engineering_fixture_v1",
        "terminal_goal_value_error",
        tick,
        4,
    )


def typed_receipt(report, goal, arm):
    return c.VerificationReceipt(
        scope=make_scope(goal, arm, report["checked_step"], report["state_version"]),
        **{
            key: report[key]
            for key in (
                "property",
                "assumptions",
                "checker_id",
                "checker_version",
                "evidence_sha256",
                "checked_step",
                "verdict",
                "reason",
                "residual_obligations",
            )
        },
    )


def run_one(recorder, case, arm, history):
    goal, fault = case["goal"], case["fault"]
    trajectory = goal["task_id"]
    cost_arm = case["source_group"].split("/", 1)[0] + ":" + arm
    directory = recorder.directory / "state" / f"{trajectory}-{arm}"
    directory.mkdir(parents=True)
    database = directory / "effects.sqlite"
    append(
        recorder.directory / "attempts.jsonl",
        {"trajectory_id": trajectory, "arm": arm, "status": "started"},
    )
    observations, detection, interrupted, accepted, reached = [], None, False, False, 0
    initial_risk = probability(history, observations)
    identity = c.ModelIdentity(
        c.digest(history), None, c.digest({"arm": arm, "version": 1})
    )
    remaining = 0.6
    error, failure = None, None
    try:
        with recorder.meter(trajectory, cost_arm, "initialize"):
            runtime.initialize(database, goal)
        for tick in (1, 2, 3):
            with recorder.meter(trajectory, cost_arm, "effect_subprocess"):
                effect = {
                    "trajectory_id": trajectory,
                    "arm": arm,
                    "tick": tick,
                    "operation_id": f"{trajectory}/step/{tick}",
                }
                try:
                    process = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "experiments.verification_cell_verify1.runtime",
                            "--database",
                            str(database),
                            "--goal",
                            c.canonical_json(goal),
                            "--fault",
                            fault,
                            "--tick",
                            str(tick),
                        ],
                        capture_output=True,
                        timeout=20,
                        check=False,
                    )
                except Exception as exception:
                    append(
                        recorder.directory / "effects.jsonl",
                        {
                            **effect,
                            **effect_streams(
                                getattr(exception, "stdout", None),
                                getattr(exception, "stderr", None),
                            ),
                            "returncode": getattr(exception, "returncode", None),
                            "status": "timed_out"
                            if isinstance(exception, subprocess.TimeoutExpired)
                            else "failed"
                            if isinstance(exception, subprocess.CalledProcessError)
                            else "launch_failed",
                        },
                    )
                    raise
                append(
                    recorder.directory / "effects.jsonl",
                    {
                        **effect,
                        **effect_streams(process.stdout, process.stderr),
                        "returncode": process.returncode,
                        "status": "completed" if process.returncode == 0 else "failed",
                    },
                )
                process.check_returncode()
                observation = json.loads(process.stdout)
                observations.append(observation)
                reached = tick
            with recorder.meter(trajectory, cost_arm, "planning"):
                risk = c.RiskPrediction(
                    make_scope(goal, arm, tick, tick),
                    identity,
                    probability(history, observations),
                    tick,
                    c.digest(observations),
                )
                append(
                    recorder.directory / "predictions.jsonl",
                    json.loads(c.canonical_json(risk)),
                )
                selected = check_selected(
                    arm, risk.probability, observations, tick, remaining
                )
            if selected:
                with recorder.meter(trajectory, cost_arm, "optional_check"):
                    report = runtime.inspect(database, goal, tick)
                remaining = round(remaining - 0.2, 10)
                append(
                    recorder.directory / "receipts.jsonl",
                    json.loads(c.canonical_json(typed_receipt(report, goal, arm))),
                )
                if report["verdict"] != "proved":
                    detection = detection if detection is not None else tick
                if report["reason"] == "missing_ack_requires_readback":
                    with recorder.meter(trajectory, cost_arm, "reconciliation"):
                        recovery = runtime.reconcile(database, goal, tick)
                    append(
                        recorder.directory / "recoveries.jsonl",
                        {
                            "trajectory_id": trajectory,
                            "arm": arm,
                            "tick": tick,
                            **recovery,
                        },
                    )
                elif report["verdict"] != "proved":
                    interrupted = True
                    break
        if not interrupted:
            with recorder.meter(trajectory, cost_arm, "mandatory_terminal_check"):
                report = runtime.inspect(database, goal, 4, accept=True)
            if report["verdict"] != "proved":
                detection = detection if detection is not None else 4
            if report["reason"] == "missing_ack_requires_readback":
                with recorder.meter(trajectory, cost_arm, "reconciliation"):
                    recovery = runtime.reconcile(database, goal, 4)
                append(
                    recorder.directory / "recoveries.jsonl",
                    {"trajectory_id": trajectory, "arm": arm, "tick": 4, **recovery},
                )
                append(
                    recorder.directory / "receipts.jsonl",
                    json.loads(c.canonical_json(typed_receipt(report, goal, arm))),
                )
                with recorder.meter(
                    trajectory, cost_arm, "mandatory_terminal_readback"
                ):
                    report = runtime.inspect(database, goal, 4, accept=True)
            append(
                recorder.directory / "receipts.jsonl",
                json.loads(c.canonical_json(typed_receipt(report, goal, arm))),
            )
            accepted = report["accepted"]
        with recorder.meter(trajectory, cost_arm, "outcome_label"):
            error = runtime.outcome(database, goal)
    except Exception as exception:
        # Preserve the original attempt. A failure never starts a replacement.
        failure = {
            "trajectory_id": trajectory,
            "arm": arm,
            "type": type(exception).__name__,
            "message": str(exception),
        }
    injection = INJECTION_STEP[fault]
    row = {
        "trajectory_id": trajectory,
        "source_group": case["source_group"],
        "arm": arm,
        "fault": fault,
        "risk": initial_risk,
        "accepted": accepted,
        "outcome_error": error,
        "injected_step": injection
        if injection is not None and reached >= injection
        else None,
        "detected_step": detection,
        "terminal_step": 4,
        "interrupted": interrupted,
    }
    append(recorder.directory / "rows.jsonl", row)
    append(
        recorder.directory / "attempts.jsonl",
        {
            "trajectory_id": trajectory,
            "arm": arm,
            "status": "failed" if failure else "completed",
            "reached_effect_step": reached,
            "failure": failure,
        },
    )
    return row, observations, failure


def cases(split, groups):
    offset = {"train": 0, "calibration": 10000, "confirmation": 20000}[split]
    result = []
    for index in range(groups):
        for fault in runtime.FAULTS:
            key = c.digest({"split": split, "group": index, "fault": fault})[:20]
            result.append(
                {
                    "source_group": f"{split}/template-group/{index}",
                    "fault": fault,
                    "goal": {
                        "task_id": key,
                        "left": offset + 100 + index,
                        "right": offset + 200 + index,
                    },
                }
            )
    return result


def intervention_report(history):
    evidence = c.digest({"fixed_observation": "same bytes in every intervention"})
    rows = []
    for probability_value, cost in ((0.01, 0.4), (0.9, 0.4), (0.4, 0.1), (0.4, 0.8)):
        rows.append(
            {
                "evidence_sha256": evidence,
                "risk": probability_value,
                "declared_check_cost": cost,
                "selection": c.select_check(probability_value, cost, 1.0, 1.0),
                "effect_authority": "NONE",
            }
        )
    return {
        "kind": "policy_function_intervention_not_model_activation",
        "fixed_evidence_sha256": evidence,
        "rows": rows,
        "mandatory_budget_shortfall": c.select_check(
            0.0, 1.0, 1.0, 0.5, mandatory=True
        ),
        "history_model_sha256": c.digest(history),
    }


def finish(
    output,
    plan,
    recorder,
    all_rows,
    failures,
    started,
    history,
    frozen_model,
    halted_phase=None,
):
    """Retain full planned denominators even when confirmation never starts."""
    roster = plan["execution_roster"]
    keys = ("trajectory_id", "source_group", "arm", "fault")
    expected = {tuple(item[key] for key in keys) for item in roster}
    observed = [tuple(row[key] for key in keys) for row in all_rows]
    missing = [
        item for item in roster if tuple(item[key] for key in keys) not in set(observed)
    ]
    results = [
        row for row in all_rows if row["source_group"].startswith("confirmation/")
    ]
    effects = records(output / "effects.jsonl")
    measured_effects = [
        row for row in recorder.costs if row["kind"] == "effect_subprocess"
    ]
    expected_effects = {
        (row["trajectory_id"], row["arm"], tick)
        for row in all_rows
        for tick in range(1, (row["detected_step"] if row["interrupted"] else 3) + 1)
    }
    terminal_calls = [
        (row["trajectory_id"], row["arm"].split(":", 1)[1])
        for row in recorder.costs
        if row["kind"] == "mandatory_terminal_check"
    ]
    unchanged = plan["source_sha256"] == source_manifest()
    gates = {
        "source_unchanged": unchanged,
        "frozen_history_unchanged": frozen_model is not None
        and c.digest(history) == frozen_model,
        "exact_attempt_roster": len(observed) == len(roster)
        and len(set(observed)) == len(observed)
        and set(observed) == expected,
        "no_execution_failures": not failures,
        "all_terminal_labels_known": all(
            row["outcome_error"] is not None for row in all_rows
        ),
        "correct_and_reconciled_trajectories_accepted": all(
            row["accepted"] and row["outcome_error"] is False and not row["interrupted"]
            for row in all_rows
            if row["fault"] in ("clean", "missing_receipt")
        ),
        "no_incorrect_or_unknown_trajectory_accepted": all(
            not row["accepted"] or row["outcome_error"] is False for row in all_rows
        ),
        "injected_faults_detected": all(
            row["injected_step"] is not None and row["detected_step"] is not None
            for row in all_rows
            if row["fault"] != "clean"
        ),
        "effect_calls_have_log_and_meter": len(effects) == len(measured_effects)
        and len({(row["trajectory_id"], row["arm"], row["tick"]) for row in effects})
        == len(effects)
        and {(row["trajectory_id"], row["arm"], row["tick"]) for row in effects}
        == expected_effects
        and sorted((row["trajectory_id"], row["arm"]) for row in effects)
        == sorted(
            (row["trajectory_id"], row["arm"].split(":", 1)[1])
            for row in measured_effects
        ),
        "mandatory_terminal_checks_executed": sorted(terminal_calls)
        == sorted(
            (row["trajectory_id"], row["arm"])
            for row in all_rows
            if not row["interrupted"]
        ),
    }
    qualification = {
        "schema": "hepta.verify1.engineering-result.v1",
        "plan_sha256": c.digest(plan),
        "status": "ENGINEERING_SMOKE_HALTED"
        if halted_phase
        else "ENGINEERING_SMOKE_PASS"
        if all(gates.values())
        else "ENGINEERING_SMOKE_FAILED",
        "halted_phase": halted_phase,
        "engineering_gates": gates,
        "planned_attempt_rows": len(roster),
        "observed_attempt_rows": len(all_rows),
        "maximum_planned_effect_calls": 3 * len(roster),
        "effect_call_records": len(effects),
        "unstarted_planned_attempts": missing,
        "planned_confirmation_rows": sum(
            item["phase"] == "confirmation" for item in roster
        ),
        "observed_confirmation_rows": len(results),
        "failed_attempts": failures,
        "source_unchanged": unchanged,
        "frozen_history_model_sha256": frozen_model,
        "model_inferences_executed": 0,
        "model_inference_count_scope": "neural bases/adapters only; table lookups are metered as planning",
        "model_arms": plan["model_arms"],
        "real_model_study_qualified": False,
        "agentd_production_integration_qualified": False,
        "scientific_acceptance": "HOLD",
        "full_physical_cost_complete": False,
        "cpu_scope": "controller process only; child process CPU unmeasured",
        "energy_joules": None,
        "outer_elapsed_ns": time.perf_counter_ns() - started,
        "metrics": metrics.summarize(results, tuple(plan["thresholds"])),
        "costs": metrics.summarize_costs(recorder.costs),
        "scope": "actual local SQLite effects with synthetic tasks and faults; no neural/model comparison",
    }
    (output / "result.json").write_text(c.canonical_json(qualification) + "\n")
    return qualification


def run(output, groups=4):
    if type(groups) is not int or not 1 <= groups <= 100:
        raise ValueError("groups must be within 1..100")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    training, calibration, confirmation = (
        cases("train", 2),
        cases("calibration", 2),
        cases("confirmation", groups),
    )
    source = source_manifest()
    roster = [
        {
            "phase": phase,
            "trajectory_id": case["goal"]["task_id"],
            "source_group": case["source_group"],
            "fault": case["fault"],
            "arm": arm,
        }
        for phase, panel, arms in (
            ("train", training, ("fixed_check_time",)),
            ("calibration", calibration, ("fixed_check_time",)),
            ("confirmation", confirmation, ARMS),
        )
        for case in panel
        for arm in arms
    ]
    plan = {
        "schema": "hepta.verify1.engineering-plan.v1",
        "source_sha256": source,
        "training": training,
        "calibration": calibration,
        "confirmation": confirmation,
        "execution_roster": roster,
        "arms": ARMS,
        "optional_budget_units": 0.6,
        "check_cost_input_units": 0.2,
        "terminal_check_reserved_separately": True,
        "thresholds": [0, 0.1, 0.25, 0.5, 0.75, 1],
        "terminal_step_meaning": "fixed scheduled decision horizon; early stops retain this comparison point",
        "risk_coverage_score": "frozen initial history probability before any trajectory observation",
        "split_construction": "distinct value ranges per split; repeated engineering templates; no source independence claim",
        "model_arms": {
            arm: {
                "status": "NOT_RUN",
                "model_artifact_sha256": None,
                "inference_receipt_count": 0,
                "reason": "requires original model artifacts, output receipts, independent real tasks and cost meters",
            }
            for arm in MODEL_ARMS
        },
        "source_groups_are_independent_real_tasks": False,
    }
    (output / "plan.json").write_text(c.canonical_json(plan) + "\n")
    recorder, history, failures, all_rows = (
        Recorder(output),
        defaultdict(lambda: [0, 0]),
        [],
        [],
    )
    for case in training:
        row, observations, failed = run_one(recorder, case, "fixed_check_time", {})
        all_rows.append(row)
        if failed:
            failures.append(failed)
        elif row["outcome_error"] is not None:
            key = (
                "missing_ack"
                if any(not observation["ack"] for observation in observations)
                else "ack_present"
            )
            history[key][0] += 1
            history[key][1] += row["outcome_error"]
    history = {key: tuple(value) for key, value in history.items()}
    (output / "history-model.json").write_text(c.canonical_json(history) + "\n")
    frozen_model = c.digest(history)
    if failures or any(row["outcome_error"] is None for row in all_rows):
        return finish(
            output,
            plan,
            recorder,
            all_rows,
            failures,
            started,
            history,
            frozen_model,
            "train",
        )
    calibration_predictions = []
    for case in calibration:
        row, observations, failed = run_one(recorder, case, "fixed_check_time", history)
        all_rows.append(row)
        if failed:
            failures.append(failed)
        if row["outcome_error"] is not None:
            calibration_predictions.append(
                {
                    "trajectory_id": row["trajectory_id"],
                    "source_group": row["source_group"],
                    "risk": row["risk"],
                    "outcome_error": row["outcome_error"],
                }
            )
    if len(calibration_predictions) != len(calibration) or failures:
        return finish(
            output,
            plan,
            recorder,
            all_rows,
            failures,
            started,
            history,
            frozen_model,
            "calibration",
        )
    (output / "calibration-data.json").write_text(
        c.canonical_json(calibration_predictions) + "\n"
    )
    identity = c.ModelIdentity(
        c.digest(history), None, c.digest({"arm": "fixed_check_time", "version": 1})
    )
    report = c.CalibrationReport(
        c.Scope(
            "calibration-panel",
            "fixed-check-time-initial-history-risk",
            c.digest(calibration),
            0,
            "sqlite_two_field_engineering_fixture_v1",
            "terminal_goal_value_error",
            0,
            4,
        ),
        identity,
        tuple(sorted({case["source_group"] for case in training})),
        tuple(sorted({case["source_group"] for case in calibration})),
        tuple(sorted({case["source_group"] for case in confirmation})),
        c.digest(calibration_predictions),
        "brier",
        "proper_scoring_rule",
        sum(
            (row["risk"] - row["outcome_error"]) ** 2 for row in calibration_predictions
        )
        / len(calibration_predictions),
        len(calibration_predictions),
        "unknown",
        (
            "engineering_templates_only",
            "no_exchangeability_or_coverage_claim",
            "frozen_initial_history_prediction",
            "fixed_check_time_labels_only",
            "not_calibrated_for_other_policies_or_step_conditioned_scores",
        ),
    )
    (output / "calibration.json").write_text(c.canonical_json(report) + "\n")
    for case in confirmation:
        for arm in ARMS:
            row, _, failed = run_one(recorder, case, arm, history)
            all_rows.append(row)
            if failed:
                failures.append(failed)
    (output / "interventions.json").write_text(
        c.canonical_json(intervention_report(history)) + "\n"
    )
    return finish(
        output, plan, recorder, all_rows, failures, started, history, frozen_model
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--groups", type=int, default=4)
    args = parser.parse_args()
    result = run(args.output, args.groups)
    print(
        c.canonical_json(
            {
                key: result[key]
                for key in (
                    "status",
                    "planned_confirmation_rows",
                    "observed_confirmation_rows",
                    "model_inferences_executed",
                    "scientific_acceptance",
                    "source_unchanged",
                )
            }
        )
    )
    if result["status"] != "ENGINEERING_SMOKE_PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
