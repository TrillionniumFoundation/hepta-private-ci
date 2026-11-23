"""Reopen a fictional hosted run, replay its frozen route and inspect raw model bytes."""

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct

import numpy as np
import sys
import zipfile

from cell_experiments import data
from cell_experiments.online_v4 import circuit_bundle


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def tensors(raw):
    n = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8:8+n])
    arrays = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        lo, hi = info["data_offsets"]
        require(info["dtype"] == "F32", "fixture tensor precision differs")
        arrays[name] = np.frombuffer(raw[8+n+lo:8+n+hi], dtype="<f4").reshape(info["shape"])
    return arrays


def replay_token(z, model, ids):
    """Independent forward for this archived GPT-2 fixture, checking its zero residual blocks."""
    runtime = model["runtime"]
    root = "original/materials/"
    base = root + runtime["base_directory"] + "/"
    config = json.loads(z.read(base + "config.json"))
    weights = tensors(z.read(base + "model.safetensors"))
    require(config["model_type"] == "gpt2" and config["n_layer"] == 1 and runtime["max_new_tokens"] == 1
            and sum(k.startswith("transformer.h.0.") for k in weights) == 12
            and all(not np.any(v) for k, v in weights.items() if k.startswith("transformer.h.")),
            "the checked one-step GPT-2 residual simplification does not apply")
    hidden = weights["transformer.wte.weight"][ids[-1]] + weights["transformer.wpe.weight"][len(ids)-1]
    centered = hidden - hidden.mean()
    normalized = centered / np.sqrt(np.mean(centered * centered) + np.float32(config["layer_norm_epsilon"]))
    hidden = normalized * weights["transformer.ln_f.weight"] + weights["transformer.ln_f.bias"]
    head = weights["lm_head.weight"]
    adapter = runtime.get("adapter_directory")
    if not adapter:
        return int(np.argmax(head @ hidden))
    base = root + adapter + "/"
    c = json.loads(z.read(base + "adapter_config.json"))
    require(c["target_modules"] == ["lm_head"] and not c["fan_in_fan_out"] and not c["use_dora"]
            and not c["use_rslora"] and c["bias"] == "none", "unsupported archived adapter")
    a = tensors(z.read(base + "adapter_model.safetensors"))
    prefix = "base_model.model.lm_head."
    head = a.get(prefix + "base_layer.weight", head)
    delta = a[prefix + "lora_B.weight"] @ (a[prefix + "lora_A.weight"] @ hidden)
    logits = head @ hidden + np.float32(c["lora_alpha"] / c["r"]) * delta
    require(np.isfinite(logits).all(), "nonfinite reconstructed logits")
    return int(np.argmax(logits))


def audit(path):
    with zipfile.ZipFile(path) as z, sqlite3.connect(":memory:") as db:
        def read(member):
            return json.loads(z.read(member))
        summary = read("SUMMARY.json")
        db.deserialize(z.read("original/intake/intake.sqlite"))
        admission, pair, binding_raw, raw, state = db.execute(
            "SELECT id,request_sha,binding,request_json,state FROM admissions"
        ).fetchone()
        binding, req = json.loads(binding_raw), json.loads(raw)
        root = "original/intake/" + admission + "/"
        require(summary["admission"] == admission == data.digest(binding)
                and state == "released" and binding["release"]["scope"] == "engineering_fixture"
                and req == read(root + "paired.json") and data.digest(req) == pair,
                "original engineering admission differs")
        bundle = req["candidate"]
        model_files = {}
        fit_receipts = {}
        for arm in ("parent", "candidate"):
            for cell, model in req[arm]["models"].items():
                for f in model["files"]:
                    b = z.read("original/materials/" + f["path"])
                    require(sha(b) == f["sha256"] and len(b) == f["bytes"], "actual model bytes differ")
                    model_files[f["path"]] = f["sha256"]
                folder = model["runtime"].get("adapter_directory")
                if folder:
                    training = read("original/materials/" + folder + "/TRAINING.json")
                    require(data.digest(training) == req[arm]["consumer_cell_training_receipts"][cell]
                            and training["child"] == data.digest(model)
                            and training["initial_verification"]["success"] is False
                            and training["corrected_verification"]["success"] is True, "original Cell fit differs")
                    fit_receipts[cell] = training["input"]
        require(fit_receipts == {"source": "train", "reader": "1"}, "historical Cell input coverage differs")
        select = read(root + "consumer/selection/RESULT.json")
        for panel_i, panel in enumerate(("future", "retention")):
            for arm_i, arm in enumerate(("parent", "candidate")):
                prefix = root + "consumer/selection/" + arm + "/"
                raw_row = read(prefix + f"{panel_i:04d}.json")
                end = read(prefix + "END.json")
                original = req[panel][0]
                pred = raw_row["prediction"]
                require(end == select["cold_receipts"][arm_i] and end["row_hashes"][panel_i] == data.digest(raw_row)
                        and raw_row["task_sha256"] == data.digest(original), "original cold pair differs")
                circuit_bundle.check_prediction(req[arm], pred, {"input": original["task"]["input"]})
                for node in pred["circuit_trace"]["nodes"]:
                    output = node["output"]
                    require(output["output_ids"] == [replay_token(z, req[arm]["models"][node["cell_id"]], output["input_ids"])],
                            "cold tensor forward disagrees with retained node")
                require(json.loads(pred["answer"]) == (1 if arm == "candidate" and panel == "future" else 0),
                        "unexpected cold fixture answer")
        op = summary["run"]["operation"]
        out = root + "consumer/" + op + "/"
        start, run, worker, material, outcome = [read(out + n + ".json") for n in (
            "STARTED", "RUN", "worker-output", "worker-input", "OUTCOME")]
        pred = worker["prediction"]
        scope = start["request"]
        task = material["task"]
        selection = data.digest(select)
        base = {"pair": pair, "candidate": data.digest(bundle), "task": data.digest(task)}
        require(op == data.digest(["hepta.paired-learning.subsequent-operation.v1", admission, selection, base])
                and scope == dict(use="request_consumer_run", operation=op, **base) and run["request"] == scope
                and material["model"] == bundle and start["nonce"] == run["nonce"] == worker["nonce"] == material["nonce"]
                and len(bytes.fromhex(run["nonce"])) == 32 and task == {"input": "train later"}
                and selection == run["selection_sha256"], "subsequent task or run binding differs")
        require(read("original/site/consumer-task-" + data.digest(task) + ".json") == task, "source task differs")
        circuit_bundle.check_prediction(bundle, pred, task)
        trace = pred["circuit_trace"]
        nodes = trace["nodes"]
        require(trace["graph"]["graph_id"] == "connected" and trace["graph"]["edges"] == ["answer"]
                and [n["cell_id"] for n in nodes] == ["source", "reader"] and trace["cost"]["model_calls"] == 2
                and trace["cost"]["verifier_calls"] == 0, "unexpected Circuit trace")
        node_summary = []
        for node in nodes:
            cell = bundle["models"][node["cell_id"]]
            directory = cell["runtime"]["base_directory"]
            vocab = read("original/materials/" + directory + "/tokenizer.json")["model"]["vocab"]
            raw = node["output"]
            rendered = " ".join(("Tool observation:\n" if m["role"] == "tool" else "") + m["content"]
                                for m in node["request"]["messages"])
            pieces = re.findall(r"\w+|[^\w\s]+", rendered)
            require(rendered == raw["rendered_input"] and raw["input_ids"] == [vocab.get(t, vocab["[UNK]"]) for t in pieces]
                    and raw["output_ids"] == [vocab[raw["answer"]]] == [replay_token(z, cell, raw["input_ids"])] and raw["pid"] == run["local_child_pid"]
                    and raw["loaded_model_digest"] == data.digest(cell), "slot tokenizer, generation or model differs")
            node_summary.append(dict(cell=node["cell_id"], model_sha256=data.digest(cell),
                                     input_ids=raw["input_ids"], output_ids=raw["output_ids"], answer=raw["answer"]))
        answer = z.read(out + "answer.utf8")
        effect = z.read(out + "effect.bin")
        require(answer == nodes[-1]["output"]["answer"].encode() == b"1"
                and nodes[1]["request"]["messages"][-1] == {"role": "tool", "content": nodes[0]["output"]["answer"]}
                and summary["run"]["run_receipt"] == data.digest(run) == outcome["scope"]["run_receipt"]
                and run["prediction_sha256"] == data.digest(worker) and run["grant_sha256"] == data.digest(start["grant"])
                and run["output_sha256"] == sha(answer) == outcome["scope"]["output"]
                and sha(effect) == outcome["scope"]["effect"]
                and z.read("original/site/consumer-effect-" + sha(effect) + ".bin") == effect
                and outcome["scope"]["outcome"] == "accepted"
                and outcome["evidence_scope"] == "engineering_fixture" and outcome["payment_authorized"] is False,
                "actual relay, answer or original outcome differs")
        for name, statement, grant in (("request", scope, start["grant"]), ("report", outcome["scope"], outcome["grant"])):
            event = read(name + "-fixture-event.json")
            displayed = {"study_sha256": binding["release"]["study_sha256"], "scope": statement}
            require(event["receipt"] == grant and event["request"] == dict(displayed, delivery_id=grant["delivery_id"])
                    and grant["study_principal_sha256"] == binding["native"]["study_principal_sha256"]
                    and grant["statement_sha256"] == sha(b"Fixture statement " + data.canonical(displayed)),
                    "fictional B or source statement differs")
        return dict(scope="engineering_fixture", archive_sha256=sha(path.read_bytes()), archive_bytes=path.stat().st_size,
                    files=sum(not n.endswith("/") for n in z.namelist()), unique_model_files=len(model_files),
                    original_cell_training_prompts=fit_receipts, selection_cold_arms=2, selection_cold_rows=4,
                    subsequent_route=trace["graph"]["graph_id"], independent_numpy_cell_forwards=10,
                    subsequent_nodes=node_summary,
                    subsequent_output_utf8=answer.decode(), operation=op, run_sha256=data.digest(run),
                    decision="accepted", fixture_outcome_sha256=data.digest(outcome), live_humans=0,
                    verified_remote_executions=0, payments=0)


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1])), indent=2))
