#!/usr/bin/env python3
"""One real original-parent training task and observed label-free forwards.

The Rust ordinary owner freezes the study, consumes the future holdout and
performs qualification/installation. This process cannot issue those receipts.
"""

import argparse
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

TRAINING = "8444eeee03e29caaa45902107e82df0eb980bede"
RUNTIME = "c96022b897c1235fdbdbfcfa32764403511c6aab"
SCHEMA = "hepta-neural-study-v1"


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path.read_bytes())}


def read_pin(value):
    require(type(value) is dict and set(value) == {"path", "sha256"}, "closed pin")
    path = Path(value["path"])
    require(
        path.is_absolute() and path.is_file() and not path.is_symlink(),
        "regular absolute pin",
    )
    require(0 < path.stat().st_size <= 32 * 1024 * 1024, "bounded input")
    raw = path.read_bytes()
    require(sha(raw) == value["sha256"], "pinned source changed")
    return json.loads(raw)


def save(path, value):
    raw = canonical(value)
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return pin(path)


def checkout(path, expected):
    require(path.is_absolute(), "absolute source checkout")
    require(
        subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()
        == expected,
        "exact source commit",
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts",
            "formal",
            "config",
        ],
        check=True,
    )


def runtime_snapshot():
    snapshot = Path(os.environ["HEPTA_PUBLIC_INITIAL_RUNTIME_SNAPSHOT"])
    require(
        sys.flags.isolated == 1
        and sys.flags.no_user_site == 1
        and snapshot.is_absolute(),
        "isolated original Python with pinned wheel closure",
    )
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(__file__).with_name("hepta_smollm_runtime_snapshot.py")),
            "verify",
            "--snapshot",
            str(snapshot),
        ],
        check=True,
    )


def checked_training_data(value, plan, plan_raw):
    """Bind the unchanged trainer's exact step schedule to the admitted dataset.

    A ledger observation denotes the supervised ground-truth answer. It is not
    a model prediction or a counterfactual training example.
    """
    require(
        value["schema"] == "hepta-neural-actual-training-data-v1",
        "training-data schema",
    )
    offered = [row for row in plan["tasks"] if row["partition"] == "training"]
    indices = [step % len(offered) for step in range(plan["training_steps"])]
    consumed = [offered[index] for index in indices]
    require(
        len(offered) == 12 and len(consumed) == 10 and indices == list(range(10)),
        "original twelve-row supply and ten-step consumption",
    )
    require(
        read_pin(value["model_plan"]) == plan
        and value["model_plan"]["sha256"] == sha(plan_raw)
        and value["offered_training_rows"] == offered
        and value["consumed_training_rows"] == consumed
        and value["consumed_step_indices"] == indices,
        "exact training-data translation",
    )
    snapshot = value["dataset_receipt"]["snapshot"]
    require(
        snapshot["dataset_digest"] == value["source_dataset_digest"]
        and len(snapshot["source_record_digests"]) == 20
        and snapshot["pending_outcomes"] == snapshot["censored_outcomes"] == 0,
        "one authenticated target per consumed row, with no additional outcomes",
    )
    ledger = Path(value["ledger"]["path"])
    require(
        ledger.is_file() and not ledger.is_symlink() and pin(ledger) == value["ledger"],
        "frozen actual training ledger bytes",
    )
    return consumed


def consumption_receipt(runtime, value, plan, consumed, trained, training_pin, output):
    # Reconstruct exactly the original deterministic token/label translation.
    # The model task itself remains unchanged; its pinned source, experiment
    # identity, completed steps and token counts bind this independent readback.
    from transformers import AutoTokenizer

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
        "original training tokenizer",
    )
    steps = []
    for number, row in enumerate(consumed):
        prompt = runtime.prompt_tokens(tokenizer, row, plan["input_tokens_max"])
        target = (
            tokenizer.encode(row["expected_output"], add_special_tokens=False) + [2] * 3
        )
        ids, labels = prompt + target, [-100] * len(prompt) + target
        require(
            len(ids) <= plan["input_tokens_max"],
            "untruncated original training tensors",
        )
        steps.append(
            dict(
                step=number,
                source_row_id=row["id"],
                source_row_sha256=sha(canonical(row)),
                input_ids=ids,
                labels=labels,
                supervised_tokens=len(target),
            )
        )
    require(
        trained["experiment"] == runtime.identity(plan)
        and trained["source"]["runtime"] == runtime.file_sha(runtime.__file__)
        and trained["training"]["tokens"] == sum(len(row["input_ids"]) for row in steps)
        and trained["training"]["supervised_tokens"]
        == sum(row["supervised_tokens"] for row in steps),
        "actual completed training source/plan/token totals match the source dataset",
    )
    return save(
        output / "training-consumption.json",
        dict(
            schema="hepta-neural-original-training-consumption-v1",
            training_data=value["training_data"],
            actual_receipt=training_pin,
            original_runtime_source_sha256=runtime.file_sha(runtime.__file__),
            experiment=runtime.identity(plan),
            steps=steps,
            evidence_scope="deterministic original token/label reconstruction checked against actual completed source-bound task; not an instrumented per-step trace",
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
    checkout(training_chain, TRAINING)
    checkout(runtime_chain, RUNTIME)
    runtime_snapshot()
    sys.path.insert(0, str(training_chain / "scripts"))
    sys.path.insert(0, str(Path(__file__).parent))
    runtime = importlib.import_module("llm_runtime_pilot")
    inherited = importlib.import_module("llm_inherited_runtime")
    parent_step = importlib.import_module("llm_runtime_parent_step_v2")
    observed = importlib.import_module("llm_runtime_observed_execution_v1")
    observation = importlib.import_module("hepta_smollm_observed_execution_v1")
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
        and study["model_training_steps"] == 10
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
    args = SimpleNamespace(
        parent=Path(value["parent"]["path"]),
        parent_sha256=value["parent"]["sha256"],
        output=output,
    )
    observation_value = observation.freeze_plan(
        args, runtime, parent_step, parent, plan_path
    )
    context = observed.context(observation_value)
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
            initial_setup_profile=observed.PROFILE,
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
            observation_plan=observation_value["initial_setup"]["observation_plan"][
                "path"
            ],
            observation_plan_sha256=observation_value["initial_setup"][
                "observation_plan"
            ]["sha256"],
        )
    )
    completion_pin = pin(output / "training/parent-step-result-observed-v1.json")
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
        and trained["observation_execution"]
        == completion["observation_execution"]
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
        shutil.copyfile(
            source if source.exists() else directory / name, child_directory / name
        )
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
            "observation_execution": context,
            "training_chain": TRAINING,
            "runtime_chain": RUNTIME,
            "installation_authority": False,
        },
    )


def forward(value, input_pin):
    require(
        set(value)
        == {
            "schema",
            "operation",
            "runtime_chain",
            "training_chain",
            "materials",
            "parent",
            "worker_plan",
            "tasks",
            "model",
            "window_id",
            "phase_id",
            "output",
        },
        "closed forward request",
    )
    checkout(Path(value["runtime_chain"]), RUNTIME)
    checkout(Path(value["training_chain"]), TRAINING)
    runtime_snapshot()
    sys.path.insert(0, str(Path(value["training_chain"]) / "scripts"))
    runtime = importlib.import_module("llm_runtime_pilot")
    output = Path(value["output"])
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    script = Path(__file__).with_name("hepta_neural_forward_v1.py").resolve()
    sources = {
        path: sha((Path(value["runtime_chain"]) / path).read_bytes())
        for path in (
            "formal/pon-nakamoto-v1/llm_adapter_contract.py",
            "scripts/llm_inherited_runtime.py",
            "scripts/llm_neural_read_worker.py",
            "scripts/llm_parent_material.py",
            "scripts/llm_runtime_pilot.py",
            "config/pon/model-family-smollm2-135m-v1.json",
        )
    }
    config = {
        "schema": "hepta-neural-positive-forward-v1",
        "source_sha256": sha(script.read_bytes()),
        "chain": value["runtime_chain"],
        "chain_commit": RUNTIME,
        "sources": sources,
        "materials": value["materials"],
        "parent": value["parent"],
        "worker_plan": value["worker_plan"],
        "tasks": value["tasks"],
        "output": str(output / "worker"),
        "owner_pid": os.getpid(),
        "deadline_monotonic_ns": time.monotonic_ns() + 600000000000,
        "budget": {"wall_seconds": 600, "rss_bytes": 8 * 1024**3},
        "phase_id": value["phase_id"],
        "model": value["model"],
        "window_id": value["window_id"],
    }
    config_pin = save(output / "observed-input.json", config)
    result = runtime.supervise(
        [
            sys.executable,
            "-I",
            "-B",
            str(script),
            "--input",
            config_pin["path"],
            "--input-sha256",
            config_pin["sha256"],
        ],
        output / "supervisor",
        config["budget"],
        exit_observation=runtime.exit_observation_profile(
            "linux-owned-exit-worker-pidfd-v4"
        ),
    )
    save(output / "supervisor-result.json", result)
    require(
        result["outcome"] == "success"
        and result["exit_code"] == 0
        and result["stop_reason"] is None
        and result["waited_child_reaped"] is True
        and result["owned_child_reap_resolved"] is True
        and result["exit_observation_profile"]["maximum_drain_ns"] == 100000000,
        "original 600s/8GiB/100ms complete forward supervision",
    )
    actual_pin = pin(output / "worker/forward-result.json")
    actual = read_pin(actual_pin)
    require(
        actual["forwards"] == 512 and actual["loads"] == 9, "complete real forwards"
    )
    runtime_snapshot()
    save(
        output / "phase-result.json",
        {
            "schema": SCHEMA + "-forward-result",
            "input": input_pin,
            "actual": actual_pin,
            "supervisor": pin(output / "supervisor-result.json"),
            "window_id": value["window_id"],
            "model": value["model"],
            "installation_authority": False,
        },
    )


def transport(value, input_pin):
    require(
        set(value) == {"schema", "operation", "request", "output"},
        "closed transport request",
    )
    sys.path.insert(0, str(Path(__file__).parent))
    cell = importlib.import_module("hepta_neural_candidate_transport_v1")
    deadline = time.monotonic() + cell.SECONDS
    request = cell.decode(cell.pinned(value["request"]))
    result = cell.transport(
        request, value["output"], value["request"]["sha256"], deadline
    )
    require(result["outcome"] == "success", "actual two-node Cell transport failed")


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--input-sha256", required=True)
    args = parser.parse_args()
    request = {"path": str(Path(args.input).resolve()), "sha256": args.input_sha256}
    value = read_pin(request)
    require(value["schema"] == SCHEMA, "explicit study namespace")
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
    {"train": train, "forward": forward, "transport": transport}[value["operation"]](
        value, request
    )
