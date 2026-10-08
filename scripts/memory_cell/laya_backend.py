"""Explicit pinned Laya tensor-model adaptation; never Agent.system_one JSON.

Loads only pre-staged reviewed source and safetensors. The local LoRA is on Laya's
actual scorer. It is not represented as full Transformer or production adoption.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file
from torch import nn
from transformers import AutoTokenizer

from pretrained import file_inventory

LAYA_COMMON_GIT_BLOB = "fb900053da691e18ff320d28d4664b46ab0d247f"


class LowRankScorer(nn.Module):
    def __init__(self, base: nn.Linear, rank: int = 4):
        super().__init__()
        self.base = base
        self.base.requires_grad_(False)
        self.a = nn.Parameter(torch.randn(rank, base.in_features) * 0.01)
        self.b = nn.Parameter(torch.zeros(base.out_features, rank))
        self.scale = 2.0

    def forward(self, inputs):
        return self.base(inputs) + (inputs @ self.a.T @ self.b.T) * self.scale


def train_and_measure(model_dir: Path, common_file: Path, pairs: list[dict], output: Path):
    source = common_file.read_bytes()
    header = f"blob {len(source)}\0".encode()
    if hashlib.sha1(header + source).hexdigest() != LAYA_COMMON_GIT_BLOB:
        raise ValueError("unreviewed Laya source")
    spec = importlib.util.spec_from_file_location("hepta_pinned_laya_common", common_file)
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    cfg = json.loads((model_dir / "rl_agent_config.json").read_text())
    model = common.build_model(cfg, str(model_dir / "encoder"))
    model.load_state_dict(load_file(str(model_dir / "model.safetensors")), strict=True)
    model.float().eval().requires_grad_(False)
    tokenizer = AutoTokenizer.from_pretrained(model_dir / "tokenizer", local_files_only=True, trust_remote_code=False)
    torch.manual_seed(8128)
    layer = LowRankScorer(model.scorer[-1])
    model.scorer[-1] = layer
    optimizer = torch.optim.AdamW([layer.a, layer.b], lr=0.001)
    train = [p for p in pairs if p["partition"] == "train"]
    test = [p for p in pairs if p["partition"] == "test"]
    if not train or not test or {p["family"] for p in train}.intersection(p["family"] for p in test):
        raise ValueError("Laya source-family leakage or missing partitions")
    def forward(pair):
        question = {"t": "choice", "ins": "Does this memory support answering: " + pair["question"],
                    "crit": {"no": "irrelevant or insufficient", "yes": "contains supporting evidence"}}
        ids, markers = common.build_sequence(tokenizer, pair["document"], question, max_len=192, head_max_len=96)
        if len(markers) != 2:
            raise ValueError("Laya incomplete candidate set")
        ids = torch.tensor([ids])
        return model(ids, torch.ones_like(ids), torch.tensor([markers]), torch.ones((1, 2), dtype=torch.bool), torch.tensor([0]))[0]
    started = time.perf_counter()
    before = []
    with torch.no_grad():
        for pair in test:
            before.append(forward(pair).softmax(-1)[0].tolist())
    losses = []
    for pair in train[:8]:
        optimizer.zero_grad(set_to_none=True)
        loss = nn.functional.cross_entropy(forward(pair), torch.tensor([pair["target"]]))
        if not torch.isfinite(loss):
            raise ValueError("Laya nonfinite loss")
        loss.backward()
        nn.utils.clip_grad_norm_([layer.a, layer.b], 1.0, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    if not torch.count_nonzero(layer.b).item():
        raise ValueError("Laya adapter did not learn")
    after = []
    with torch.no_grad():
        for pair in test:
            after.append(forward(pair).softmax(-1)[0].tolist())
    output.mkdir(parents=True, exist_ok=False)
    save_file({"a": layer.a.detach(), "b": layer.b.detach()}, str(output / "scorer-lora.safetensors"))
    report = {"schema": "hepta.laya-scorer-lora-observation.v1", "source_blob": LAYA_COMMON_GIT_BLOB,
              "base_inventory": file_inventory(model_dir), "steps": len(losses), "losses": losses,
              "trainable_parameters": layer.a.numel() + layer.b.numel(), "seconds": time.perf_counter() - started,
              "before": before, "after": after, "test_pairs": test,
              "profile": "real-pretrained-Laya-scorer-LoRA", "full_benchmark_score": False,
              "production_accepted": False}
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report
