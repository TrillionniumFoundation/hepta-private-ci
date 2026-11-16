"""Visible student attempts, bounded repository tests and feedback without gold."""

import copy
from pathlib import Path
import time

from . import coding_sft, data


def feedback(verification):
    """Expose only test observations; no fixture, oracle or expected answer text."""
    result = verification["result"]
    return data.canonical(
        {
            "success": verification["success"],
            "reason": result.get("reason", "semantic_test_result"),
            "execution_performed": result.get("executed", False),
            "mutants_killed": result.get("controls_rejected"),
            "mutants_total": (result.get("result") or {}).get("control_count"),
            "instruction": "Return a corrected JSON edit if the tests failed.",
        }
    ).decode()


def attempts(predictor, record, directory, *, maximum=2, execute=True):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    messages = copy.deepcopy(
        record["task"].get(
            "messages", [{"role": "user", "content": record["task"]["input"]}]
        )
    )
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
        output = predictor.predict(request)
        if output["loaded_model_digest"] != predictor.model_digest:
            raise ValueError("student policy differs from loaded model")
        coding_sft.write_new(directory / f"output-{number}.json", output)
        verification = data.verify_answer(record, output["answer"]) if execute else None
        observation = (
            feedback(verification)
            if execute
            else "Shadow prediction was recorded without applying the patch or executing tests."
        )
        step = {
            "number": number,
            "output": output,
            "verification": verification,
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
        "success": bool(
            steps[-1]["verification"] and steps[-1]["verification"]["success"]
        ),
        "first_attempt_success": bool(
            steps[0]["verification"] and steps[0]["verification"]["success"]
        ),
        "attempts_are_independent_tasks": False,
    }
    coding_sft.write_new(directory / "RESULT.json", result)
    return result


def corrected_record(original, observed, mode):
    """A correction is an authored A-only target, never a new source or teacher."""
    record = copy.deepcopy(original)
    record["record_id"] += "/" + mode
    record["teacher_id"] = None
    events = []
    for step in observed["steps"]:
        events.append(
            {
                "actor": "student",
                "kind": "action",
                "content": step["output"]["answer"],
                "executed": step["executed"],
                "receipt_sha256": step["receipt_sha256"],
                "policy_sha256": step["output"]["loaded_model_digest"],
                "receipt_actor": "student",
                "trainable": False,
            }
        )
        events.append(
            {
                "actor": "environment",
                "kind": "observation",
                "content": step["feedback"],
                "executed": False,
                "trainable": False,
            }
        )
    events.append(
        {
            "actor": "curator",
            "kind": "correction",
            "content": original["final_answer"],
            "executed": False,
            "trainable": True,
        }
    )
    record["trajectory"] = [{"index": i, **event} for i, event in enumerate(events)]
    record["derivation"] = {
        "original_record_digest": data.digest(original),
        "mode": mode,
        "student_attempts_digest": data.digest(observed),
        "independent_sample_increment": 0,
        "correction_origin": "verified authored reference on training split only",
    }
    data.validate_record(record)
    return record


def collect(records, parent, root, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if any(r["split"] != "train" for r in records):
        raise ValueError("corrections must use A only")
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
    report = {
        "schema": "hepta.repository-interaction.v2",
        "wall_seconds": time.perf_counter() - started,
        "student_policy": data.digest(parent),
        "task_count": len(records),
        "cohorts": {
            name: {
                "records": len(rows),
                "model_calls": sum(len(r["steps"]) for r in receipts[name]),
                "executed_attempts": sum(
                    s["executed"] for r in receipts[name] for s in r["steps"]
                ),
                "successful_tasks": sum(r["success"] for r in receipts[name]),
                "records_digest": data.digest(rows),
            }
            for name, rows in cohorts.items()
        },
        "external_teacher_trajectories": False,
        "independent_sample_increment": 0,
    }
    coding_sft.write_new(output / "COLLECTION.json", report)
    return cohorts, report


def evaluate(manifest, root, records, output, *, maximum=1, prompt_records=None):
    """Execute actual candidate assertions against fixed original and mutant code."""
    predictor = coding_sft.load_predictor(manifest, root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start, cpu, wall = time.time_ns(), time.process_time(), time.perf_counter()
    rows = []
    try:
        for index, record in enumerate(records):
            shown = copy.deepcopy(record)
            if prompt_records is not None:
                shown["task"]["input"] = prompt_records[index]["task"]["input"]
                if "messages" in prompt_records[index]["task"]:
                    shown["task"]["messages"] = copy.deepcopy(
                        prompt_records[index]["task"]["messages"]
                    )
                else:
                    shown["task"].pop("messages", None)
            observed = attempts(predictor, shown, output / str(index), maximum=maximum)
            observed["task_digest"] = data.digest(record)
            observed["original_input_sha256"] = data.digest(record["task"]["input"])
            rows.append(observed)
    finally:
        predictor.close()
    receipt = {
        "schema": "hepta.repository-evaluation.v2",
        "status": "COMPLETE",
        "model_digest": data.digest(manifest),
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
