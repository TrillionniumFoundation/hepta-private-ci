"""Use the unchanged authorized existing teacher, with pre-call full-context checks."""

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
connection = importlib.import_module("teacher_connection")


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(connection.canonical(value) + b"\n")
        stream.flush()


def wire_messages(messages):
    return [
        {
            "role": "user" if row["role"] == "tool" else row["role"],
            "content": ("Tool observation:\n" if row["role"] == "tool" else "")
            + row["content"],
        }
        for row in messages
    ]


def count_tokens(credential, content):
    raw = connection.request(
        "/tokenize",
        credential,
        {"content": content, "add_special": False, "parse_special": True},
    )
    tokens = raw.get("tokens")
    connection.require(
        isinstance(tokens, list) and all(isinstance(token, int) for token in tokens),
        "actual tokenizer integer IDs required",
    )
    return {
        "tokens": len(tokens),
        "token_ids_sha256": connection.digest(tokens),
        "raw": raw,
    }


def render(credential, messages):
    wire = wire_messages(messages)
    value = connection.request(
        "/apply-template",
        credential,
        {
            "messages": wire,
            "add_generation_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    prompt = value.get("prompt") if isinstance(value, dict) else None
    connection.require(isinstance(prompt, str), "native full chat rendering required")
    return wire, prompt, count_tokens(credential, prompt)


def identity(root):
    prior = read(root / "PREFLIGHT-2.json")
    connection.require(
        prior["status"] == "MATCHED_EXISTING_SERVICE",
        "matched existing service required",
    )
    server, credential = connection.existing_server()
    connection.require(
        server == prior["server"],
        "existing operator service changed after read-only preflight",
    )
    connection.require(
        connection.stat_identity(Path(connection.WEIGHT))
        == prior["weight_identity"]["file_identity"],
        "actual teacher weight bytes/identity changed",
    )
    return prior, server, credential


def prepare(root, commit):
    prior, server, credential = identity(root)
    tasks, protocol, oracles = [
        read(root / name)
        for name in ("TASKS.json", "PROTOCOL.json", "ORACLE_ACTIONS.json")
    ]
    connection.require(
        len(tasks) == len(oracles) == 4,
        "all four fixed A tasks and codec references required",
    )
    connection.require(
        connection.file_sha(root / "TASKS.json") == protocol["task_records_sha256"],
        "A tasks changed",
    )
    props = connection.request("/props", credential)
    models = connection.request("/v1/models", credential)
    connection.require(
        props["model_path"] == connection.WEIGHT
        and props["model_alias"] == connection.ALIAS,
        "teacher model differs",
    )
    slots = connection.idle(credential)
    native_context = min(int(row["n_ctx"]) for row in slots)
    connection.require(
        native_context >= 10240,
        "teacher cannot hold common 8192 input plus2048 output window",
    )
    checks = []
    for task, reference in zip(tasks, oracles):
        wire, rendered, tokens = render(credential, task["task"]["messages"])
        reference_tokens = count_tokens(credential, reference)
        connection.require(
            tokens["tokens"] <= 8192 and tokens["tokens"] + 2048 <= native_context,
            "complete initial teacher input plus output reserve exceeds native context",
        )
        connection.require(
            reference_tokens["tokens"] <= 2048,
            "common output codec cannot express an original repair",
        )
        checks.append(
            {
                "record_id": task["record_id"],
                "prompt_sha256": task["prompt_sha256"],
                "native_rendered_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
                "rendered_prompt": rendered,
                "input_tokenization": tokens,
                "reference_tokenization": reference_tokens,
                "wire_messages": wire,
            }
        )
    freeze = {
        "schema": "hepta.existing-teacher-upstream-freeze.v1",
        "source_commit": commit,
        "script_sha256": connection.file_sha(Path(__file__)),
        "connection_sha256": connection.file_sha(HERE / "teacher_connection.py"),
        "protocol_sha256": connection.file_sha(root / "PROTOCOL.json"),
        "tasks_sha256": connection.file_sha(root / "TASKS.json"),
        "server": server,
        "weight_identity": prior["weight_identity"],
        "native_context": native_context,
        "chat_template_sha256": hashlib.sha256(
            props["chat_template"].encode()
        ).hexdigest(),
        "model_ids": [row["id"] for row in models["data"]],
        "slots_before": slots,
        "checks": checks,
        "request_parameters": {
            "max_tokens": 2048,
            "temperature": 0.0,
            "top_p": 1.0,
            "top_k": 1,
            "min_p": 0.0,
            "seed": 1729,
            "n": 1,
            "stream": False,
            "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        "logical_information_and_two_call_caps_match_students": True,
        "physical_compute_matched": False,
        "internal_research_license_scope_only": True,
        "credentials_retained": False,
        "security_configuration_changed": False,
        "new_model_calls": 0,
        "planned_model_calls": 8,
        "created_at_ns": time.time_ns(),
    }
    write(root / "TEACHER_FREEZE.json", freeze)
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "teacher_freeze_sha256": connection.file_sha(
                    root / "TEACHER_FREEZE.json"
                ),
                "native_context": native_context,
                "input_tokens": [row["input_tokenization"]["tokens"] for row in checks],
                "reference_tokens": [
                    row["reference_tokenization"]["tokens"] for row in checks
                ],
                "model_calls": 0,
            }
        )
    )


def run(root, stage, commit):
    prior, server, credential = identity(root)
    freeze = read(root / "TEACHER_FREEZE.json")
    connection.require(
        server == freeze["server"]
        and connection.file_sha(Path(__file__)) == freeze["script_sha256"]
        and connection.file_sha(HERE / "teacher_connection.py")
        == freeze["connection_sha256"],
        "frozen service/code changed",
    )
    connection.require(
        connection.file_sha(root / "TASKS.json") == freeze["tasks_sha256"]
        and connection.file_sha(root / "PROTOCOL.json") == freeze["protocol_sha256"],
        "frozen task/protocol changed",
    )
    tasks = read(root / "TASKS.json")
    output = root / stage
    output.mkdir(exist_ok=False)
    started, completed, sent = time.perf_counter(), 0, 0
    try:
        for index, task in enumerate(tasks):
            connection.require(
                connection.existing_server()[0] == freeze["server"], "service changed"
            )
            connection.require(
                connection.stat_identity(Path(connection.WEIGHT))
                == freeze["weight_identity"]["file_identity"],
                "weight changed",
            )
            slots = connection.idle(credential)
            connection.require(
                min(int(row["n_ctx"]) for row in slots) == freeze["native_context"],
                "slot context changed",
            )
            messages = task["task"]["messages"]
            if stage == "second":
                previous = read(root / "first" / ("OUTPUT-" + str(index) + ".json"))
                item = read(root / "FIRST_VERIFICATIONS.json")[index]
                connection.require(
                    item["project_id"] == task["project_id"]
                    and item["verification"]["answer_sha256"]
                    == hashlib.sha256(previous["answer"].encode()).hexdigest(),
                    "feedback does not bind the actual first teacher answer",
                )
                connection.require(
                    item["verification_digest"]
                    == connection.digest(item["verification"]),
                    "receipt binding differs",
                )
                connection.require(
                    item["feedback_digest"]
                    == hashlib.sha256(item["feedback"].encode()).hexdigest(),
                    "feedback differs",
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": previous["answer"]},
                    {"role": "tool", "content": item["feedback"]},
                ]
            wire, rendered, tokens = render(credential, messages)
            connection.require(
                tokens["tokens"] <= 8192
                and tokens["tokens"] + 2048 <= freeze["native_context"],
                "full second-turn context plus output reserve exceeds native window; no truncation",
            )
            payload = {
                "model": connection.ALIAS,
                "messages": wire,
                **freeze["request_parameters"],
            }
            write(
                output / ("REQUEST-" + str(index) + ".json"),
                {
                    "record_id": task["record_id"],
                    "logical_messages": messages,
                    "payload": payload,
                    "slots_before": slots,
                    "native_rendered_prompt": rendered,
                    "input_tokenization": tokens,
                    "native_context": freeze["native_context"],
                    "output_reserve": 2048,
                },
            )
            write(
                output / ("GENERATION_STARTED-" + str(index) + ".json"),
                {
                    "at_ns": time.time_ns(),
                    "request_digest": connection.digest(payload),
                    "unknown_request_not_replayed": True,
                },
            )
            tick = time.perf_counter()
            sent += 1
            raw = connection.request("/v1/chat/completions", credential, payload)
            elapsed = time.perf_counter() - tick
            write(
                output / ("RAW_RESPONSE-" + str(index) + ".json"),
                {
                    "raw_response": raw,
                    "wall_seconds": elapsed,
                    "request_digest": connection.digest(payload),
                },
            )
            connection.require(
                len(raw.get("choices", [])) == 1, "one real teacher output required"
            )
            answer = raw["choices"][0]["message"].get("content")
            connection.require(
                answer is None or isinstance(answer, str),
                "raw teacher content type differs",
            )
            receipt = {
                "record_id": task["record_id"],
                "project_id": task["project_id"],
                "answer": answer or "",
                "raw_response": raw,
                "wall_seconds": elapsed,
                "usage": raw.get("usage"),
                "predicted_input_tokens_from_native_template": tokens["tokens"],
                "input_truncated": False,
                "freeze_sha256": connection.file_sha(root / "TEACHER_FREEZE.json"),
                "request_digest": connection.digest(payload),
                "logical_messages_digest": connection.digest(messages),
            }
            write(output / ("OUTPUT-" + str(index) + ".json"), receipt)
            usage = raw.get("usage", {})
            connection.require(
                isinstance(usage.get("prompt_tokens"), int)
                and usage["prompt_tokens"] + 2048 <= freeze["native_context"],
                "actual complete input exceeds context",
            )
            connection.require(
                abs(usage["prompt_tokens"] - tokens["tokens"]) <= 1,
                "actual input differs from complete native tokenization beyond optional BOS; preserve output and stop",
            )
            connection.require(
                connection.existing_server()[0] == freeze["server"],
                "service changed during actual call",
            )
            write(
                output / ("POSTFLIGHT-" + str(index) + ".json"),
                {
                    "slots": connection.idle(credential),
                    "actual_prompt_tokens": usage["prompt_tokens"],
                    "native_tokenizer_delta": usage["prompt_tokens"] - tokens["tokens"],
                },
            )
            completed += 1
        write(
            root / (stage.upper() + "_COMPLETE.json"),
            {
                "actual_model_requests": sent,
                "completed_outputs": completed,
                "wall_seconds": time.perf_counter() - started,
                "source_commit": commit,
                "new_training_updates": 0,
                "full_system_cost_known": False,
            },
        )
        print(
            json.dumps(
                {
                    "stage": stage,
                    "actual_model_calls": sent,
                    "completed_outputs": completed,
                }
            )
        )
    except BaseException as error:
        write(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "requests_sent": sent,
                "completed_outputs": completed,
                "raw_responses_received": len(list(output.glob("RAW_RESPONSE-*.json"))),
                "wall_seconds": time.perf_counter() - started,
                "unknown_generation_not_replayed": True,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "first", "second"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    prepare(args.root, args.source_commit) if args.stage == "prepare" else run(
        args.root, args.stage, args.source_commit
    )
