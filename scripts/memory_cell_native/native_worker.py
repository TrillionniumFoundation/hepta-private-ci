"""Actual fixed-adapter NeuronModelPort backend. No source values or controls enter.

The trusted local process measures its execution; this is not remote computation
attestation. Q24 observations are raw model signals, not calibrated correctness.
"""

import json
import platform
import resource
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_backend import HEAD, ENCODER, features, inspect, prompt, sha
from native_tick_contract import validate_tick_binding


def run(raw):
    if len(raw) > 64 * 1024:
        raise ValueError("bounded request required")
    request = json.loads(raw)
    required = {
        "schema",
        "repo",
        "model",
        "checkpoint",
        "scope",
        "source_root",
        "rank",
        "seed",
        "pins",
        "question",
        "query_digest",
        "source_binding_digest",
        "neuron_request",
    }
    if request.get("schema") == "hepta.memory-cell.native-request.v2":
        required.add("tick_binding")
    if set(request) != required or request["schema"] not in {
        "hepta.memory-cell.native-request.v1",
        "hepta.memory-cell.native-request.v2",
    }:
        raise ValueError("closed request schema")
    expected_repo = Path(__file__).resolve().parents[2]
    if Path(request["repo"]).resolve() != expected_repo:
        raise ValueError("backend repository is fixed by its executable")
    if (
        not isinstance(request["scope"], str)
        or not 1 <= len(request["scope"].encode()) <= 128
        or any(ord(c) < 32 for c in request["scope"])
        or "<|" in request["scope"]
    ):
        raise ValueError("bounded scope")
    n = request["neuron_request"]
    fields = {
        "request_id",
        "config_id",
        "generation",
        "model_id",
        "encoder_digest",
        "head_digest",
        "weights_digest",
        "input_digest",
        "feature_vector_q24",
        "expected_output_width",
    }
    if set(n) != fields or n["feature_vector_q24"] != features(request["question"]):
        raise ValueError("actual query differs from native input features")
    if (
        n["encoder_digest"] != sha(ENCODER)
        or n["head_digest"] != sha(HEAD)
        or not 1 <= n["expected_output_width"] <= 32
    ):
        raise ValueError("unregistered query binding or observation profile")
    if request["schema"] == "hepta.memory-cell.native-request.v2":
        validate_tick_binding(request)
    elif n["input_digest"] != request["source_binding_digest"]:
        raise ValueError("source-bound v1 request changed")
    actual, evidence = inspect(request["repo"], request["model"], request["checkpoint"])
    if actual != request["pins"] or n["weights_digest"] != actual["weights_digest"]:
        raise ValueError("retained artifact/runtime pins differ from actual bytes")
    if (
        evidence["lineage"]["roots"] != [request["source_root"]]
        or evidence["lineage"]["scope"] != request["scope"]
    ):
        raise ValueError("single source root and scope must match the owner")
    sys.path.insert(0, str(expected_repo / "scripts/memory_cell"))
    import torch
    from parametric_model import SourceMemoryCell, adapter_digest
    from pretrained import frozen_digest

    torch.set_num_threads(2)
    started = time.perf_counter()
    cell = SourceMemoryCell(
        request["model"], rank=request["rank"], seed=request["seed"]
    )
    cell.load(
        request["checkpoint"],
        expected_manifest_sha256=actual["manifest_sha256"],
        scope=request["scope"],
        allowed_roots={request["source_root"]},
        revoked=set(),
    )
    if any(
        p.device.type != "cpu" or p.dtype != torch.float32
        for p in cell.reader.model.parameters()
    ):
        raise ValueError("CPU float32 profile required")
    adapter_before = adapter_digest(cell.reader.model)
    ids = cell.prompt_ids(request["question"])
    rendered = cell.reader.tokenizer.apply_chat_template(
        [
            {"role": "system", "content": __import__("parametric_model").SYSTEM},
            {
                "role": "user",
                "content": f"Scope: {request['scope']}\n{request['question']}",
            },
        ],
        tokenize=False,
        add_generation_prompt=True,
    )
    if (
        rendered != prompt(request["scope"], request["question"])
        or cell.reader.tokenizer.encode(rendered, add_special_tokens=False) != ids
    ):
        raise ValueError("actual tokenized prompt differs from the native template")
    with torch.no_grad():
        observed = cell.reader.model(
            input_ids=torch.tensor([ids], dtype=torch.long),
            output_hidden_states=True,
            use_cache=False,
        )
        width = n["expected_output_width"]
        drive = (
            (torch.tanh(observed.hidden_states[-1][0, -1, :width]) * (1 << 24))
            .round()
            .to(torch.int64)
            .tolist()
        )
        prediction = (
            (
                torch.softmax(observed.logits[0, -1].float(), dim=0).topk(width).values
                * (1 << 24)
            )
            .round()
            .to(torch.int64)
            .tolist()
        )
    del observed
    generated = cell.generate([request["question"]])[0]
    if (
        generated["prompt_token_ids"] != ids
        or generated["answer_postprocessed"] is not False
    ):
        raise ValueError("raw generation prompt changed")
    if adapter_before != adapter_digest(
        cell.reader.model
    ) or cell.reader.base_digest != frozen_digest(cell.reader.model):
        raise ValueError("model parameters changed during read")
    after, _ = inspect(request["repo"], request["model"], request["checkpoint"])
    if after != actual:
        raise ValueError("pinned files changed during read")
    return {
        "schema": "hepta.memory-cell.native-execution.v1",
        "request_sha256": sha(raw),
        "query_digest": request["query_digest"],
        "source_binding_digest": request["source_binding_digest"],
        "pins": actual,
        "question": request["question"],
        "prompt": rendered,
        "prompt_token_ids": ids,
        "generated_token_ids": generated["token_ids"],
        "text": generated["text"],
        "drive_q24": drive,
        "prediction_q24": prediction,
        "latency_micros": max(1, round((time.perf_counter() - started) * 1e6)),
        "resident_bytes": sum(
            p.numel() * p.element_size() for p in cell.reader.model.parameters()
        ),
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if platform.system() == "Darwin" else 1024),
        "resident_measurement": "model_parameter_bytes_excludes_allocator",
        "feature_forward_calls": 1,
        "decoder_queries": 1,
        "adapter_enabled": True,
        "answer_postprocessed": False,
        "facts_received": False,
        "retrieval_received": False,
        "base_unchanged": True,
        "adapter_unchanged": True,
    }


if __name__ == "__main__":
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    print(
        json.dumps(
            run(raw),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
