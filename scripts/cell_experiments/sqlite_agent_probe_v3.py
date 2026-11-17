"""Bounded, gold-free action collection against the actual SQLite destination.

The caller owns predictor loading and closing. No model library is imported here.
All tasks are exposed development instances of one controlled environment family.
"""

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import time

from . import data
from .repo_tasks_v3_sqlite import ACTIONS, FIXTURES, SOURCE_SHA256, DevelopmentSession


PROTOCOL = "hepta.sqlite-agent-probe.v3"
MAX_HISTORY_ANSWER_BYTES = 8192
ACTION_CONTRACT = (
    "Choose exactly one primitive action per turn. Return only one JSON string: "
    '"inspect", "stage", "apply", or "stop". No object, array, Markdown, or prose. '
    "The same SQLite state persists across turns. inspect reads actual progress, "
    "the next unsatisfied row, and whether its prescribed payload is staged. "
    "stage stages that row's prescribed payload. apply attempts that staged write; "
    "an apply without the needed stage has no effect. Repeated apply is idempotent. "
    "stage/apply use the last visible row, or row zero when no view is available. "
    "A lost reply can remove the view after a committed write. inspect refreshes "
    "the view. stop ends the task and claims completion only if the last actual "
    "readback reports complete. stop performs no implicit inspect or repair. "
    "This is action planning only: the destination supplies payload values; you "
    "do not generate SQL or payloads. This exposed development task is not new C, "
    "a new independent source, an external user, or native Cell adoption."
)


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(data.canonical(value) + b"\n")


def parse_action(answer):
    """Admit the complete raw JSON string; never extract or repair an action."""
    if not isinstance(answer, str):
        return None, "answer_is_not_text"
    try:
        action = json.loads(answer)
    except (ValueError, TypeError):
        return None, "invalid_json"
    if not isinstance(action, str) or action not in ACTIONS:
        return None, "expected_one_allowed_json_string"
    return action, None


def call_cost(output, wall, cpu, returned):
    measured = {
        "predictor_returned": returned,
        "predict_call_wall_seconds": wall,
        "predict_call_cpu_seconds": cpu,
        "cpu_scope": "probe process only; remote/service/GPU CPU excluded",
    }
    for key in ("input_tokens", "output_tokens"):
        value = output.get(key) if isinstance(output, dict) else None
        measured[key] = value if type(value) is int and value >= 0 else None
    reported = None
    if isinstance(output, dict):
        reported = output.get("wall_seconds", output.get("elapsed_seconds"))
    measured["predictor_reported_wall_seconds"] = (
        reported
        if type(reported) in (int, float) and math.isfinite(reported) and reported >= 0
        else None
    )
    measured["provider_charge_receipt"] = (
        {
            key: output[key]
            for key in ("usage", "cost", "billed_cost", "currency")
            if key in output
        }
        if isinstance(output, dict)
        else {}
    )
    measured["monetary_cost_verified"] = False
    return measured


def run_task(
    predictor, task_id, directory, *, actor_kind, maximum=12, fixtures=FIXTURES
):
    """Run one persistent destination, preserving every prediction and rejection.

    predict(request) follows causal_probe_v3.Predictor: request contains record_id
    and task.input/task.messages. Returns must name the predictor's model_digest.
    actor_kind is explicitly model or scripted; scripted calls are never model runs.
    """
    if type(maximum) is not int or not 1 <= maximum <= 12:
        raise ValueError("maximum must be between one and twelve decisions")
    if actor_kind not in ("model", "scripted"):
        raise ValueError("explicit actor_kind model or scripted required")
    model_digest = predictor.model_digest
    if not isinstance(model_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", model_digest
    ):
        raise ValueError("predictor must expose its SHA-256 model digest")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    session = DevelopmentSession(task_id, directory / "destination", fixtures)
    started_at, started, cpu = time.time_ns(), time.perf_counter(), time.process_time()
    prompt = (
        session.spec["purpose"]
        + "\n"
        + ACTION_CONTRACT
        + f"\nThere are {len(session.task['goals'])} prescribed rows. "
        + f"You have at most {maximum} model decisions, including invalid outputs."
    )
    initial = {"observation": session.observation(), "remaining_decisions": maximum}
    messages = [
        {"role": "user", "content": prompt},
        {"role": "tool", "content": data.canonical(initial).decode()},
    ]
    metadata = {
        "schema": PROTOCOL,
        "task_id": task_id,
        "split": "development",
        "model_digest": model_digest,
        "actor_kind": actor_kind,
        "actor_identity_basis": "caller-declared predictor kind and loaded digest",
        "lineage_id": session.spec["lineage_id"],
        "source_group_id": session.spec["source_group_id"],
        "maximum_decisions": maximum,
        "started_at_ns": started_at,
        "input_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "initial_messages_sha256": data.digest(messages),
        "task_spec_sha256": data.digest(session.spec),
        "destination_source_sha256": SOURCE_SHA256,
        "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "independent_sample_increment": 0,
        "new_C": False,
        "gold_substitution": False,
        "payloads_supplied_by_destination": True,
        "external_evaluator_authenticated": False,
    }
    write_new(directory / "STARTED.json", metadata)
    steps, errors = [], []
    terminal_reason, binding_valid = "decision_budget_exhausted", True
    try:
        for number in range(maximum):
            request = {
                "record_id": task_id,
                "task": {"input": prompt, "messages": copy.deepcopy(messages)},
            }
            request_hash = data.digest(request)
            write_new(directory / f"request-{number}.json", request)
            call_started = time.time_ns()
            write_new(
                directory / f"call-started-{number}.json",
                {
                    "request_sha256": request_hash,
                    "messages_sha256": data.digest(messages),
                    "model_digest": model_digest,
                    "started_at_ns": call_started,
                },
            )
            before = session.observation()
            call_wall, call_cpu = time.perf_counter(), time.process_time()
            returned, predictor_error = False, None
            try:
                output = predictor.predict(copy.deepcopy(request))
                returned = True
            except Exception as error:
                predictor_error = type(error).__name__
                output = {"predictor_error": predictor_error, "message": str(error)}
            measurement = call_cost(
                output,
                time.perf_counter() - call_wall,
                time.process_time() - call_cpu,
                returned,
            )
            write_new(directory / f"output-{number}.json", output)
            answer = output.get("answer") if isinstance(output, dict) else None
            action, parse_error = parse_action(answer)
            contract_error = predictor_error
            if not contract_error and not isinstance(output, dict):
                contract_error = "predictor_return_is_not_an_object"
            if not contract_error and (
                output.get("loaded_model_digest") != model_digest
                or predictor.model_digest != model_digest
            ):
                contract_error, binding_valid = "loaded_model_digest_mismatch", False
            if (
                not contract_error
                and output.get("input_sha256", metadata["input_sha256"])
                != metadata["input_sha256"]
            ):
                contract_error, binding_valid = "input_digest_mismatch", False
            if not contract_error and output.get(
                "messages_sha256", data.digest(messages)
            ) != data.digest(messages):
                contract_error, binding_valid = "message_digest_mismatch", False
            if not contract_error and not isinstance(answer, str):
                contract_error = "predictor_answer_is_not_text"
            oversized = (
                isinstance(answer, str)
                and len(answer.encode()) > MAX_HISTORY_ANSWER_BYTES
            )
            if not contract_error and oversized:
                contract_error = "raw_answer_exceeds_frozen_history_bound"
            if contract_error or parse_error:
                sqlite_receipt = {
                    "action_receipt": None,
                    "before": before,
                    "after": session.observation(),
                    "execution_performed": False,
                    "reason": contract_error or parse_error,
                    "execution_summary": {
                        "primitive_calls_delta": 0,
                        "write_transactions_delta": 0,
                        "applied_effects_delta": 0,
                        "repository_patch_verifier": False,
                        "subprocess_started": False,
                        "same_process_sqlite": True,
                    },
                }
                errors.append(
                    {
                        "decision": number,
                        "kind": "predictor_contract_error"
                        if contract_error
                        else "format_error",
                    }
                )
            else:
                transition = session.step(action)
                receipt = transition["action_receipt"]
                sqlite_receipt = {
                    "action_receipt": receipt,
                    "before": before,
                    "after": transition["observation"],
                    "execution_performed": receipt["execution_summary"][
                        "primitive_calls_delta"
                    ]
                    > 0,
                    "execution_summary": receipt["execution_summary"],
                }
                view = before["visible_readback"]
                # Only a directly preceding actual readback establishes that
                # this row is unstaged. A stale view after stage/apply does not.
                if (
                    action == "apply"
                    and before["last_action"] == "inspect"
                    and view
                    and not view["complete"]
                    and not view["staged"]
                    and receipt["execution_summary"]["applied_effects_delta"] == 0
                ):
                    errors.append(
                        {"decision": number, "kind": "observed_unstaged_apply"}
                    )
                if transition["result"] is not None:
                    terminal_reason = transition["result"]["terminal_reason"]
            observation = {
                "observation": session.observation(),
                "remaining_decisions": maximum - number - 1,
                "format_error": parse_error,
                "predictor_contract_error": contract_error,
                "execution_summary": sqlite_receipt["execution_summary"],
                "instruction": "Return one allowed JSON string; no action was executed."
                if parse_error
                else "Choose the next action from actual readback.",
            }
            if session.closed:
                observation["terminal_business_result"] = {
                    "success": session.result["success"],
                    "complete": session.result["business_result"]["complete"],
                    "duplicate_effects": session.result["business_result"][
                        "duplicate_effects"
                    ],
                }
            feedback = data.canonical(observation).decode()
            step = {
                "decision": number,
                "request_sha256": request_hash,
                "input_sha256": metadata["input_sha256"],
                "messages_sha256": data.digest(messages),
                "expected_model_digest": model_digest,
                "output": output,
                "output_sha256": data.digest(output),
                "parsed_action": action,
                "parse_error": parse_error,
                "predictor_contract_error": contract_error,
                "sqlite_receipt": sqlite_receipt,
                "feedback": feedback,
                "cost": measurement,
                "started_at_ns": call_started,
                "completed_at_ns": time.time_ns(),
                "previous_step_sha256": steps[-1]["receipt_sha256"] if steps else None,
            }
            step["receipt_sha256"] = data.digest(step)
            write_new(directory / f"step-{number}.json", step)
            steps.append(step)
            if isinstance(answer, str):
                messages.extend(
                    [
                        {"role": "assistant", "content": answer},
                        {"role": "tool", "content": feedback},
                    ]
                )
            if contract_error:
                terminal_reason = "predictor_contract_error"
                break
            if session.closed:
                break
        if not session.closed:
            session.finish(reason=terminal_reason)
    finally:
        if not session.closed:
            session.finish(reason="probe_exception")
    final = session.result
    cost = {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "predictor_calls_attempted": len(steps),
        "predictor_calls_returned": sum(s["cost"]["predictor_returned"] for s in steps),
        "model_calls_attempted": len(steps) if actor_kind == "model" else 0,
        "model_calls_returned": sum(s["cost"]["predictor_returned"] for s in steps)
        if actor_kind == "model"
        else 0,
        "scripted_predictor_calls": len(steps) if actor_kind == "scripted" else 0,
        "predict_call_wall_seconds": sum(
            s["cost"]["predict_call_wall_seconds"] for s in steps
        ),
        "sqlite_primitive_calls": final["business_result"]["primitive_calls"],
        "cpu_scope": "probe process only; excludes remote/service/GPU CPU",
        "time_scopes_are_nested_not_additive": True,
        "monetary_cost": None,
        "complete": False,
        "load_and_close_cost_included": False,
    }
    for key in ("input_tokens", "output_tokens"):
        values = [s["cost"][key] for s in steps]
        cost[key] = sum(values) if all(value is not None for value in values) else None
        cost["known_" + key] = sum(value for value in values if value is not None)
        cost[key + "_receipts_complete"] = all(value is not None for value in values)
    error_kinds = {item["kind"] for item in errors}
    result = {
        **metadata,
        "completed_at_ns": time.time_ns(),
        "terminal_reason": terminal_reason,
        "success": final["success"],
        "model_binding_valid": binding_valid,
        "decisions": len(steps),
        "steps": steps,
        "errors": errors,
        "recovery": {
            "format_error_then_success": bool(
                final["success"] and "format_error" in error_kinds
            ),
            "observed_unstaged_apply_then_success": bool(
                final["success"] and "observed_unstaged_apply" in error_kinds
            ),
            "actor_kind": actor_kind,
            "automatic_repair": False,
        },
        "sqlite_result": final,
        "final_messages_sha256": data.digest(messages),
        "cost": cost,
        "confirmation_qualified": False,
        "native_cell_adoption": False,
    }
    write_new(directory / "MESSAGES.json", messages)
    write_new(directory / "RESULT.json", result)
    return result


def run_panel(predictor, directory, *, actor_kind, maximum=12, fixtures=FIXTURES):
    """Collect the three declared development scenarios; caller retains predictor."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(
        (
            Path(fixtures) / "tasks/sqlite-dev-v3/task-development-sqlite.json"
        ).read_text()
    )
    model_digest = predictor.model_digest
    rows = []
    for task in manifest["tasks"]:
        if predictor.model_digest != model_digest:
            raise ValueError("panel predictor model digest changed")
        rows.append(
            run_task(
                predictor,
                task["task_id"],
                directory / task["task_id"],
                actor_kind=actor_kind,
                maximum=maximum,
                fixtures=fixtures,
            )
        )
    result = {
        "schema": "hepta.sqlite-agent-panel.v3",
        "actor_kind": actor_kind,
        "model_digest": model_digest,
        "tasks": len(rows),
        "successes": sum(r["success"] for r in rows),
        "rows": rows,
        "independent_sample_increment": 0,
        "new_C": False,
        "new_independent_sources": 0,
        "confirmation_qualified": False,
    }
    write_new(directory / "PANEL.json", result)
    return result
