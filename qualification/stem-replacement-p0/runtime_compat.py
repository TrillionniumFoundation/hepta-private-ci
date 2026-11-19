"""Dependency/shape compatibility smoke; never downloads or loads an original checkpoint.

Uses tiny, randomly initialized modules only to identify a bad *runtime API*
before scheduling 1.6+ GB pinned checkpoint downloads. Not a model benchmark.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from io import BytesIO
import json
import os
from pathlib import Path

AUTHORITY = "DENY_ALL"
SCHEMA = "hepta.stem.equal-size.runtime-compat.v1"


def require(value, reason):
    if not value:
        raise ValueError(reason)


def safe_tensor_roundtrip():
    import torch
    from physical_forward import safe_state_inventory

    net = torch.nn.Linear(8, 4)
    state = net.state_dict()
    require(type(state) is OrderedDict, "unexpected native PyTorch state_dict type")
    buf = BytesIO()
    torch.save(state, buf)
    buf.seek(0)
    saved = torch.load(buf, map_location="cpu", weights_only=True)
    require(type(saved) is OrderedDict, "unsafe/non-native weights-only state")
    count = safe_state_inventory(net, saved, torch)
    require(count == 36, "tiny state tensor count drift")
    net.load_state_dict(saved, strict=True, assign=True)
    net.eval()
    with torch.inference_mode():
        output = net(torch.ones((1, 8), dtype=torch.float32))
    require(output.shape == (1, 4) and bool(torch.isfinite(output).all()),
            "tiny native torch forward failed")
    return {"real_torch_weights_only_roundtrip": True, "actual_tiny_trainable_scalars": count,
            "torch_version": torch.__version__}


def modernbert_runtime_smoke():
    import torch
    from transformers import AutoModelForMaskedLM, ModernBertConfig
    from physical_forward import safe_state_inventory

    config = ModernBertConfig(hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                              num_attention_heads=4, vocab_size=128,
                              max_position_embeddings=128, local_attention=32,
                              global_attn_every_n_layers=2, pad_token_id=0,
                              bos_token_id=1, eos_token_id=2)
    require(config.model_type == "modernbert", "wrong architecture family")
    original = AutoModelForMaskedLM.from_config(config, trust_remote_code=False)
    weights = original.state_dict()
    buf = BytesIO()
    torch.save(weights, buf)
    del weights
    buf.seek(0)
    loaded = torch.load(buf, map_location="cpu", weights_only=True)
    require(safe_state_inventory(original, loaded, torch) > 0,
            "ModernBERT native checkpoint mismatch")
    second = AutoModelForMaskedLM.from_config(config, trust_remote_code=False)
    second.load_state_dict(loaded, strict=True, assign=True)
    second.eval()
    for param in second.parameters():
        param.requires_grad_(False)
    with torch.inference_mode():
        x = second.base_model(
            input_ids=torch.tensor([[1, 7, 8, 2]]),
            attention_mask=torch.ones((1, 4), dtype=torch.int64), return_dict=True,
        ).last_hidden_state
    require(tuple(x.shape) == (1, 4, 32) and bool(torch.isfinite(x).all()),
            "real CPU ModernBERT API/shape failure")
    return {"real_tiny_modernbert_forward": True,
            "real_ettin_weights_loaded": False, "pretrained_task_quality_verified": False}


def laya_installed_api_smoke():
    import inspect
    from importlib.metadata import version
    import laya
    require(version("laya") == "0.3.20", "Laya package changed")
    load = getattr(laya, "load", None)
    require(callable(load), "Laya.load native API unavailable")
    parameters = inspect.signature(load).parameters
    require(all(k in parameters for k in ("model_id_or_path", "device", "fast")),
            "native Laya 0.3.20 loader signature changed")
    return {"laya_package_version": "0.3.20", "laya_import_and_signature_valid": True,
            "real_laya_weights_loaded": False}


def source_contract():
    """No torch/transformers/laya imports, suitable for the light source CI."""
    require(SCHEMA.endswith("v1") and AUTHORITY == "DENY_ALL", "unsafe admission")
    return {"schema": SCHEMA, "authority": AUTHORITY,
            "original_model_weights_loaded": False,
            "real_pretrained_encoder_forward_verified": False,
            "publisher_signature_verified": False,
            "production_promotion_permitted": False,
            "physical_cell_split_permitted": False,
            "disposition": "HOLD_NO_GO"}


def run():
    a = source_contract()
    a["torch"] = safe_tensor_roundtrip()
    a["modernbert"] = modernbert_runtime_smoke()
    a["laya"] = laya_installed_api_smoke()
    return a


def main(argv=None):
    p=argparse.ArgumentParser(description="Tiny real torch/ModernBERT/Laya dependency smoke; no pretrained assets")
    p.add_argument("--out",required=True)
    args=p.parse_args(argv)
    record=run()
    out=Path(args.out)
    require(out.parent.is_dir() and not out.parent.is_symlink() and not out.exists(),
            "runtime smoke receipt requires a new ordinary path")
    data=(json.dumps(record,sort_keys=True,separators=(",", ":"),allow_nan=False)+"\n").encode()
    fd=os.open(out,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    print("tiny runtime compatibility: real Torch/ModernBERT CPU smoke, no pretrained model; DENY_ALL")


if __name__ == "__main__":
    main()
