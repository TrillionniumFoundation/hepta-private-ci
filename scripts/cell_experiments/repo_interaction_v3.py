"""Bounded v3 student interaction using unchanged v2 generation and verifier.

Call protocol_v3.prepare_record before freezing a task panel. For SFT, explicitly
rebind authored reference outcomes with protocol_v3.verify_reference. Neither
reference is ever substituted for a generated output or sent in a request.
"""

import copy
import hashlib
from pathlib import Path
import time

from . import coding_sft, data
from .protocol_v3 import execution_summary, feedback, require_prepared
from .repo_interaction_v2 import corrected_record


def attempts(predictor, record, directory, *, maximum=2, execute=True):
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError("one to four bounded attempts required")
    if type(execute) is not bool:
        raise ValueError("execution mode must be an explicit boolean")
    messages = require_prepared(record)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    coding_sft.write_new(directory / "PROTOCOL.json", record["action_protocol_v3"])
    steps = []
    for number in range(maximum):
        request = {
            "record_id": record["record_id"],
            "task": {
                "input": record["task"]["input"],
                "messages": copy.deepcopy(messages),
            },
        }
        coding_sft.write_new(directory / f"request-{number}.json", request)
        request_digest = data.digest(request)
        input_digest = hashlib.sha256(request["task"]["input"].encode()).hexdigest()
        messages_digest = data.digest(request["task"]["messages"])
        output = predictor.predict(copy.deepcopy(request))
        # Retain the raw generator return even when its policy binding is invalid.
        coding_sft.write_new(directory / f"output-{number}.json", output)
        if output["loaded_model_digest"] != predictor.model_digest:
            raise ValueError("student policy differs from loaded model")
        if output.get("input_sha256") != input_digest:
            raise ValueError("student output input differs from the recorded request")
        if "messages_sha256" in output and output["messages_sha256"] != messages_digest:
            raise ValueError("student output history differs from the recorded request")
        verification = data.verify_answer(record, output["answer"]) if execute else None
        observation = (
            feedback(verification)
            if execute
            else (
                "Shadow prediction was recorded without applying the patch "
                "or executing tests."
            )
        )
        step = {
            "number": number,
            "request_sha256": request_digest,
            "output": output,
            "verification": verification,
            "execution_summary": execution_summary(verification) if execute else None,
            "semantic_measurement": "measured" if execute else "unmeasured",
            "feedback": observation,
            "executed": bool(
                verification and verification["result"].get("executed", False)
            ),
        }
        step["receipt_sha256"] = data.digest(step)
        coding_sft.write_new(directory / f"step-{number}.json", step)
        steps.append(step)
        messages.extend(
            [
                {"role": "assistant", "content": output["answer"]},
                {"role": "tool", "content": observation},
            ]
        )
        if not execute or verification["success"]:
            break
    result = {
        "record_id": record["record_id"],
        "task_id": record["task_id"],
        "source_id": record["source_id"],
        "lineage_id": record["lineage_id"],
        "steps": steps,
        "success": steps[-1]["verification"]["success"] if execute else None,
        "first_attempt_success": steps[0]["verification"]["success"]
        if execute
        else None,
        "semantic_measurement": "measured" if execute else "unmeasured",
        "attempts_are_independent_tasks": False,
    }
    coding_sft.write_new(directory / "RESULT.json", result)
    return result


def collect(records, parent, root, output):
    """Collect A-only student feedback; authored corrections remain labeled."""
    if not records or any(r["split"] != "train" for r in records):
        raise ValueError("corrections must use nonempty A only")
    for record in records:
        require_prepared(record)
        data.validate_record(record)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    predictor = coding_sft.load_predictor(parent, root)
    started = time.perf_counter()
    cohorts, receipts = {}, {}
    try:
        for name in ("shadow", "controlled"):
            rows, results = [], []
            for index, record in enumerate(records):
                observed = attempts(
                    predictor,
                    record,
                    output / name / str(index),
                    maximum=2 if name == "controlled" else 1,
                    execute=name == "controlled",
                )
                rows.append(corrected_record(record, observed, name))
                results.append(observed)
            cohorts[name], receipts[name] = rows, results
            coding_sft.write_new(output / (name + ".records.json"), rows)
    finally:
        predictor.close()
    cohort_metrics = {}
    for name, rows in cohorts.items():
        steps = [step for row in receipts[name] for step in row["steps"]]
        counts = [
            (step["execution_summary"] or {}).get("subject_call_count")
            for step in steps
        ]
        measured = [count for count in counts if type(count) is int and count >= 0]
        missing = len(counts) - len(measured)
        outcomes = [row["success"] for row in receipts[name]]
        outcomes_measured = all(type(value) is bool for value in outcomes)
        cohort_metrics[name] = {
            "records": len(rows),
            "model_calls": len(steps),
            "executed_attempts": sum(step["executed"] for step in steps),
            "completed_original_calls": sum(measured) if missing == 0 else None,
            "completed_original_calls_measured_subtotal": sum(measured)
            if measured
            else None,
            "completed_original_calls_measured_attempts": len(measured),
            "completed_original_calls_missing_attempts": missing,
            "completed_original_call_count_complete": missing == 0,
            "successful_tasks": sum(outcomes) if outcomes_measured else None,
            "semantic_measurement": "measured" if outcomes_measured else "unmeasured",
            "records_digest": data.digest(rows),
        }
    report = {
        "schema": "hepta.repository-interaction.v3",
        "wall_seconds": time.perf_counter() - started,
        "student_policy": data.digest(parent),
        "task_count": len(records),
        "cohorts": cohort_metrics,
        "external_teacher_trajectories": False,
        "independent_sample_increment": 0,
    }
    coding_sft.write_new(output / "COLLECTION.json", report)
    return cohorts, report


def evaluate(manifest, root, records, output, *, maximum=1, prompt_records=None):
    """Measure actual original/control execution; syntax admission is not success."""
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError("one to four bounded attempts required")
    if not records or (
        prompt_records is not None and len(prompt_records) != len(records)
    ):
        raise ValueError("nonempty aligned task records required")
    for record in records:
        require_prepared(record)
    if prompt_records is not None:
        for record, prompt in zip(records, prompt_records):
            require_prepared(prompt)
            # Only the visible prompt and its freshly bound protocol/reference
            # evidence may vary. All provenance, authorization, times, labels
            # and non-prompt task fields, including the verifier, stay fixed.
            variable = {
                "task",
                "action_protocol_v3",
                "protocol_reference_receipt",
                "verified_outcome",
            }
            identities = [
                {
                    "record": {
                        key: value for key, value in item.items() if key not in variable
                    },
                    "task": {
                        key: value
                        for key, value in item["task"].items()
                        if key not in ("input", "messages")
                    },
                }
                for item in (record, prompt)
            ]
            if data.digest(identities[0]) != data.digest(identities[1]):
                raise ValueError(
                    "prompt records must preserve task identity and provenance"
                )
    shown_records = copy.deepcopy(
        prompt_records if prompt_records is not None else records
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    coding_sft.write_new(output / "ORIGINAL_PANEL.json", records)
    coding_sft.write_new(output / "SHOWN_PANEL.json", shown_records)
    predictor = coding_sft.load_predictor(manifest, root)
    start, cpu, wall = time.time_ns(), time.process_time(), time.perf_counter()
    rows = []
    try:
        for index, (record, shown) in enumerate(zip(records, shown_records)):
            observed = attempts(predictor, shown, output / str(index), maximum=maximum)
            observed["task_digest"] = data.digest(record)
            observed["original_input_sha256"] = data.digest(record["task"]["input"])
            observed["shown_task_digest"] = data.digest(shown)
            observed["shown_input_sha256"] = data.digest(shown["task"]["input"])
            rows.append(observed)
    finally:
        predictor.close()
    receipt = {
        "schema": "hepta.repository-evaluation.v3",
        "status": "COMPLETE",
        "model_digest": data.digest(manifest),
        "original_panel_digest": data.digest(records),
        "shown_panel_digest": data.digest(shown_records),
        "started_at_ns": start,
        "completed_at_ns": time.time_ns(),
        "rows": rows,
        "successes": sum(r["success"] for r in rows),
        "first_attempt_successes": sum(r["first_attempt_success"] for r in rows),
        "tasks": len(records),
        "maximum_attempts": maximum,
        "cost": {
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu,
            "input_tokens": sum(
                s["output"]["input_tokens"] for r in rows for s in r["steps"]
            ),
            "output_tokens": sum(
                s["output"]["output_tokens"] for r in rows for s in r["steps"]
            ),
            "model_calls": sum(len(r["steps"]) for r in rows),
            "cap_exhaustions": sum(
                s["output"].get("hit_output_limit", False)
                for r in rows
                for s in r["steps"]
            ),
            "cpu_scope": "evaluation parent only; verifier subprocess CPU excluded",
            "complete": False,
        },
    }
    coding_sft.write_new(output / "EVALUATION.json", receipt)
    return receipt
