"""Read-only admission and original-evidence checks for stopped collection.

Source selection uses registered metadata, and training admission requires actual
completed v2 observations. These checks do not authenticate a native Cell owner.
"""

from collections import defaultdict
import hashlib
from pathlib import Path

from ndu_real_materials.common import read_relative, strict_json
from .span_meter import record_from_jsonl, verify_record
from .training import validate_record
from .trajectory import V2_SCHEMA, validate_chains


SCHEMA = "ndu.real.stopped-collection-plan.v1"


BEHAVIOR_SHA = "db6e3d05270163368d10176299a7d5be3ccee2d8e773fcfbb32454ff1c0f9f54"


SCHEDULES = {
    "continuation_not_worthwhile": ["STOP"],
    "preparation_required": ["PREPARE_ROI", "READ_ROI", "STOP"],
    "selective_refinement": ["PREPARE_ROI", "STOP"],
    "text_image_complementary": ["RENDER_IMAGE", "STOP"],
    "text_sufficient": ["WRITE_TEXT", "STOP"],
}


PREPARATION_FILES = (
    "selection-plan.json",
    "selected-cases.json",
    "native-config.template.json",
    "control-plan.json",
)


def read_original(path, expected=None):
    path = Path(path)
    raw = read_relative(path.parent, path.name, limit=64 * 1024 * 1024)
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError("Original bytes differ from pin: " + str(path))
    return raw, {"path": str(path), "sha256": digest, "bytes": len(raw)}


def verify_selection(selection, selected, catalog, previous, quarantined):
    """Recompute selection using registry metadata; no reference labels."""
    if (
        selection.get("schema") != "ndu.portfolio.fresh-selection.v1"
        or selection.get("confirmation_access") is not False
        or selection.get("isolator_change_authorized") is not False
        or selection.get("maximum_episodes") != 60
        or selection.get("collection_wall_limit_seconds") != 600
        or selection.get("weights_sha256") != BEHAVIOR_SHA
        or not isinstance(selected, list)
        or len(selected) != 60
    ):
        raise ValueError("Unknown or expanded stopped collection contract")
    if (
        previous["groups"]["training"] != selection["original_fit_groups"]
        or previous["groups"]["tuning"] != selection["original_tuning_groups"]
        or len(selection["original_fit_groups"]) != 40
        or len(selection["original_tuning_groups"]) != 8
    ):
        raise ValueError("Original fitting/tuning roster differs")
    excluded = set(
        selection["original_fit_groups"] + selection["original_tuning_groups"]
    )
    excluded.update(quarantined)
    train, by_id = defaultdict(list), {}
    for case in catalog:
        if case["id"] in by_id:
            raise ValueError("Duplicate registered case identity")
        by_id[case["id"]] = case
        if case["role"] == "train" and case["source_id"] not in excluded:
            train[case["source_id"]].append(case)
    ordered = lambda values: sorted(  # noqa: E731 - Preserve the reviewed AST.
        values, key=lambda v: hashlib.sha256(v.encode()).digest()
    )
    available = ordered(train)
    groups = {"calibration": available[:6], "diagnostic": available[6:12]}
    if len(available) < 12 or selection["groups"] != groups:
        raise ValueError("Source roster is not the frozen first twelve")
    expected = []
    for phase, identities in groups.items():
        for group in identities:
            episodes = defaultdict(list)
            for case in train[group]:
                episodes[case["episode_group"]].append(case)
            complete = [
                name
                for name, cases in episodes.items()
                if len(cases) == 5
                and {c["task_family"] for c in cases} == set(SCHEDULES)
            ]
            if not complete:
                raise ValueError("Frozen source lacks a complete five-family receipt")
            cases = sorted(
                episodes[ordered(complete)[0]], key=lambda c: c["task_family"]
            )
            expected.extend(
                {"case": c, "exploration": SCHEDULES[c["task_family"]], "phase": phase}
                for c in cases
            )
    if selected != expected:
        raise ValueError("Cases/actions/phase differ from the fixed selection")
    return groups


def verify_frozen(root, expected_sha256):
    root = Path(root)
    plan = strict_json(read_original(root / "COLLECTION_PLAN.json", expected_sha256)[0])
    if plan.get("schema") != SCHEMA or len(plan["requests"]) != 60:
        raise ValueError("Unknown frozen collection plan")
    for pin in [*plan["original_pins"], *plan["source_pins"], *plan["requests"]]:
        read_original(pin["path"], pin["sha256"])
    read_original(root / "execution-config.json", plan["execution_config_sha256"])
    return plan


def verify_completed(request, result, launch, trajectory, raw_rows, plan):
    """Validate actual host artifacts; never upgrade legacy or incomplete rows."""
    expected = {
        "schema": "ndu.real.episode-result.v1",
        "terminal_status": "Completed",
        "original_operation_id": request["profile"]["original_operation_id"],
        "case_id": request["case"]["id"],
        "source_group_id": request["case"]["source_id"],
        "split": "train",
        "memory_mode": "reset",
        "model_sha256": BEHAVIOR_SHA,
        "rubric_sha256": request["config"]["rubric_sha256"],
        "actions": request["exploration"],
        "confirmation_evaluated": False,
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("Original completed episode differs from its request")
    if (
        launch.get("schema") != "ndu.real.actor-isolation.v1"
        or launch.get("enforced_before_actor_exec") is not True
        or launch.get("exit_code") != 0
        or any(
            launch.get(key)
            for key in ("limit_reason", "protocol_error", "callback_error")
        )
        or launch.get("launcher_source_sha256") != plan["isolator_sha256"]
    ):
        raise ValueError("Original isolation result is incomplete or differs")
    steps = trajectory["steps"]
    if [s["action"]["action"] for s in steps] != request["exploration"] or any(
        s.get("parameters_unchanged") is not True
        or s.get("weights_sha256") != BEHAVIOR_SHA
        for s in steps
    ):
        raise ValueError("Actual action sequence/model differs from fixed exploration")
    if not raw_rows.endswith(b"\n"):
        raise ValueError("Incomplete original training JSONL")
    rows = [validate_record(strict_json(line)) for line in raw_rows.splitlines()]
    if (
        len(rows) != len(steps)
        or any(
            row["schema"] != V2_SCHEMA
            or row["execution_status"] != "completed"
            or row["origin_run_id"] != expected["original_operation_id"]
            or row["episode_id"] != expected["case_id"]
            or row["source_group"] != expected["source_group_id"]
            or row["memory_mode"] != "reset"
            or row.get("behavior_weights_sha256") != BEHAVIOR_SHA
            or row["rubric_sha256"] != result["rubric_sha256"]
            or row["utility_profile_sha256"] != result["utility_profile_sha256"]
            or row["behavior_control_profile_sha256"]
            != result["control_profile_sha256"]
            for row in rows
        )
        or [r["action"] for r in rows] != request["exploration"]
    ):
        raise ValueError("Training rows are not the actual completed v2 episode")
    validate_chains(rows)
    for row, step in zip(rows, steps):
        if (
            any(
                row[key] != step[key]
                for key in (
                    "candidate_features",
                    "candidate_metadata",
                    "public_metadata",
                    "remaining_seconds",
                    "legal_actions",
                )
            )
            or row["duration_seconds"] != step["observed_action_seconds"]
        ):
            raise ValueError(
                "Training content/cost differs from the original actor observation"
            )
    if (
        rows[-1]["after_score"] != result["gross_score"]
        or rows[-1]["terminal_reason"] != "actor_stop"
    ):
        raise ValueError("Final observed score/termination differs from training rows")
    return rows


def readback_attempt(entry, plan, root):
    directory = Path(root) / "attempts" / entry["operation"]
    item = {
        "operation": entry["operation"],
        "phase": entry["phase"],
        "status": "Unstarted",
        "training_rows": 0,
    }
    if not directory.exists():
        return item, b""
    item["status"] = "Unresolved"
    try:
        receipt = strict_json(read_original(directory / "attempt.json")[0])
        item.update(
            outer_wall_seconds=receipt["outer_wall_seconds"],
            supervision=receipt["supervision"],
        )
        if (
            receipt["request_sha256"] != entry["sha256"]
            or receipt["operation"] != entry["operation"]
        ):
            raise ValueError("Original attempt/request binding differs")
        for stream in ("stdout", "stderr"):
            read_original(directory / (stream + ".log"), receipt[stream + "_sha256"])
        supervised = receipt["supervision"]
        if not supervised["cleanup_complete"]:
            raise ValueError("Original process supervision remains unresolved")
        item["status"] = "Failed"
        request = strict_json(read_original(entry["path"], entry["sha256"])[0])
        output = Path(request["output"])
        raw, pin = read_original(output / "result.json")
        result = strict_json(raw)
        item.update(
            result=pin,
            terminal_status=result.get("terminal_status"),
            deployment_wall_seconds=result.get("deployment_meter", {}).get(
                "wall_seconds"
            ),
            evaluation_wall_seconds=result.get("evaluation_meter", {}).get(
                "wall_seconds"
            ),
        )
        if supervised["returncode"] != 0 or supervised["error"] is not None:
            raise ValueError(
                "Original episode supervisor did not complete successfully"
            )
        launch = strict_json(read_original(output / "launch.json")[0])
        trajectory = strict_json(read_original(output / "trajectory.json")[0])
        raw_rows, row_pin = read_original(output / "training-rows.jsonl")
        rows = verify_completed(request, result, launch, trajectory, raw_rows, plan)
        scores = []
        for index in range(len(rows) + 1):
            score = strict_json(
                read_original(output / f"delivery-{index:02d}" / "evaluation.json")[0]
            )
            if (
                score["evaluator_source_sha256"]
                != request["config"]["evaluator_sha256"]
            ):
                raise ValueError("Original post-actor evaluator source differs")
            scores.append(score["quality"])
        if any(
            row["before_score"] != scores[index]
            or row["after_score"] != scores[index + 1]
            for index, row in enumerate(rows)
        ):
            raise ValueError("Training quality differs from original evaluator outputs")
        for key, name in (
            ("deployment_meter", "deployment.meter.jsonl"),
            ("evaluation_meter", "evaluation.meter.jsonl"),
        ):
            meter = result[key]
            record = record_from_jsonl(read_original(output / name)[0])
            replay = verify_record(record, expected_sha256=meter["raw_spans_sha256"])
            if (
                not replay["valid"]
                or not replay["complete_record"]
                or record != meter["raw_spans"]
            ):
                raise ValueError("Original meter journal does not replay completely")
        if (
            result["deployment_meter"].get("interval_reconciliation")
            != "EXACT_MONOTONIC_INTERVALS_SAME_HOST"
        ):
            raise ValueError("Full deployment interval reconciliation is absent")
        from .interval_costs import actor_receipts

        actors = actor_receipts(
            [step["meter"] for step in trajectory["steps"]], output / "actor-output"
        )
        if sorted(a["raw_spans_sha256"] for a in actors) != sorted(
            result["deployment_meter"]["actor_record_sha256s"]
        ):
            raise ValueError("Original actor journals differ from deployment receipt")
        item.update(
            status="Completed",
            training_rows=len(rows),
            original_training_rows=row_pin,
            gross_score=result["gross_score"],
            source_group=request["case"]["source_id"],
        )
        return item, raw_rows
    except (ValueError, KeyError, TypeError, OSError) as error:
        item["error"] = {"type": type(error).__name__, "message": str(error)}
        return item, b""
