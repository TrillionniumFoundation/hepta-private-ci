"""Compare frozen coding models or local routed Circuits in two fresh processes.

Run python -m cell_experiments.paired_cold REQUEST CANONICAL_SHA256 MATERIALS OUT.
REQUEST uses schema hepta.paired-cold.request.v1, embedded parent/candidate model
manifests, nonempty retention/future lists of authorized evaluation records and
a positive per-arm timeout_seconds. Use a fresh private OUT for each separate
experiment. Retained attempts are never overwritten. Reported observations do
not authenticate independent users, event chronology, adoption or settlement.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from . import (
    adoption,
    chat_protocol,
    coding_sft,
    data,
    prospective_exposure,
    paired_source,
)

ARMS = ("parent", "candidate")
PANELS = ("future", "retention")


def loader_for(model):
    if (
        model["family"] == coding_sft.FAMILY
        and model["schema"] == coding_sft.MODEL_SCHEMA
    ):
        return coding_sft
    from .online_v4 import circuit_bundle

    adoption.require(
        model["family"] == circuit_bundle.FAMILY
        and model["schema"] == circuit_bundle.SCHEMA,
        "unsupported model profile",
    )
    return circuit_bundle


def verify_materials(model, materials):
    loader = loader_for(model)
    if loader is coding_sft:
        return coding_sft.verify_model(model, materials)
    return loader.checked_bundle(model, materials)


def cell_weights_changed(parent, child):
    for model in (parent, child):
        adoption.need(model, "parent schema family files runtime")
        adoption.require(
            loader_for(model) is coding_sft, "expected a coding Cell manifest"
        )

    def inference_settings(model):
        return {
            k: v
            for k, v in model["runtime"].items()
            if k not in ("base_directory", "adapter_directory")
        }

    def artifacts(model, role):
        return sorted(
            (Path(f["path"]).name, f["sha256"]) for f in model["files"] if role(f)
        )

    def frozen_input_artifact(f):
        return f["role"] == "tokenizer" or Path(f["path"]).name in {
            "config.json",
            "generation_config.json",
            "chat_template.jinja",
        }

    def weight_hashes(model):
        runtime = model["runtime"]
        weights = [Path(runtime["base_directory"]) / "model.safetensors"]
        if runtime.get("adapter_directory"):
            weights.append(
                Path(runtime["adapter_directory"]) / "adapter_model.safetensors"
            )
        files = {Path(item["path"]): item["sha256"] for item in model["files"]}
        adoption.require(
            all(path in files for path in weights), "missing loaded Cell weights"
        )
        return [files[path] for path in weights]

    adoption.require(
        inference_settings(parent) == inference_settings(child)
        and artifacts(parent, frozen_input_artifact)
        == artifacts(child, frozen_input_artifact),
        "inference settings or tokenizer changed",
    )
    return weight_hashes(parent) != weight_hashes(child)


def checked_models(parent, child):
    for model in (parent, child):
        adoption.need(model, "parent schema family runtime")
    adoption.require(child["parent"] == data.digest(parent), "wrong candidate parent")
    loader = loader_for(parent)
    adoption.require(loader is loader_for(child), "incompatible paired model families")
    if loader is coding_sft:
        adoption.require(cell_weights_changed(parent, child), "unchanged weights")
        return
    for bundle in (parent, child):
        adoption.need(bundle, "models budget router router_sha256")
        adoption.need(bundle["router"], "plan graphs weights")
        adoption.require(
            data.digest(bundle["router"]) == bundle["router_sha256"],
            "router digest differs",
        )
    adoption.require(
        set(parent["models"]) == set(child["models"]) and parent["models"],
        "Cell slots changed",
    )
    adoption.require(
        parent["runtime"] == child["runtime"] and parent["budget"] == child["budget"],
        "Circuit runtime or budget changed",
    )
    adoption.require(
        all(
            parent["router"][key] == child["router"][key] for key in ("plan", "graphs")
        ),
        "Circuit routing plan or graph inventory changed",
    )
    changed = []
    for cell_id in sorted(parent["models"]):
        old, new = parent["models"][cell_id], child["models"][cell_id]
        if cell_weights_changed(old, new):
            adoption.require(
                new["parent"] == data.digest(old), "wrong changed Cell parent"
            )
            changed.append(cell_id)
    router_changed = parent["router"]["weights"] != child["router"]["weights"]
    adoption.require(changed or router_changed, "unchanged Cell and router weights")
    return {"changed_cell_weights": changed, "router_weights_changed": router_changed}


def checked_panels(panels, runtime):
    adoption.require(
        isinstance(panels, dict) and set(panels) in ({"retention"}, set(PANELS)),
        "retention or complete paired panels required",
    )
    seen = set()
    visible_inputs = set()
    protocol = chat_protocol.protocol_name(runtime)
    for panel, records in panels.items():
        adoption.require(
            isinstance(records, list) and records, "missing " + panel + " panel"
        )
        for record in records:
            data.validate_record(record, require_outcome=False)
            adoption.require(
                panel != "future" or record["split"] == "confirmation",
                "future tasks require the confirmation split",
            )
            adoption.require(record["task_id"] not in seen, "repeated task identity")
            seen.add(record["task_id"])
            task = record["task"]
            if protocol == chat_protocol.NATIVE:
                visible = chat_protocol.inference_wire_messages(
                    task["input"], task.get("messages")
                )
            else:
                adoption.require(
                    task.get("messages") is None, "unsupported legacy chat history"
                )
                visible = task["input"]
            identity = data.digest(visible)
            adoption.require(
                identity not in visible_inputs, "repeated model-visible input"
            )
            visible_inputs.add(identity)


def checked_request(path, expected):
    req = adoption.read_json(path)
    adoption.need(req, "schema")
    adoption.require(
        req.get("schema") == "hepta.paired-cold.request.v1"
        and data.digest(req) == expected,
        "frozen request differs",
    )
    adoption.need(req, "parent candidate future retention timeout_seconds")
    parent, child = req["parent"], req["candidate"]
    checked_models(parent, child)
    adoption.require(
        type(req["timeout_seconds"]) is int and req["timeout_seconds"] > 0,
        "positive per-arm time budget required",
    )
    checked_panels({p: req[p] for p in PANELS}, parent["runtime"])
    prospective_exposure.check_request(req, prospective_exposure.catalog_for(child))
    paired_source.check_future(req)
    return req


def frozen_tokenizer(model, materials):
    """Open the manifest-bound tokenizer used for the original task input."""
    from transformers import AutoTokenizer

    verify_materials(model, materials)
    loader = loader_for(model)
    if loader is not coding_sft:
        model = loader.input_manifest(model)
    runtime = model["runtime"]
    protocol = chat_protocol.protocol_name(runtime)
    tokenizer = AutoTokenizer.from_pretrained(
        Path(materials) / runtime["base_directory"],
        local_files_only=True,
        trust_remote_code=False,
    )
    if protocol == chat_protocol.NATIVE:
        adoption.require(
            chat_protocol.template_digest(tokenizer.get_chat_template())
            == runtime["chat_template_sha256"],
            "preflight tokenizer template changed",
        )
    return tokenizer


def token_inputs(req, model, materials):
    """Catch template collapse and tokenizer collisions before loading model weights."""
    tokenizer = frozen_tokenizer(model, materials)
    runtime = model["runtime"]
    protocol = chat_protocol.protocol_name(runtime)
    router_training = set()
    if loader_for(model) is not coding_sft:
        router_training = {
            sample["input_ids_sha256"]
            for arm in ARMS
            for sample in req[arm]["router_training_inputs"]
        }
    catalog = prospective_exposure.catalog_for(req.get("candidate", model))
    exposed_inputs = (
        {row["input_ids_sha256"] for row in catalog["known_inputs"]}
        if catalog
        else set()
    )
    exposed_inputs.update(
        req.get("candidate", model)
        .get("paired_source_exposure", {})
        .get("input_ids_sha256", [])
    )
    inputs = {}
    seen = set()
    for panel in PANELS:
        for record in req[panel]:
            task = record["task"]
            text = coding_sft.prompt_text(
                task["input"], tokenizer, protocol, task.get("messages")
            )
            tokens = tokenizer.encode(text, add_special_tokens=False)
            adoption.require(
                0 < len(tokens) <= runtime["max_input_tokens"],
                "input outside frozen token budget",
            )
            token_hash = data.digest(tokens)
            adoption.require(token_hash not in seen, "repeated model input token IDs")
            if panel == "future":
                adoption.require(
                    token_hash not in exposed_inputs,
                    "future matches known historical input token IDs",
                )
                adoption.require(
                    token_hash not in router_training,
                    "future input repeats a frozen router training input",
                )
            seen.add(token_hash)
            inputs[record["task_id"]] = token_hash
    return inputs


def visible_task(record):
    return {
        key: record["task"][key]
        for key in ("input", "messages")
        if key in record["task"]
    }


def cold_arm(req, arm, materials, out, expected):
    model = req[arm]
    inputs = token_inputs(req, model, materials)
    start = time.time_ns()
    predictor = loader_for(model).load_predictor(model, materials)
    model_digest = data.digest(model)
    loaded = time.time_ns()
    rows = []
    try:
        for panel in PANELS:
            for record in req[panel]:
                # Only the deployment-time task input enters the predictor.
                prediction = adoption.prediction(
                    predictor, {"task": visible_task(record)}, model_digest
                )
                outcome = data.verify_answer(record, prediction["answer"])
                row = dict(
                    panel=panel,
                    task_id=record["task_id"],
                    task_sha256=data.digest(record),
                    input_ids_sha256=inputs[record["task_id"]],
                    prediction=prediction,
                    outcome=outcome,
                )
                coding_sft.write_new(out / arm / f"{len(rows):04d}.json", row)
                rows.append(row)
        adoption.require(
            verify_materials(model, materials) == model_digest,
            "cold model changed during execution",
        )
    finally:
        predictor.close()
    coding_sft.write_new(
        out / arm / "END.json",
        {
            "request_sha256": expected,
            "arm": arm,
            "model_digest": model_digest,
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "started_ns": start,
            "loaded_ns": loaded,
            "ended_ns": time.time_ns(),
            "row_hashes": [data.digest(r) for r in rows],
        },
    )


def compare(req, out, expected, pids, materials=None):
    receipts = [adoption.read_json(out / arm / "END.json") for arm in ARMS]
    loader = loader_for(req["parent"])
    circuit = loader is not coding_sft
    if circuit:
        adoption.require(
            materials is not None, "Circuit readback requires original model materials"
        )
        tokenizers = {arm: frozen_tokenizer(req[arm], materials) for arm in ARMS}
    keys = [(p, r) for p in PANELS for r in req[p]]
    for arm, receipt, pid in zip(ARMS, receipts, pids, strict=True):
        adoption.require(
            receipt["pid"] == pid
            and receipt["ppid"] == os.getpid()
            and receipt["request_sha256"] == expected
            and receipt["arm"] == arm
            and receipt["model_digest"] == data.digest(req[arm])
            and len(receipt["row_hashes"]) == len(keys),
            "cold process binding differs",
        )
    counts = {
        p: {"both": 0, "parent_only": 0, "candidate_only": 0, "neither": 0}
        for p in PANELS
    }
    work = {
        arm: {"model_calls": 0, "input_tokens": 0, "output_tokens": 0} for arm in ARMS
    }
    for i, (panel, task) in enumerate(keys):
        scores, inputs = [], []
        for arm, receipt in zip(ARMS, receipts, strict=True):
            row = adoption.read_json(out / arm / f"{i:04d}.json")
            prediction = row["prediction"]
            if circuit:
                loader.check_prediction(
                    req[arm], prediction, visible_task(task), tokenizers[arm]
                )
                original = prediction["circuit_trace"]["nodes"][0]["output"]
                adoption.require(
                    original["input_ids_sha256"] == row["input_ids_sha256"],
                    "Circuit executed input differs from preflight",
                )
                for key in work[arm]:
                    work[arm][key] += prediction["circuit_trace"]["cost"][key]
            outcome = data.verify_answer(task, prediction["answer"])
            adoption.require(
                row["panel"] == panel
                and row["task_id"] == task["task_id"]
                and row["task_sha256"] == data.digest(task)
                and prediction["pid"] == receipt["pid"]
                and prediction["loaded_model_digest"] == receipt["model_digest"]
                and prediction["input_sha256"] == outcome["input_sha256"]
                and data.digest(outcome) == data.digest(row["outcome"])
                and data.digest(row) == receipt["row_hashes"][i],
                "paired row differs",
            )
            inputs.append(
                (
                    row["input_ids_sha256"],
                    prediction["rendered_input_sha256"],
                    prediction["input_tokens"],
                )
            )
            scores.append(outcome["success"])
        adoption.require(inputs[0] == inputs[1], "effective inputs differ across arms")
        outcome_key = {
            (True, True): "both",
            (True, False): "parent_only",
            (False, True): "candidate_only",
            (False, False): "neither",
        }[tuple(scores)]
        counts[panel][outcome_key] += 1
    future, retained = counts["future"], counts["retention"]
    return {
        "schema": "hepta.paired-cold.result.v1",
        "request_sha256": expected,
        "model_family": req["parent"]["family"],
        "circuit_loaded": circuit,
        **(
            {
                "paired_circuit_changes": checked_models(
                    req["parent"], req["candidate"]
                ),
                "measured_circuit_work": work,
            }
            if circuit
            else {}
        ),
        "evaluation_order": list(PANELS),
        "retention_scope": "pooled covered tasks passed by the frozen parent",
        "cold_receipts": receipts,
        "counts": counts,
        "future_success_count_delta": future["candidate_only"] - future["parent_only"],
        "old_parent_successes_preserved": retained["both"] > 0
        and retained["parent_only"] == 0,
        "external_teacher_calls_by_runner": 0,
        "authenticated_users_established": False,
        "prospective_arrival_authenticated": False,
        "production_adoption": False,
        "settlement": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("digest")
    parser.add_argument("materials", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arm", choices=ARMS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    req = checked_request(args.request, args.digest)
    out = args.output
    if args.arm:
        cold_arm(req, args.arm, args.materials, out, args.digest)
        return
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    coding_sft.write_new(out / "REQUEST.json", req)
    env = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    pids = []
    for arm in ARMS:
        directory = out / arm
        directory.mkdir()
        command = [
            sys.executable,
            "-m",
            "cell_experiments.paired_cold",
            str(out / "REQUEST.json"),
            args.digest,
            str(args.materials),
            str(out),
            "--arm",
            arm,
        ]
        with (
            (directory / "stdout.log").open("xb") as stdout,
            (directory / "stderr.log").open("xb") as stderr,
        ):
            with subprocess.Popen(
                command, env=env, stdout=stdout, stderr=stderr
            ) as process:
                pids.append(process.pid)
                try:
                    status = process.wait(timeout=req["timeout_seconds"])
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise
                if status:
                    raise subprocess.CalledProcessError(status, command)
    coding_sft.write_new(
        out / "RESULT.json", compare(req, out, args.digest, pids, args.materials)
    )


if __name__ == "__main__":
    main()
