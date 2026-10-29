#!/usr/bin/env python3
"""Fixed diverse60 training with the original forward, Cell and owned budgets."""

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
import hepta_neural_diverse_v3 as work
import hepta_neural_study_v1 as original

require, canonical, sha = original.require, original.canonical, original.sha
pin, read_pin, save = original.pin, original.read_pin, original.save
SCHEMA = work.STUDY_SCHEMA
# Publishing supplies exact identities; an unpublished candidate cannot execute.
TRAINING_COMMIT = "0bd7019a06e34c69fcbc84f23dda8510689b9a8d"
TRAINING_TREE = "1f4c5a62483cb686627a9acb16c3626c7e68f1c8"
EXCLUSION_SHA = "946d33b8f3cd95949f8eaf3623948639cf68c58214ad8b8f191ae0c2088606e4"


def checkout_training_tree(path):
    require(
        path.is_absolute()
        and all(
            type(value) is str and re.fullmatch("[0-9a-f]{40}", value)
            for value in (TRAINING_COMMIT, TRAINING_TREE)
        ),
        "published exact diverse training source required",
    )
    observed = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD", "HEAD^{tree}"], text=True
    ).splitlines()
    require(
        observed == [TRAINING_COMMIT, TRAINING_TREE],
        "exact diverse training commit and tree",
    )
    original.checkout(path, TRAINING_COMMIT)
    return TRAINING_COMMIT


def checked_training_data(value, plan, plan_raw, data):
    work.closed(
        value,
        "schema model_plan offered_training_rows consumed_training_rows consumed_step_indices "
        "source_dataset_digest dataset_receipt ledger row_encoding record_semantics frozen_unix_micros",
    )
    require(
        value["schema"] == "hepta-neural-actual-training-data-diverse-v3",
        "distinct diverse dataset namespace",
    )
    rows = data["training_rows"]
    require(
        type(plan["training_steps"]) is int
        and plan["training_steps"] == 10
        and read_pin(value["model_plan"]) == plan
        and value["model_plan"]["sha256"] == sha(plan_raw)
        and len(rows) == 60
        and value["offered_training_rows"] == value["consumed_training_rows"] == rows
        and canonical(value["consumed_step_indices"]) == canonical(list(range(60))),
        "sixty explicit public rows with the unchanged original material plan",
    )
    snapshot = value["dataset_receipt"]["snapshot"]
    require(
        snapshot["dataset_digest"] == value["source_dataset_digest"]
        and len(snapshot["source_record_digests"]) == 120
        and type(snapshot["pending_outcomes"]) is int
        and snapshot["pending_outcomes"] == 0
        and type(snapshot["censored_outcomes"]) is int
        and snapshot["censored_outcomes"] == 0,
        "sixty authenticated decisions and sixty observed targets, with no extra outcomes",
    )
    ledger = Path(value["ledger"]["path"])
    require(
        ledger.is_file() and not ledger.is_symlink() and pin(ledger) == value["ledger"],
        "frozen actual training ledger bytes",
    )
    require(
        type(value["frozen_unix_micros"]) is int
        and 0 < value["frozen_unix_micros"] < time.time_ns() // 1000,
        "actual diverse training data frozen before execution",
    )
    return rows


def consumption_receipt(runtime, value, plan, data, trained, training_pin, output):
    from transformers import AutoTokenizer
    from hepta_neural_evidence_v1 import open_regular

    trace_pin = trained["training"]["objective"]["trace"]
    trace_path = output / "training/execution" / work.TRACE
    work.closed(trace_pin, "path sha256 bytes")
    require(
        Path(trace_pin["path"]) == trace_path
        and type(trace_pin["bytes"]) is int
        and 0 < trace_pin["bytes"] <= 1024 * 1024,
        "bounded actual diverse trace role",
    )
    with open_regular(trace_path) as stream:
        raw = stream.read(1024 * 1024 + 1)
    require(
        len(raw) == trace_pin["bytes"]
        and sha(raw) == trace_pin["sha256"]
        and raw.endswith(b"\n"),
        "complete actual diverse trace pin",
    )
    records = [work.decode(line) for line in raw.splitlines()]
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
        and len(tokenizer) == 49152
        and [
            tokenizer.encode(answer, add_special_tokens=False)
            for answer in ("yes", "no")
        ]
        == [[10407], [4607]],
        "original tokenizer and answer actions",
    )
    prompts = [
        runtime.prompt_tokens(tokenizer, row, plan["input_tokens_max"])
        for row in data["training_rows"]
    ]
    require(
        prompts == data["training_token_ids"],
        "independently retokenized all sixty frozen public prompts",
    )
    steps = [
        dict(
            optimizer_step=update,
            row_ordinal=ordinal,
            source_row_index=index,
            source_row_sha256=data["ordered_training_row_sha256"][index],
            input_ids=prompts[index],
            supervised_tokens=1,
        )
        for update, batch in enumerate(data["update_schedule"])
        for ordinal, index in enumerate(batch)
    ]
    consumed = dict(
        schema="hepta-neural-diverse-training-consumption-v3",
        training_data=value["training_data"],
        actual_receipt=training_pin,
        actual_trace=trace_pin,
        original_runtime_source_sha256=runtime.file_sha(runtime.__file__),
        experiment=runtime.identity(plan),
        optimizer_steps=30,
        distinct_source_rows=60,
        actual_row_exposures=300,
        fixed_training_data_sha256=work.DATA_SHA256,
        update_schedule_sha256=work.identity(data["update_schedule"]),
        steps=steps,
        evidence_scope="fixed-child actual unsigned trace independently retokenized; no independent execution proof or qualification",
    )
    require(
        trained["experiment"] == runtime.identity(plan)
        and trained["source"]["runtime"] == runtime.file_sha(runtime.__file__),
        "actual original material/runtime binding",
    )
    work.validate_trace(records, trained, consumed, data, trained[work.CONTEXT_KEY])
    return save(output / "training-consumption.json", consumed)


def train(value, input_pin):
    work.closed(
        value,
        "schema operation training_chain runtime_chain materials parent ordinary study training_data output",
    )
    require(
        value["schema"] == SCHEMA and value["operation"] == "train",
        "explicit diverse training request",
    )
    training_chain, runtime_chain = (
        Path(value["training_chain"]),
        Path(value["runtime_chain"]),
    )
    training_commit = checkout_training_tree(training_chain)
    original.checkout(runtime_chain, original.RUNTIME)
    original.runtime_snapshot()
    sys.path.insert(0, str(training_chain / "scripts"))
    runtime = importlib.import_module("llm_runtime_pilot")
    inherited = importlib.import_module("llm_inherited_runtime")
    parent_step = importlib.import_module("llm_runtime_parent_step_v2")
    diverse = importlib.import_module("llm_binary_diverse60_observed_v3")
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
        "the actual ordinary installed parent is consumed",
    )
    require(
        type(EXCLUSION_SHA) is str and re.fullmatch("[0-9a-f]{64}", EXCLUSION_SHA),
        "frozen current exposure exclusion required",
    )
    require(
        study["schema"] == SCHEMA + "-preregistered"
        and study["model_training_steps"] == 10
        and study["optimizer_steps"] == 30
        and study["actual_row_exposures"] == 300
        and study["distinct_source_rows"] == 60
        and study["physical_microbatch"] == 1
        and study["expected_input_tokens"] == 15600
        and study["previous_consumed_prompt_exclusion_sha256"] == EXCLUSION_SHA
        and study["future_windows"] == 2
        and study["tasks_per_window"] == 512
        and study["minimum_window_micros"] == 1000000
        and study["parent_file_sha256"] == parent["file_sha256"],
        "explicit preregistered diverse work with original future windows",
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
        "unmodified original ten-step material plan",
    )
    data_path = training_chain / "config/pon/binary-diverse60-training-v3.json"
    data = work.training_data(data_path)
    require(
        data == work.training_data(),
        "same exact public source bytes in both repositories",
    )
    dataset = read_pin(value["training_data"])
    checked_training_data(dataset, plan, plan_raw, data)
    plan_path = output / "model-plan.json"
    plan_path.write_bytes(plan_raw)
    execution_value = dict(
        files=dict(plan=str(plan_path)),
        parent={key: parent[key] for key in ("contract", "adapter", "file_sha256")},
        initial_setup=dict(
            profile=diverse.PROFILE,
            recipe=dict(setup.RECIPE),
            parent_material=dict(value["parent"]),
            training_data=pin(data_path),
        ),
    )
    execution_plan = output / "diverse-execution-plan-v3.json"
    runtime.save(execution_plan, diverse.plan_record(execution_value))
    execution_value["initial_setup"]["diverse_plan"] = pin(execution_plan)
    context = diverse.context(execution_value)
    work.validate_context(context, data)
    directory = Path(parent["directory"])
    attempt = sha(
        canonical(
            dict(
                schema=SCHEMA + "-actual-parent-attempt",
                input=input_pin,
                study=value["study"],
                ordinary=value["ordinary"],
            )
        )
    )
    parent_step.run(
        SimpleNamespace(
            operation="train",
            initial_setup_profile=diverse.PROFILE,
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
            binary_plan=None,
            binary_plan_sha256=None,
            diverse_plan=str(execution_plan),
            diverse_plan_sha256=runtime.file_sha(execution_plan),
            diverse_training_data=str(data_path),
            diverse_training_data_sha256=work.DATA_SHA256,
        )
    )
    completion_pin = pin(
        output / ("training/parent-step-result-" + work.SUFFIX + ".json")
    )
    completion = read_pin(completion_pin)
    training_pin = pin(output / "training/execution/actual-receipt.json")
    trained = read_pin(training_pin)
    require(
        completion["outcome"] == "success"
        and completion["completion_verified"] is True
        and completion["actual_receipt_sha256"] == training_pin["sha256"]
        and trained["parent_readback"] == parent["adapter"]
        and trained["training"]["steps"] == 30
        and trained["training_changed_from_setup"] is True
        and trained[work.CONTEXT_KEY] == completion[work.CONTEXT_KEY] == context,
        "complete actual diverse parent training under the original owner",
    )
    require(
        read_pin(value["training_data"]) == dataset
        and checked_training_data(
            dataset, plan, plan_path.read_bytes(), work.training_data(data_path)
        )
        == data["training_rows"],
        "admitted dataset remains exactly the completed public training source",
    )
    consumption = consumption_receipt(
        runtime, value, plan, data, trained, training_pin, output
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
    child = dict(
        schema=inherited.PARENT_SCHEMA,
        generation=2,
        operation_id=attempt,
        directory=str(child_directory),
        contract=parent["contract"],
        **trained["candidate"],
    )
    inherited.read_parent(child)
    child_pin = save(output / "candidate-parent.json", child)
    original.runtime_snapshot()
    save(
        output / "training-result.json",
        dict(
            schema=SCHEMA + "-training-result",
            input=input_pin,
            study=value["study"],
            ordinary=value["ordinary"],
            parent=value["parent"],
            child=child_pin,
            training=training_pin,
            completion=completion_pin,
            training_data=value["training_data"],
            training_consumption=consumption,
            source_dataset_digest=dataset["source_dataset_digest"],
            **{work.CONTEXT_KEY: context},
            training_chain=training_commit,
            training_tree=TRAINING_TREE,
            runtime_chain=original.RUNTIME,
            installation_authority=False,
        ),
    )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-sha256", required=True)
    args = parser.parse_args()
    request = dict(path=str(Path(args.input).resolve()), sha256=args.input_sha256)
    value = read_pin(request)
    require(
        (value["schema"], value["operation"])
        in (
            (SCHEMA, "train"),
            (original.SCHEMA, "forward"),
            (original.SCHEMA, "transport"),
        ),
        "explicit diverse train or unchanged original forward/transport namespace",
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


if __name__ == "__main__":
    main()
