"""Read-only CPU forward smoke for immutable Laya/Ettin research checkpoints.

This is not an equal-budget task comparison, training job, production loader,
signed issuer receipt, or authority source. No fallback/random checkpoint is used.
Ettin's legacy .bin is opened ONLY by torch.load(weights_only=True), never pickle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import tempfile
import time

from gate import AUTHORITY, MODELS, require
import preflight
import review_bytes
import source_bytes

SCHEMA = "hepta.stem.equal-size.physical-forward.v1"
MAX_PROBE_TOKENS = 128
PROBE_STATE = "The signed inventory report says the shipment reached the warehouse."
PROBE_QUERY = "Does the report support the claim that the shipment reached the warehouse?"
PROBE_OPTIONS = ("not_supported", "supported")
PROBE_TEXT = ("Evidence: " + PROBE_STATE + " Question: " + PROBE_QUERY
              + " Options: not_supported; supported")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _resource():
    # GitHub physical lane explicitly chooses Linux. On macOS ru_maxrss is bytes.
    return {"cpu_ns": time.process_time_ns(), "wall_ns": time.monotonic_ns(),
            "maxrss_kib_linux": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}


def checked_receipt(receipt, stage, expected_model):
    """Independent on-disk review always PRECEDES all imports of torch/laya."""
    require(expected_model in ("laya421", "ettin400"), "unsupported physical pilot model")
    require(type(receipt) is dict and receipt.get("model") == expected_model and
            receipt.get("authority") == AUTHORITY and receipt.get("disposition") == "HOLD_NO_GO" and
            receipt.get("selected_source_bytes_verified") is True and
            receipt.get("tensor_model_loaded") is False and
            receipt.get("real_model_forward_completed") is False and
            receipt.get("production_promotion_permitted") is False,
            "source receipt cannot authorize a physical model")
    repo, revision, _, _ = MODELS[expected_model]
    require(receipt.get("repo") == repo and receipt.get("revision") == revision,
            "actual checkpoint identity mismatch")
    proof = review_bytes.audit(receipt, stage)
    require(proof["independently_rehashed_exact_physical_bytes"] is True and
            proof["file_count"] == receipt["file_count"] and
            proof["total_bytes_rehashed"] > 0 and
            proof["production_promotion_permitted"] is False,
            "genuine source-byte verification incomplete")
    return proof


def safe_state_inventory(model, weights, torch):
    """Refuse all unknown tensor types, omitted, added or dimension-drifted keys."""
    require(type(weights) in (dict,) and 0 < len(weights) < 8192,
            "Ettin must be a bounded, plain weights-only tensor mapping")
    expected = model.state_dict()
    require(set(weights) == set(expected), "checkpoint/model named-tensor mismatch")
    total = 0
    for key, value in weights.items():
        require(type(key) is str and len(key) <= 256 and key in expected and
                type(value) is torch.Tensor and
                value.layout == torch.strided and value.device.type == "cpu" and
                value.dtype == expected[key].dtype and
                tuple(value.shape) == tuple(expected[key].shape) and value.numel() > 0,
                "unsafe or incompatible pretrained tensor")
        total += value.numel()
        require(total <= 650_000_000, "out-of-profile actual loaded tensor count")
    return total


def _ettin_forward(stage):
    import torch
    from transformers import AutoConfig, AutoModelForMaskedLM, AutoTokenizer

    root = str(stage)
    config = AutoConfig.from_pretrained(root, local_files_only=True, trust_remote_code=False)
    require(config.model_type == "modernbert", "unreviewed original Ettin architecture")
    # No AutoModel.from_pretrained(.bin), which could obscure pickle loading.
    net = AutoModelForMaskedLM.from_config(config, trust_remote_code=False)
    weights = torch.load(str(Path(stage) / "pytorch_model.bin"), map_location="cpu", weights_only=True)
    total = safe_state_inventory(net, weights, torch)
    net.load_state_dict(weights, strict=True, assign=True)
    del weights
    net.eval()
    for p in net.parameters():
        p.requires_grad_(False)
    tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True,
                                               trust_remote_code=False, use_fast=True)
    require(tokenizer.is_fast, "original Ettin tokenizer not registered fast profile")
    enc = tokenizer(PROBE_TEXT, add_special_tokens=True, truncation=True,
                    max_length=MAX_PROBE_TOKENS, return_tensors="pt")
    tokens = int(enc["input_ids"].numel())
    require(0 < tokens <= MAX_PROBE_TOKENS, "Ettin token budget violated")
    with torch.inference_mode():
        # Use the real trained base of the loaded MLM checkpoint, NOT a new head.
        actual = net.base_model(**enc, return_dict=True).last_hidden_state
        require(actual.ndim == 3 and actual.shape[0] == 1 and
                actual.shape[1] == tokens and actual.shape[2] == config.hidden_size,
                "Ettin actual hidden feature geometry drift")
        pooled = actual[0, 0, :].float().contiguous()
        require(bool(torch.isfinite(pooled).all()), "non-finite real Ettin feature")
    feature = pooled.numpy().tobytes()
    return {"output_type": "frozen_encoder_cls_fp32_sha256_not_decision_probability",
            "feature_sha256": _sha(feature), "feature_dimension": int(pooled.numel()),
            "actual_tensor_values_loaded": int(total), "input_tokens": tokens,
            "original_cpu_base_forward_calls": 1, "torch_pickle_loaded": False,
            "weights_only_loader_used": True,
            "actual_native_decision_probability": False}


def _laya_forward(stage):
    import laya
    import torch

    # Upstream laya==0.3.20 may rewrite incompatible tokenizer_config on load.
    # Protect the independently rehashed original by serving a private file COPY.
    with tempfile.TemporaryDirectory(prefix="hepta-laya-runtime-") as temp:
        runtime = Path(temp)
        for p in Path(stage).rglob("*"):
            if p.is_file() and not p.is_symlink() and ".cache" not in p.relative_to(stage).parts:
                out = runtime / p.relative_to(stage)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, out)
        cfg = runtime / "tokenizer/tokenizer_config.json"
        original = _sha(cfg.read_bytes()) if cfg.exists() else None
        agent = laya.load(str(runtime), device="cpu", fast=False)
        require(hasattr(agent, "model") and hasattr(agent.model, "encoder"),
                "native Laya model did not load")
        tensor_count = sum(int(p.numel()) for p in agent.model.parameters())
        require(360_000_000 <= tensor_count <= 500_000_000, "real Laya tensor inventory differs")
        probe = {"support": {"type": "noul", "instructions": PROBE_QUERY,
                             "criteria": {"false": PROBE_OPTIONS[0], "true": PROBE_OPTIONS[1]}}}
        calls = [0]
        hook = agent.model.encoder.register_forward_hook(lambda *unused: calls.__setitem__(0, calls[0] + 1))
        try:
            with torch.inference_mode():
                result = agent.predict(PROBE_STATE, probe, max_len=MAX_PROBE_TOKENS)
        finally:
            hook.remove()
        require(calls[0] == 1, "Laya native real encoder forward was not exactly once")
        require(type(result) is dict and type(result.get("answers")) is dict and
                type(result["answers"].get("support")) is dict and
                type(result.get("usage")) is dict, "incomplete Laya native result")
        answer = result["answers"]["support"]
        p = answer.get("noul")
        tokens = result["usage"].get("input_tokens")
        require(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 and
                type(tokens) is int and 0 < tokens <= MAX_PROBE_TOKENS,
                "Laya numerical decision or actual token count invalid")
        runtime_cfg = _sha(cfg.read_bytes()) if cfg.exists() else None
        return {"output_type": "native_laya_noul_probability_not_comparable_to_ettin_cls",
                "probability": float(p), "input_tokens": tokens,
                "original_cpu_base_forward_calls": calls[0],
                "actual_tensor_values_loaded": tensor_count,
                "runtime_tokenizer_config_modified": runtime_cfg != original,
                "runtime_tokenizer_config_sha256": runtime_cfg,
                "original_staged_tokenizer_was_not_modified": True,
                "torch_pickle_loaded": False, "weights_only_loader_used": False,
                "actual_native_decision_probability": True}


def run(model, receipt, stage):
    proof = checked_receipt(receipt, stage, model)
    before = _resource()
    result = _laya_forward(stage) if model == "laya421" else _ettin_forward(stage)
    after = _resource()
    require(result["original_cpu_base_forward_calls"] == 1 and
            result["actual_tensor_values_loaded"] > 0 and
            result["input_tokens"] > 0, "no physical model computation")
    return {"schema": SCHEMA, "model":model,
            "source_receipt_sha256":proof["source_sha256_receipt"],
            "source_weight_bytes_rehashed":proof["total_bytes_rehashed"],
            "output":result, "clock_wall_ns_self_reported":after["wall_ns"]-before["wall_ns"],
            "clock_cpu_ns_self_reported":after["cpu_ns"]-before["cpu_ns"],
            "peak_rss_kib_linux_self_reported":after["maxrss_kib_linux"],
            "real_forward_on_fixed_unlabeled_probe":True,
            "heldout_human_task_score":None,
            "equal_head_training_budget_verified":False,
            "two_arm_scientific_winner_verified":False,
            "publisher_signature_verified":False,
            "production_promotion_permitted":False, "authority":AUTHORITY,
            "disposition":"HOLD_NO_GO"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verified physical CPU frozen forward; NO model promotion")
    ap.add_argument("--model",choices=("ettin400","laya421"),required=True)
    ap.add_argument("--receipt",required=True)
    ap.add_argument("--stage",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args(argv)
    # Import and byte checks before any untrusted model code/data path.
    receipt=review_bytes.read_sealed(args.receipt)
    doc=run(args.model,receipt,Path(args.stage))
    source_bytes.write_new(args.out,doc)
    print(f"{args.model}: one physical pretrained CPU forward; no held task score; HOLD_NO_GO")


if __name__=="__main__":
    main()
