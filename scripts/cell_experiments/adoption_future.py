"""Distinct cold-process tasks and measured inference costs, engineering only."""

import os
import time
from pathlib import Path


def validate_d(request, api):
    plan = request["plan"]
    if "d_tasks" not in plan and "d_tasks" not in request:
        return
    declared, supplied = plan.get("d_tasks"), request.get("d_tasks")
    api.require(
        isinstance(declared, list)
        and 0 < len(declared) <= 64
        and isinstance(supplied, list)
        and len(supplied) == len(declared),
        "complete frozen D panel required",
        "BLOCKED",
    )
    from .data import validate_record

    previous = plan["b_tasks"] + plan["c_tasks"]
    sources = set(plan["train_sources"]) | {t["source_id"] for t in previous}
    ids, digests = (
        {t["task_id"] for t in previous},
        {t["task_digest"] for t in previous},
    )
    for frozen, task in zip(declared, supplied):
        api.need(frozen, "task_id task_digest source_id")
        api.need(task, "task_id task_digest source_id record")
        validate_record(task["record"], require_outcome=False)
        api.require(
            all(task[k] == frozen[k] for k in ("task_id", "task_digest", "source_id"))
            and all(task[k] == task["record"][k] for k in ("task_id", "source_id"))
            and task["record"]["split"] == "confirmation"
            and api.digest(task["record"]) == task["task_digest"],
            "D changed since freeze or has wrong split",
        )
        api.require(
            task["source_id"] not in sources, "D source overlaps A/B/C", "BLOCKED"
        )
        api.require(
            task["task_id"] not in ids and task["task_digest"] not in digests,
            "D repeats an existing task",
        )
        ids.add(task["task_id"])
        digests.add(task["task_digest"])


def admit_d(spec, api):
    """Reserve the original cold attempt before loading or running any model."""
    root = Path(spec["database"]).parent
    request = api.read_json(root / "REQUEST.json")
    api.require(
        api.digest(request) == spec["binding"]
        and api.read_json(root / "COLD_REQUEST.json") == spec,
        "cold request differs from the original frozen operation",
    )
    # The original request decides whether D admission is mandatory. Caller
    # fields cannot downgrade an operation into the legacy replay-only path.
    if "d_tasks" not in request:
        return
    validate_d(request, api)
    api.require(
        spec["d_tasks"] == request["d_tasks"]
        and spec["record"] == request["c_tasks"][-1]["record"]
        and spec["replay_expected"]
        == api.comparable(api.read_json(root / "C_RECEIPTS.json")[-1]["prediction"]),
        "cold D request differs from original selection or C",
    )
    api.require(
        not (root / "D_RECEIPTS.json").exists(),
        "D already has execution material",
        "INCOMPLETE",
    )
    marker = dict(
        schema="hepta.e6.cold-admission.v1",
        binding=spec["binding"],
        spec_digest=api.digest(spec),
    )
    try:
        with (root / "COLD_ADMISSION.json").open("xb") as stream:
            stream.write(api.canonical(marker) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise api.EvidenceError(
            "INCOMPLETE", "original cold attempt requires reconciliation"
        ) from error
    if os.name != "nt":
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def execute_d(predictor, spec, selected, replay, api):
    """Run D only after the original last-C replay has matched."""
    if "d_tasks" not in spec:
        return None
    api.require(
        api.comparable(replay) == spec["replay_expected"],
        "cold replay differs before D",
    )
    from .data import verify_answer

    rows = []
    for task in spec["d_tasks"]:
        started = time.time_ns()
        prediction = api.prediction(predictor, task["record"], selected)
        rows.append(
            dict(
                task_id=task["task_id"],
                task_digest=task["task_digest"],
                source_id=task["source_id"],
                prediction=prediction,
                outcome=verify_answer(task["record"], prediction["answer"]),
                started_at_ns=started,
                completed_at_ns=time.time_ns(),
            )
        )
        api.save(Path(spec["database"]).parent / "D_RECEIPTS.json", rows)
    return rows


def measured_costs(report):
    phases = {
        "hot_C": [r["prediction"] for r in report["C"]],
        "cold_C_replay": [report["cold"]["prediction"]],
        "cold_D": [r["prediction"] for r in report.get("D", [])],
    }
    return {
        "scope": "inference only; replay counted separately; process wall time overlaps inference",
        "phases": {
            name: dict(
                model_calls=len(rows),
                input_tokens=sum(r["input_tokens"] for r in rows),
                output_tokens=sum(r["output_tokens"] for r in rows),
                reported_prediction_seconds=sum(r["elapsed_seconds"] for r in rows),
            )
            for name, rows in phases.items()
        },
        "training_and_B_costs": None,
        "energy_joules": None,
        "complete_physical_costs": False,
    }
