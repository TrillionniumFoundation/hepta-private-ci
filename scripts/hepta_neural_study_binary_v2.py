#!/usr/bin/env python3
"""Separate binary-answer training and unchanged original forward/Cell owners.

This helper emits unsigned execution evidence. Product qualification and ordinary
installation remain owned by the original Rust runner and selector.
"""

import argparse
import ctypes
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_neural_study_v1 as original

require, canonical, sha = original.require, original.canonical, original.sha
pin, read_pin, save = original.pin, original.read_pin, original.save
checkout, runtime_snapshot = original.checkout, original.runtime_snapshot
checked_training_data = original.checked_training_data
RUNTIME = original.RUNTIME
SCHEMA = "hepta-neural-study-binary-v2"
TRAINING_TREE = "1ba8d5460f77aa2e00f7bf1b5e400626b555e158"
EXCLUSION_SHA = "d2101f954f9b025d5fe0a87b73ae2d31f20eb6f989ed279a04ffe38d0932b06d"


def checkout_training_tree(path):
    require(path.is_absolute(), "absolute binary training source")
    observed = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD", "HEAD^{tree}"], text=True
    ).splitlines()
    require(
        len(observed) == 2
        and re.fullmatch("[0-9a-f]{40}", observed[0])
        and observed[1] == TRAINING_TREE,
        "exact frozen binary training tree",
    )
    checkout(path, observed[0])
    return observed[0]


def consumption_receipt(runtime, value, plan, consumed, trained, training_pin, output):
    """Independently tokenize the actual trace; ten rows remain ten examples."""
    from transformers import AutoTokenizer

    trace_pin = trained["training"]["objective"]["trace"]
    trace_path = output / "training/execution/binary-training-trace-v2.jsonl"
    require(
        set(trace_pin) == {"path", "sha256", "bytes"}
        and trace_path == Path(trace_pin["path"])
        and trace_path.is_file()
        and not trace_path.is_symlink()
        and 0 < trace_path.stat().st_size <= 1024 * 1024,
        "bounded actual binary trace",
    )
    raw = trace_path.read_bytes()
    require(
        len(raw) == trace_pin["bytes"] and sha(raw) == trace_pin["sha256"],
        "actual binary trace pin",
    )
    records = [json.loads(line) for line in raw.splitlines()]
    micros = [record for record in records if record["event"] == "microstep"]
    require(
        len(records) == 112 and len(micros) == 100 and len(consumed) == 10,
        "complete binary workload trace",
    )
    tokenizer = AutoTokenizer.from_pretrained(
        value["materials"],
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    tokenizer.padding_side = "left"
    require(
        tokenizer.bos_token_id == 1
        and tokenizer.eos_token_id == tokenizer.pad_token_id == 2
        and len(tokenizer) == 49152,
        "original tokenizer",
    )
    answers = [
        tokenizer.encode(answer, add_special_tokens=False) for answer in ("yes", "no")
    ]
    require(
        answers == [[10407], [4607]], "two original nonspecial single-token actions"
    )
    prompts = [
        runtime.prompt_tokens(tokenizer, row, plan["input_tokens_max"])
        for row in consumed
    ]
    steps = []
    for index, micro in enumerate(micros):
        ordinal, update = index % 10, index // 10
        row, prompt = consumed[ordinal], prompts[ordinal]
        require(
            micro["optimizer_step"] == update
            and micro["row_ordinal"] == ordinal
            and micro["source_row_sha256"] == sha(canonical(row))
            and micro["input_ids"] == prompt
            and 0 < len(prompt) <= plan["input_tokens_max"]
            and micro["answer_token_ids"] == [10407, 4607]
            and micro["target_index"] == ("yes", "no").index(row["expected_output"])
            and micro["backward_completed"] is True,
            "actual trace independently matches original source and prompt tokens",
        )
        steps.append(
            dict(
                optimizer_step=update,
                row_ordinal=ordinal,
                source_row_sha256=sha(canonical(row)),
                input_ids=prompt,
                supervised_tokens=1,
            )
        )
    require(
        trained["experiment"] == runtime.identity(plan)
        and trained["source"]["runtime"] == runtime.file_sha(runtime.__file__)
        and trained["training"]["steps"] == 10
        and trained["training"]["tokens"] == sum(len(row["input_ids"]) for row in steps)
        and trained["training"]["supervised_tokens"] == 100,
        "actual binary exposure totals, not legacy 526/40",
    )
    return save(
        output / "training-consumption.json",
        dict(
            schema="hepta-neural-binary-training-consumption-v2",
            training_data=value["training_data"],
            actual_receipt=training_pin,
            actual_trace=trace_pin,
            original_runtime_source_sha256=runtime.file_sha(runtime.__file__),
            experiment=runtime.identity(plan),
            optimizer_steps=10,
            independent_source_rows=10,
            actual_row_exposures=100,
            steps=steps,
            evidence_scope="fixed-child actual unsigned trace independently retokenized; no independent execution proof or qualification",
        ),
    )


def train(value, input_pin):
    require(
        set(value)
        == {
            "schema",
            "operation",
            "training_chain",
            "runtime_chain",
            "materials",
            "parent",
            "ordinary",
            "study",
            "training_data",
            "output",
        },
        "closed training request",
    )
    training_chain, runtime_chain = (
        Path(value["training_chain"]),
        Path(value["runtime_chain"]),
    )
    training_commit = checkout_training_tree(training_chain)
    checkout(runtime_chain, RUNTIME)
    runtime_snapshot()
    sys.path.insert(0, str(training_chain / "scripts"))
    sys.path.insert(0, str(Path(__file__).parent))
    runtime = importlib.import_module("llm_runtime_pilot")
    inherited = importlib.import_module("llm_inherited_runtime")
    parent_step = importlib.import_module("llm_runtime_parent_step_v2")
    binary = importlib.import_module("llm_binary_answer_observed_v2")
    setup = importlib.import_module("llm_initial_trainable_setup_v2")
    parent = inherited.validate_parent(read_pin(value["parent"]))
    inherited.read_parent(parent)
    ordinary, study = read_pin(value["ordinary"]), read_pin(value["study"])
    actual = ordinary["parent"]
    require(
        parent["generation"] == 1
        and ordinary["ordinary_context_reads"] == 1
        and actual["generation"] == 1
        and actual["parameter_sha256"] == parent["file_sha256"]
        and actual["adapter"] == parent["adapter"]
        and actual["contract"] == parent["contract"],
        "the actual ordinary installed generation-one parent is the training input",
    )
    require(
        study["schema"] == SCHEMA + "-preregistered"
        and study["model_training_steps"] == study["optimizer_steps"] == 10
        and study["actual_row_exposures"] == 100
        and study["independent_source_rows"] == 10
        and study["previous_consumed_prompt_exclusion_sha256"] == EXCLUSION_SHA
        and study["future_windows"] == 2
        and study["tasks_per_window"] == 512
        and study["minimum_window_micros"] == 1000000
        and study["parent_file_sha256"] == parent["file_sha256"],
        "predeclared study",
    )
    output = Path(value["output"])
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    plan_raw = (
        Path(__file__).resolve().parents[1]
        / "codex-rs/hepta-learning-artifacts/profiles/"
        "smollm2-public-initial-v2.plan.json"
    ).read_bytes()
    plan = runtime.validate_plan(json.loads(plan_raw))
    manifest, _ = runtime.verify_materials(Path(value["materials"]))
    require(
        plan == runtime.experiment_plan(manifest),
        "unmodified original ten-step model plan",
    )
    training_data = read_pin(value["training_data"])
    consumed = checked_training_data(training_data, plan, plan_raw)
    require(
        training_data["frozen_unix_micros"] < time.time_ns() // 1000,
        "actual training source is frozen before the training task",
    )
    plan_path = output / "model-plan.json"
    plan_path.write_bytes(plan_raw)
    execution_value = dict(
        files=dict(plan=str(plan_path)),
        parent={key: parent[key] for key in ("contract", "adapter", "file_sha256")},
        initial_setup=dict(
            recipe=dict(setup.RECIPE), parent_material=dict(value["parent"])
        ),
    )
    execution_plan = output / "binary-execution-plan-v2.json"
    runtime.save(execution_plan, binary.plan_record(execution_value))
    execution_value["initial_setup"]["binary_plan"] = dict(
        path=str(execution_plan), sha256=runtime.file_sha(execution_plan)
    )
    context = binary.context(execution_value)
    directory = Path(parent["directory"])
    attempt = sha(
        canonical(
            {
                "schema": SCHEMA + "-actual-parent-attempt",
                "input": input_pin,
                "study": value["study"],
                "ordinary": value["ordinary"],
            }
        )
    )
    parent_step.run(
        SimpleNamespace(
            operation="train",
            initial_setup_profile=binary.PROFILE,
            parent_material=value["parent"]["path"],
            parent_material_sha256=value["parent"]["sha256"],
            materials=value["materials"],
            plan=str(plan_path),
            output=str(output / "training"),
            attempt_id=attempt,
            expected_plan=runtime.identity(plan),
            parent_contract=str(directory / "target-contract.json"),
            parent_adapter=str(directory / "wrapped-adapter.json"),
            parent_artifact=str(directory / "artifact.safetensors"),
            expected_contract=parent["contract"],
            expected_parent_adapter=parent["adapter"],
            expected_parent_file_sha256=parent["file_sha256"],
            candidate_directory=None,
            expected_candidate_adapter=None,
            expected_candidate_file_sha256=None,
            expected_candidate_record_sha256=None,
            expected_candidate_result_sha256=None,
            research_plan=None,
            research_plan_sha256=None,
            observation_plan=None,
            observation_plan_sha256=None,
            binary_plan=str(execution_plan),
            binary_plan_sha256=runtime.file_sha(execution_plan),
        )
    )
    completion_pin = pin(output / "training/parent-step-result-binary-observed-v2.json")
    completion = read_pin(completion_pin)
    training_pin = pin(output / "training/execution/actual-receipt.json")
    trained = read_pin(training_pin)
    require(
        completion["outcome"] == "success"
        and completion["completion_verified"] is True
        and completion["actual_receipt_sha256"] == training_pin["sha256"]
        and trained["parent_readback"] == parent["adapter"]
        and trained["training"]["steps"] == 10
        and trained["training_changed_from_setup"] is True
        and trained["binary_observed_execution"]
        == completion["binary_observed_execution"]
        == context,
        "complete actual parent training including original terminal budget",
    )
    require(
        read_pin(value["training_data"]) == training_data
        and checked_training_data(training_data, plan, plan_path.read_bytes())
        == consumed,
        "training sources remain exactly the admitted dataset",
    )
    consumption = consumption_receipt(
        runtime, value, plan, consumed, trained, training_pin, output
    )
    child_directory = output / "candidate"
    child_directory.mkdir(mode=0o700)
    for name in (
        "artifact.safetensors",
        "target-contract.json",
        "wrapped-adapter.json",
    ):
        source = output / "training/execution" / name
        require(
            source.is_file() and not source.is_symlink(),
            "complete actual trained child material",
        )
        shutil.copyfile(source, child_directory / name)
    child = {
        "schema": inherited.PARENT_SCHEMA,
        "generation": 2,
        "operation_id": attempt,
        "directory": str(child_directory),
        "contract": parent["contract"],
        **trained["candidate"],
    }
    inherited.read_parent(child)
    child_pin = save(output / "candidate-parent.json", child)
    runtime_snapshot()
    save(
        output / "training-result.json",
        {
            "schema": SCHEMA + "-training-result",
            "input": input_pin,
            "study": value["study"],
            "ordinary": value["ordinary"],
            "parent": value["parent"],
            "child": child_pin,
            "training": training_pin,
            "completion": completion_pin,
            "training_data": value["training_data"],
            "training_consumption": consumption,
            "source_dataset_digest": training_data["source_dataset_digest"],
            "binary_observed_execution": context,
            "training_chain": training_commit,
            "training_tree": TRAINING_TREE,
            "runtime_chain": RUNTIME,
            "installation_authority": False,
        },
    )


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-sha256", required=True)
    args = parser.parse_args()
    request = {"path": str(Path(args.input).resolve()), "sha256": args.input_sha256}
    value = read_pin(request)
    require(
        (value["schema"], value["operation"])
        in (
            (SCHEMA, "train"),
            (original.SCHEMA, "forward"),
            (original.SCHEMA, "transport"),
        ),
        "explicit binary training or original forward/transport namespace",
    )
    owner = value.pop("host_parent_pid")
    require(
        type(owner) is int and owner > 1 and os.getppid() == owner,
        "original Rust parent lost",
    )
    libc = ctypes.CDLL(None, use_errno=True)
    require(
        libc.prctl(1, signal.SIGKILL, 0, 0, 0) == 0 and os.getppid() == owner,
        "original Rust parent death binding",
    )
    {"train": train, "forward": original.forward, "transport": original.transport}[
        value["operation"]
    ](value, request)
