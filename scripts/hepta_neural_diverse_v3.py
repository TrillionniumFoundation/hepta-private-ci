"""Closed diverse60 work records; no model, owner or qualification is executed."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

PROFILE = "canonical-positive-zero-binary-diverse60-observed-v3"
CONTEXT_KEY = "binary_diverse60_observed_execution"
SUFFIX = "binary-diverse60-observed-v3"
STUDY_SCHEMA = "hepta-neural-study-diverse-v3"
TRACE = "binary-diverse60-training-trace-v3.jsonl"
DATA_SHA256 = "d457f4b01cc6aaa445403e81b1fa9511e24f23e4254a6ef9ff9ec29abab693cf"
DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "codex-rs/hepta-infer-worker-host/fixtures/smollm-diverse60-training-v3.json"
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def identity(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def closed(value, fields):
    require(
        type(value) is dict and set(value) == set(fields.split()),
        "closed diverse record",
    )


def digest(value):
    require(
        type(value) is str and re.fullmatch("[0-9a-f]{64}", value), "diverse digest"
    )
    return value


def decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate diverse key")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=unique)


def training_data(path=DATA_PATH):
    from hepta_neural_evidence_v1 import open_regular

    with open_regular(path) as stream:
        raw = stream.read(1024 * 1024 + 1)
    require(
        0 < len(raw) <= 1024 * 1024 and hashlib.sha256(raw).hexdigest() == DATA_SHA256,
        "exact frozen diverse60 public payload",
    )
    data = decode(raw)
    closed(
        data,
        "schema origin generation_rule generation_exclusion_identity training_rows "
        "ordered_training_row_sha256 training_token_ids batches_per_pass update_schedule "
        "expected_input_tokens tokenizer flags",
    )
    require(
        canonical(data) + b"\n" == raw
        and data["schema"] == "llm-binary-diverse60-training-data-v3"
        and data["flags"]
        == {
            "model_qualification": False,
            "future_window": False,
            "complete_current_exposure_exclusion_claim": False,
        },
        "canonical public training namespace without freshness or qualification claim",
    )
    rows, tokens, schedule = (
        data["training_rows"],
        data["training_token_ids"],
        data["update_schedule"],
    )
    require(
        len(rows) == len(tokens) == 60
        and len({row["prompt_sha256"] for row in rows}) == 60
        and data["ordered_training_row_sha256"] == [identity(row) for row in rows]
        and len(schedule) == 30
        and schedule == data["batches_per_pass"] * 5
        and all(len(batch) == len(set(batch)) == 10 for batch in schedule)
        and Counter(i for batch in schedule for i in batch)
        == Counter({i: 5 for i in range(60)})
        and data["expected_input_tokens"]
        == 15600
        == sum(len(tokens[i]) for batch in schedule for i in batch),
        "fixed sixty rows, six ten-row batches, five passes and15600 tokens",
    )
    return data


def validate_context(context, data):
    closed(
        context,
        "profile plan_sha256 recipe observer model_plan training_data training_rows "
        "training_schedule distinct_source_rows row_exposures optimizer_steps physical_microbatch expected_input_tokens",
    )
    require(context["profile"] == PROFILE, "explicit diverse training profile")
    for key in (
        "plan_sha256",
        "recipe",
        "observer",
        "model_plan",
        "training_data",
        "training_rows",
        "training_schedule",
    ):
        digest(context[key])
    require(
        context["training_data"] == DATA_SHA256
        and context["training_rows"] == identity(data["ordered_training_row_sha256"])
        and context["training_schedule"] == identity(data["update_schedule"]),
        "exact data, source rows and scheduled exposures",
    )
    for key, expected in (
        ("distinct_source_rows", 60),
        ("row_exposures", 300),
        ("optimizer_steps", 30),
        ("physical_microbatch", 1),
        ("expected_input_tokens", 15600),
    ):
        require(
            type(context[key]) is int and context[key] == expected,
            "exact diverse work context",
        )


def validate_trace(records, raw, consumed, data, context):
    """Recompute every scalar exposure, binary CE and mean; never rerun a model."""
    validate_context(context, data)
    rows, tokens, schedule = (
        data["training_rows"],
        data["training_token_ids"],
        data["update_schedule"],
    )
    training, objective = raw["training"], raw["training"]["objective"]
    closed(
        training,
        "steps loss tokens supervised_tokens supported_profile_flops flop_scope objective",
    )
    closed(
        objective,
        "profile execution recipe source_sha256 optimizer_steps microsteps distinct_source_rows "
        "row_exposures answer_tokens eos_tokens actual_input_tokens trace same_work_as_legacy_ten_single_rows loss_scope",
    )
    digest(raw["input"])
    closed(objective["trace"], "path bytes sha256")
    digest(objective["trace"]["sha256"])
    require(
        type(objective["trace"]["bytes"]) is int
        and 0 < objective["trace"]["bytes"] <= 1024 * 1024,
        "bounded diverse trace declaration",
    )
    require(
        objective["profile"] == PROFILE
        and objective["execution"] == context
        and objective["recipe"] == context["recipe"]
        and objective["source_sha256"]
        == digest(raw["source"]["binary_diverse60_observed"])
        and raw["source"]["binary_diverse60_training_data"] == DATA_SHA256
        and objective["same_work_as_legacy_ten_single_rows"] is False
        and objective["loss_scope"]
        == "ten-row-mean-two-original-answer-token-CE-gradient-per-optimizer-step",
        "separate source-bound diverse objective",
    )
    for key, expected in (
        ("optimizer_steps", 30),
        ("microsteps", 300),
        ("distinct_source_rows", 60),
        ("row_exposures", 300),
        ("answer_tokens", 300),
        ("eos_tokens", 0),
        ("actual_input_tokens", 15600),
    ):
        require(
            type(objective[key]) is int and objective[key] == expected,
            "exact diverse objective counts",
        )
    require(type(records) is list and len(records) == 332, "complete332 diverse trace")
    first = records[0]
    closed(
        first,
        "event profile input recipe plan_sha256 source source_rows training_data_sha256 "
        "update_schedule_sha256 pid start_monotonic_ns",
    )
    require(
        first["event"] == "start"
        and first["profile"] == PROFILE
        and first["input"] == raw["input"]
        and first["recipe"] == context["recipe"]
        and first["plan_sha256"] == context["plan_sha256"]
        and first["source"] == objective["source_sha256"]
        and first["source_rows"] == data["ordered_training_row_sha256"]
        and first["training_data_sha256"] == DATA_SHA256
        and first["update_schedule_sha256"] == context["training_schedule"]
        and type(first["pid"]) is int
        and first["pid"] > 0
        and type(first["start_monotonic_ns"]) is int
        and first["start_monotonic_ns"] > 0,
        "complete diverse start context",
    )
    position, total, previous_clock, previous_cpu = 1, 0, first["start_monotonic_ns"], 0
    means, steps = [], []
    for update, batch in enumerate(schedule):
        losses = []
        for ordinal, source_index in enumerate(batch):
            row = records[position]
            position += 1
            closed(
                row,
                "event optimizer_step row_ordinal source_row_index source_row_sha256 input_ids answer_token_ids "
                "target_index answer_logits loss backward_completed completed_monotonic_ns completed_process_cpu_ns",
            )
            require(
                row["event"] == "microstep"
                and type(row["optimizer_step"]) is int
                and row["optimizer_step"] == update
                and type(row["row_ordinal"]) is int
                and row["row_ordinal"] == ordinal
                and type(row["source_row_index"]) is int
                and row["source_row_index"] == source_index
                and row["source_row_sha256"]
                == data["ordered_training_row_sha256"][source_index]
                and canonical(row["input_ids"]) == canonical(tokens[source_index])
                and canonical(row["answer_token_ids"]) == b"[10407,4607]"
                and type(row["target_index"]) is int
                and row["target_index"]
                == ("yes", "no").index(rows[source_index]["expected_output"])
                and row["backward_completed"] is True,
                "exact scheduled scalar row, original tokens and label",
            )
            require(
                type(row["answer_logits"]) is list
                and len(row["answer_logits"]) == 2
                and all(
                    type(value) is str and math.isfinite(float(value))
                    for value in row["answer_logits"]
                )
                and type(row["loss"]) is str
                and math.isfinite(float(row["loss"]))
                and float(row["loss"]) >= 0,
                "finite binary logits and CE",
            )
            scores = [float(value) for value in row["answer_logits"]]
            difference = scores[1 - row["target_index"]] - scores[row["target_index"]]
            expected_loss = max(difference, 0) + math.log1p(math.exp(-abs(difference)))
            require(
                math.isfinite(expected_loss)
                and abs(float(row["loss"]) - expected_loss)
                <= 0.00001 * max(1, expected_loss),
                "original binary CE tolerance",
            )
            require(
                type(row["completed_monotonic_ns"]) is int
                and row["completed_monotonic_ns"] >= previous_clock
                and type(row["completed_process_cpu_ns"]) is int
                and row["completed_process_cpu_ns"] >= previous_cpu,
                "ordered scalar wall and CPU observations",
            )
            previous_clock, previous_cpu = (
                row["completed_monotonic_ns"],
                row["completed_process_cpu_ns"],
            )
            losses.append(float(row["loss"]))
            total += len(tokens[source_index])
            steps.append(
                dict(
                    optimizer_step=update,
                    row_ordinal=ordinal,
                    source_row_index=source_index,
                    source_row_sha256=data["ordered_training_row_sha256"][source_index],
                    input_ids=tokens[source_index],
                    supervised_tokens=1,
                )
            )
        row = records[position]
        position += 1
        closed(
            row,
            "event optimizer_step microsteps gradient_l2_squared optimizer_completed completed_monotonic_ns completed_process_cpu_ns",
        )
        require(
            row["event"] == "optimizer-step"
            and type(row["optimizer_step"]) is int
            and row["optimizer_step"] == update
            and type(row["microsteps"]) is int
            and row["microsteps"] == 10
            and row["optimizer_completed"] is True
            and type(row["gradient_l2_squared"]) is str
            and math.isfinite(float(row["gradient_l2_squared"]))
            and float(row["gradient_l2_squared"]) > 0
            and type(row["completed_monotonic_ns"]) is int
            and row["completed_monotonic_ns"] >= previous_clock
            and type(row["completed_process_cpu_ns"]) is int
            and row["completed_process_cpu_ns"] >= previous_cpu,
            "actual mean-gradient update and ordered observations",
        )
        previous_clock, previous_cpu = (
            row["completed_monotonic_ns"],
            row["completed_process_cpu_ns"],
        )
        means.append(format(math.fsum(losses) / 10, ".17g"))
    last = records[position]
    closed(
        last,
        "event optimizer_steps microsteps tokens supervised_tokens completed_monotonic_ns",
    )
    require(
        last["event"] == "complete"
        and all(
            type(last[key]) is int and last[key] == expected
            for key, expected in (
                ("optimizer_steps", 30),
                ("microsteps", 300),
                ("tokens", 15600),
                ("supervised_tokens", 300),
            )
        )
        and type(last["completed_monotonic_ns"]) is int
        and last["completed_monotonic_ns"] >= previous_clock,
        "complete final diverse counts",
    )
    require(
        type(training["steps"]) is int
        and training["steps"] == 30
        and training["loss"] == means
        and type(training["tokens"]) is int
        and training["tokens"] == total == 15600
        and type(training["supervised_tokens"]) is int
        and training["supervised_tokens"] == 300
        and type(training["supported_profile_flops"]) is int
        and training["supported_profile_flops"] >= 0
        and training["flop_scope"]
        == "profiler-supported-operators-only-not-total-work",
        "recomputed means and exact scalar work totals",
    )
    if consumed is not None:
        require(
            canonical(consumed["steps"]) == canonical(steps),
            "independent actual consumption matches every scheduled exposure",
        )
    return dict(
        optimizer_updates=30,
        gradient_microsteps=300,
        distinct_source_rows=60,
        input_tokens=15600,
        answer_supervised_tokens=300,
        eos_supervised_tokens=0,
    )
