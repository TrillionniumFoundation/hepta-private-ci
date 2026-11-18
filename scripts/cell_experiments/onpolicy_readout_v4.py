"""Read recovery outcomes from bound, actually executed current-policy rollouts."""

import copy
import hashlib

from . import data
from .protocol_v3 import execution_summary, require_prepared


def summarize_collection(collection, records, expected_model_digest, *, maximum=2):
    """Count failures and recovery with explicit denominators; never execute tasks.

    An invalid first action and a failed executed action are separate cohorts.
    Shadow predictions carry no measured success, failure or recovery rate.
    These checks bind retained bytes and do not authenticate their producer.
    """

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(type(maximum) is int and 1 <= maximum <= 4, "bounded attempt cap required")
    require(
        collection.get("schema") == "hepta.current-policy-collection.v1"
        and collection.get("complete") is True
        and collection.get("reused_observation_count") == 0,
        "complete fresh collection required",
    )
    require(
        collection.get("model_digest") == expected_model_digest
        and collection.get("records_digest") == data.digest(records),
        "collection candidate or task binding differs",
    )
    require(
        records and len({r["task_id"] for r in records}) == len(records),
        "nonempty distinct task identities required",
    )
    rows = collection.get("rows")
    require(isinstance(rows, list), "collection rows required")
    teacher = collection.get("collection_mode") == "teacher"
    require(
        len(rows) == (0 if teacher else len(records)), "complete task coverage required"
    )
    if teacher:
        require(
            collection.get("student_called") is False,
            "teacher collection cannot call student",
        )
    totals = dict(
        model_calls=0, student_verifier_calls=0, input_tokens=0, output_tokens=0
    )
    task_rows = []
    for record, row in zip(records, rows):
        require(
            all(
                row.get(k) == record[k]
                for k in ("record_id", "task_id", "source_id", "lineage_id")
            ),
            "rollout task identities or ordering differ",
        )
        require(
            row.get("model_digest") == expected_model_digest,
            "rollout used another candidate",
        )
        steps = row.get("steps")
        require(
            isinstance(steps, list) and 1 <= len(steps) <= maximum,
            "rollout attempt coverage differs",
        )
        measured = row.get("semantic_measurement") == "measured"
        require(
            measured or row.get("semantic_measurement") == "unmeasured",
            "explicit observation mode required",
        )
        require(
            measured or len(steps) == 1, "shadow predictions cannot contain retries"
        )
        messages = copy.deepcopy(require_prepared(record))
        outcomes, executions = [], []
        for number, step in enumerate(steps):
            require(
                step.get("number") == number
                and step.get("receipt_sha256")
                == data.digest(
                    {k: v for k, v in step.items() if k != "receipt_sha256"}
                ),
                "rollout step receipt changed",
            )
            output = step["output"]
            request = {
                "record_id": record["record_id"],
                "task": {
                    "input": record["task"]["input"],
                    "messages": copy.deepcopy(messages),
                },
            }
            require(
                step.get("request_sha256") == data.digest(request)
                and output.get("loaded_model_digest") == expected_model_digest
                and output.get("generation_config_sha256")
                == row.get("generation_digest")
                and output.get("input_sha256")
                == hashlib.sha256(record["task"]["input"].encode()).hexdigest()
                and output.get("messages_sha256") == data.digest(messages),
                "actual request, feedback or loaded candidate differs",
            )
            require(
                isinstance(output.get("answer"), str)
                and isinstance(step.get("feedback"), str),
                "retained output and feedback required",
            )
            for key in ("input_tokens", "output_tokens"):
                require(
                    type(output.get(key)) is int and output[key] >= 0,
                    "measured nonboolean token counts required",
                )
                totals[key] += output[key]
            totals["model_calls"] += 1
            verification = step.get("verification")
            if measured:
                require(
                    isinstance(verification, dict)
                    and type(verification.get("success")) is bool,
                    "actual verifier outcome required",
                )
                summary = execution_summary(verification)
                require(
                    step.get("execution_summary") == summary
                    and type(step.get("executed")) is bool
                    and step["executed"]
                    == bool(verification["result"].get("executed", False)),
                    "execution observation differs from verifier",
                )
                require(
                    verification["success"] is False
                    or summary["execution_performed"] is True,
                    "successful business outcome needs actual execution",
                )
                outcomes.append(verification["success"])
                executions.append(step["executed"])
                totals["student_verifier_calls"] += 1
                require(
                    number == len(steps) - 1 or not verification["success"],
                    "rollout continued after business success",
                )
            else:
                require(
                    verification is None
                    and step.get("executed") is False
                    and step.get("execution_summary") is None,
                    "executed observations cannot be relabeled shadow",
                )
            messages.extend(
                [
                    {"role": "assistant", "content": output["answer"]},
                    {"role": "tool", "content": step["feedback"]},
                ]
            )
        first, final = (outcomes[0], outcomes[-1]) if measured else (None, None)
        require(
            row.get("first_attempt_success") is first and row.get("success") is final,
            "rollout summary differs from actual steps",
        )
        require(
            not measured or final or len(steps) == maximum,
            "failed rollout ended before its declared attempt cap",
        )
        failed = measured and not first
        task_rows.append(
            {
                "task_id": record["task_id"],
                "record_id": record["record_id"],
                "model_digest": expected_model_digest,
                "rollout_digest": data.digest(row),
                "attempts": len(steps),
                "measured": measured,
                "first_attempt_success": first,
                "final_success": final,
                "first_failed_action_executed": executions[0] if failed else None,
                "recovered_after_first_failure": bool(failed and final)
                if measured
                else None,
            }
        )
    require(
        all(
            type(collection.get(k)) is int and collection[k] == value
            for k, value in totals.items()
        ),
        "collection totals differ from retained calls",
    )
    require(
        len({row["measured"] for row in task_rows}) <= 1,
        "collection mixes measured and shadow tasks",
    )
    measured_rows = [row for row in task_rows if row["measured"]]
    failed = [row for row in measured_rows if row["first_attempt_success"] is False]
    executed = [row for row in failed if row["first_failed_action_executed"] is True]
    rejected = [row for row in failed if row["first_failed_action_executed"] is False]

    def recovery(cohort):
        recovered = sum(row["recovered_after_first_failure"] for row in cohort)
        return {
            "recovered": recovered,
            "first_failure_tasks": len(cohort),
            "rate": recovered / len(cohort) if cohort else None,
            "tasks_with_retry": sum(row["attempts"] > 1 for row in cohort),
        }

    return {
        "schema": "hepta.current-policy-recovery-readout.v1",
        "collection_digest": data.digest(collection),
        "model_digest": expected_model_digest,
        "records_digest": data.digest(records),
        "maximum_attempts": maximum,
        "declared_tasks": len(records),
        "observed_tasks": len(task_rows),
        "measured_tasks": len(measured_rows),
        "unmeasured_tasks": len(task_rows) - len(measured_rows),
        "first_attempt_successes": sum(
            row["first_attempt_success"] for row in measured_rows
        )
        if measured_rows
        else None,
        "final_successes": sum(row["final_success"] for row in measured_rows)
        if measured_rows
        else None,
        "all_first_failures": recovery(failed),
        "executed_first_failures": recovery(executed),
        "unexecuted_first_failures": recovery(rejected),
        "actual_call_cost": totals,
        "task_outcomes": task_rows,
        "new_independent_tasks": 0,
        "source_authentication_established": False,
        "independent_confirmation_qualified": False,
        "scope": "retained current-policy observations; no new tasks or execution",
        "full_system_cost_complete": False,
    }
