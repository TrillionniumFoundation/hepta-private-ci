"""Fresh current-policy rollouts with unchanged business verification."""

import copy
import hashlib
from pathlib import Path
import time

from .. import data
from ..coding_sft import write_new
from ..protocol_v3 import execution_summary, require_prepared
from .onpolicy_feedback import SCHEMA as FEEDBACK_SCHEMA, feedback


def attempts(predictor, record, directory, *, maximum=2, execute=True):
    """Persist each actual request/output before interpretation or feedback."""
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError("one to four attempts required")
    if type(execute) is not bool:
        raise ValueError("explicit execution mode required")
    messages = copy.deepcopy(require_prepared(record))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    model_digest, generation_digest = predictor.model_digest, predictor.generation_digest
    write_new(directory / "INTENT.json", {
        "record_digest": data.digest(record), "model_digest": model_digest,
        "generation_digest": generation_digest, "maximum_attempts": maximum,
        "execute": execute, "feedback_schema": FEEDBACK_SCHEMA,
        "started_at_ns": time.time_ns(), "automatic_retry": False,
    })
    steps = []
    try:
        for number in range(maximum):
            request = {"record_id": record["record_id"], "task": {
                "input": record["task"]["input"], "messages": copy.deepcopy(messages)}}
            write_new(directory / f"request-{number}.json", request)
            output = predictor.predict(copy.deepcopy(request))
            write_new(directory / f"output-{number}.json", output)
            expected = {
                "loaded_model_digest": model_digest,
                "generation_config_sha256": generation_digest,
                "input_sha256": hashlib.sha256(request["task"]["input"].encode()).hexdigest(),
                "messages_sha256": data.digest(request["task"]["messages"]),
            }
            if predictor.model_digest != model_digest or any(
                output.get(key) != value for key, value in expected.items()
            ):
                raise ValueError("output is not from the recorded current policy and request")
            if any(type(output.get(key)) is not int or output[key] < 0
                   for key in ("input_tokens", "output_tokens")):
                raise ValueError("actual token counts are required")
            verification = None
            if execute:
                write_new(directory / f"verify-request-{number}.json", {
                    "record_digest": data.digest(record), "output_digest": data.digest(output),
                    "started_at_ns": time.time_ns(), "automatic_retry": False})
                verification = data.verify_answer(record, output["answer"])
                write_new(directory / f"verification-{number}.json", verification)
            observation = feedback(verification) if execute else data.canonical({
                "schema": FEEDBACK_SCHEMA, "semantic_measurement": "unmeasured",
                "execution_performed": False, "instruction": "Shadow output was not executed."
            }).decode()
            step = {
                "number": number, "request_sha256": data.digest(request), "output": output,
                "verification": verification,
                "execution_summary": execution_summary(verification) if execute else None,
                "semantic_measurement": "measured" if execute else "unmeasured",
                "feedback": observation,
                "executed": bool(verification and verification["result"].get("executed", False)),
            }
            step["receipt_sha256"] = data.digest(step)
            write_new(directory / f"step-{number}.json", step)
            steps.append(step)
            messages.extend([{"role": "assistant", "content": output["answer"]},
                             {"role": "tool", "content": observation}])
            if not execute or verification["success"]:
                break
        result = {
            "schema": "hepta.current-policy-rollout.v1", "record_id": record["record_id"],
            "task_id": record["task_id"], "source_id": record["source_id"],
            "lineage_id": record["lineage_id"], "model_digest": model_digest,
            "generation_digest": generation_digest, "steps": steps,
            "success": steps[-1]["verification"]["success"] if execute else None,
            "first_attempt_success": steps[0]["verification"]["success"] if execute else None,
            "semantic_measurement": "measured" if execute else "unmeasured",
            "attempts_are_independent_tasks": False, "independent_sample_increment": 0,
        }
        write_new(directory / "RESULT.json", result)
        return result
    except BaseException as error:
        write_new(directory / "FAILED.json", {
            "status": "FAILED_PRESERVED", "error_type": type(error).__name__,
            "error": str(error), "completed_steps": len(steps),
            "call_totals_complete": False, "automatic_retry": False})
        raise


def collect_current(records, manifest, root, output, loader, *, maximum=2, execute=True):
    """Load one explicit candidate; never reuse previous generation observations."""
    if not records or any(row["split"] != "train" for row in records):
        raise ValueError("current-policy collection requires nonempty A only")
    for row in records:
        require_prepared(row)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    expected = data.digest(manifest)
    write_new(output / "COLLECTION_INTENT.json", {
        "model_digest": expected, "records_digest": data.digest(records),
        "maximum_attempts": maximum, "execute": execute,
        "reused_observation_count": 0, "automatic_retry": False})
    predictor = loader(manifest, root)
    try:
        if predictor.model_digest != expected:
            raise ValueError("loaded candidate differs from this round's manifest")
        rows = [attempts(predictor, row, output / str(index), maximum=maximum, execute=execute)
                for index, row in enumerate(records)]
    finally:
        predictor.close()
    steps = [step for row in rows for step in row["steps"]]
    result = {
        "schema": "hepta.current-policy-collection.v1", "model_digest": expected,
        "rows": rows, "records_digest": data.digest(records),
        "model_calls": len(steps), "student_verifier_calls": len(steps) if execute else 0,
        "input_tokens": sum(s["output"]["input_tokens"] for s in steps),
        "output_tokens": sum(s["output"]["output_tokens"] for s in steps),
        "reused_observation_count": 0, "independent_sample_increment": 0,
        "complete": True, "full_system_cost_complete": False,
    }
    write_new(output / "COLLECTION.json", result)
    return result
