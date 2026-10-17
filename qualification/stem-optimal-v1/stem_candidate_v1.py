"""Source-frozen original public BANKING77 Stem candidate experiment.

The `prepare` operation is a MATERIAL-owner step; the `infer` operation receives
only the resulting train labels and label-free heldout text. Neither a checked
SHA nor a reported forward count is a trusted model issuer signature. Research only.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import resource
import time
import unicodedata

ORIGINAL_COMMIT = "57ec275d8078af65b7731c2a98be812d844a6d6b"
ORIGINAL_SHA = {
    "train": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
    "test": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
}
INTENTS = ("card_arrival", "cash_withdrawal_not_recognised", "exchange_rate", "lost_or_stolen_phone")
MODEL_NAMES = ("granite47", "granite97", "mmbert140")
DATA_SCHEMA = "hepta.stem.optimal.original-source.v1"
RUN_SCHEMA = "hepta.stem.optimal.physical-unattested.v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(item) -> bytes:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _parse_source(raw: bytes, expected: str):
    need(isinstance(raw, bytes) and 0 < len(raw) <= 2_000_000, "publisher size bound")
    need(sha256(raw) == expected and SHA.fullmatch(expected), "publisher data bytes mismatch")
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8", "strict")))
    need(rows.fieldnames == ["text", "category"], "publisher CSV columns mismatch")
    result = {}
    for idx, row in enumerate(rows):
        need(idx < 20_000 and set(row) == {"text", "category"}, "invalid publisher record")
        text, label = row["text"], row["category"]
        need(isinstance(text, str) and isinstance(label, str) and bool(text) and len(text.encode()) <= 4096, "invalid original sample")
        key = norm(text)
        need(bool(key), "empty normalized original")
        if key in result:
            need(result[key] == label, "conflicting original labels")
        result[key] = label
    return result


def _select(train, held):
    items = {"train": [], "heldout": []}
    for split, mapping, num in (("train", train, 16), ("heldout", held, 8)):
        for label_idx, intent in enumerate(INTENTS):
            pool = [text for text, label in mapping.items() if label == intent and (split == "train" or text not in train)]
            pool.sort(key=lambda s: sha256(("hepta-banking77-subset-v1\x00" + s).encode("utf-8")))
            need(len(pool) >= num, "incomplete original public class selection")
            for text in pool[:num]:
                cid = ("fit:" if split == "train" else "heldout:") + sha256(text.encode("utf-8"))
                base = {"case_id": cid, "source_sha256": sha256(text.encode("utf-8")), "text": text}
                if split == "train":
                    base["label"] = label_idx
                items[split].append(base)
    # Scramble source-first without labels; no case IDs or order encode heldout class.
    for split in items:
        items[split].sort(key=lambda x: sha256(("stem-optimal-order-v1\x00" + x["case_id"]).encode("utf-8")))
    return items


def prepare_original(train_bytes: bytes, test_bytes: bytes, *, hashes=ORIGINAL_SHA):
    need(set(hashes) == {"train", "test"}, "fixed publisher SHA manifest")
    train = _parse_source(train_bytes, hashes["train"])
    test = _parse_source(test_bytes, hashes["test"])
    selected = _select(train, test)
    need(len(selected["train"]) == 64 and len(selected["heldout"]) == 32, "fixed original cohort")
    need(all("label" not in x and "category" not in x for x in selected["heldout"]), "heldout label leakage")
    result = {
        "schema": DATA_SCHEMA, "publisher_revision": ORIGINAL_COMMIT,
        "publisher_sha256": hashes, "train": selected["train"], "heldout": selected["heldout"],
        "heldout_labels_excluded": True, "research_only": True, "production_authorized": False,
    }
    result["source_plan_sha256"] = sha256(canonical(result))
    return result


def verify_prepared(data):
    need(type(data) is dict and set(data) == {"schema", "publisher_revision", "publisher_sha256", "train", "heldout", "heldout_labels_excluded", "research_only", "production_authorized", "source_plan_sha256"}, "strict source envelope")
    need(data["schema"] == DATA_SCHEMA and data["publisher_revision"] == ORIGINAL_COMMIT, "source revision")
    need(data["publisher_sha256"] == ORIGINAL_SHA, "not the independently frozen original source")
    need(data["heldout_labels_excluded"] is True and data["research_only"] is True and data["production_authorized"] is False, "untrusted authority")
    need(len(data["train"]) == 64 and len(data["heldout"]) == 32, "cohort count")
    ids = set()
    for typ in ("train", "heldout"):
        for row in data[typ]:
            fields = {"case_id", "source_sha256", "text", "label"} if typ == "train" else {"case_id", "source_sha256", "text"}
            need(type(row) is dict and set(row) == fields, "unexpected source/heldout label field")
            need(isinstance(row["text"], str) and row["text"] == norm(row["text"]) and bool(row["text"]), "noncanonical text")
            csha = sha256(row["text"].encode("utf-8"))
            need(csha == row["source_sha256"] and row["case_id"] == ("fit:" if typ == "train" else "heldout:") + csha, "source identity mismatch")
            need(row["case_id"] not in ids, "duplicated/cross-leaked source")
            ids.add(row["case_id"])
            if typ == "train":
                need(type(row["label"]) is int and 0 <= row["label"] < len(INTENTS), "invalid training label")
    need(sha256(canonical({k: v for k, v in data.items() if k != "source_plan_sha256"})) == data["source_plan_sha256"], "changed source plan")


def load_materials(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    need(set(data) == {"schema", "precision", "preprocessing", "training", "candidates", "unresolved_controls", "research_only", "production_authorized"}, "exact material manifest")
    need(data["schema"] == "hepta.stem.original-candidate-model-material.v1", "material schema")
    need(data["research_only"] is True and data["production_authorized"] is False, "cannot grant authority")
    need(data["precision"] == "float32_cpu" and data["preprocessing"] == "tokenizer_native_trunc128_masked_mean_l2", "fixed forward profile")
    need(data["training"] == {"seed": 17, "steps": 100, "learning_rate": 0.006, "per_cell_parameters": 6914, "cells": 4}, "matched training budget")
    need(set(data["candidates"]) == set(MODEL_NAMES), "full candidate set")
    for k, spec in data["candidates"].items():
        need(type(spec) is dict and {"repo", "revision", "weight_file", "weight_sha256", "parameters_approx", "width", "license"}.issubset(spec), "material fields")
        need(GIT_SHA.fullmatch(spec["revision"]) is not None and SHA.fullmatch(spec["weight_sha256"]) is not None, "immutable model pin")
        need(spec["weight_file"] == "model.safetensors" and spec["width"] == 384, "fixed model profile")
        need(isinstance(spec["repo"], str) and "/" in spec["repo"] and all(c.isalnum() or c in "_-/ ." for c in spec["repo"]), "model repository path")
    return data


def _peak_rss_bytes():
    # Linux maxrss is KiB; GH ubuntu runners, not portable physical host evidence.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _material_model(spec):
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoTokenizer

    root = Path(snapshot_download(repo_id=spec["repo"], revision=spec["revision"],
                                  allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
                                  ignore_patterns=["*.bin", "*.pt", "*.h5", "*.onnx"], local_files_only=False))
    tensor_path = root / spec["weight_file"]
    need(tensor_path.is_file() and tensor_path.stat().st_size < 1_000_000_000, "missing or oversized pinned safetensors")
    # Xet/LFS pointer SHA is NOT evidence that the actual weight bytes were read.
    hasher = hashlib.sha256()
    with tensor_path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(block)
    need(hasher.hexdigest() == spec["weight_sha256"], "actual safetensors SHA mismatch; stop before loading")
    tok = AutoTokenizer.from_pretrained(str(root), trust_remote_code=False, local_files_only=True)
    mdl = AutoModel.from_pretrained(str(root), local_files_only=True, trust_remote_code=False,
                                    use_safetensors=True, torch_dtype=torch.float32)
    mdl.eval().to("cpu")
    # Do not call HF model's official sentence-transformers pooling: compare a controlled
    # masked-mean representation only. Native pooling is a separate required arm.
    return tok, mdl


def _encode(texts, tokenizer, model):
    import torch
    import torch.nn.functional as F

    parts = []
    calls = 0
    with torch.inference_mode():
        for start in range(0, len(texts), 16):
            tokens = tokenizer(texts[start:start+16], padding=True, truncation=True,
                               max_length=128, return_tensors="pt")
            output = model(**tokens).last_hidden_state.float()
            mask = tokens["attention_mask"].unsqueeze(-1).float()
            pooled = (output * mask).sum(1) / mask.sum(1).clamp_min(1.0)
            normalized = F.normalize(pooled, dim=-1)
            need(torch.isfinite(normalized).all().item(), "nonfinite real encoder output")
            parts.append(normalized.detach().cpu())
            calls += 1
    return torch.cat(parts).clone(), calls


def _torch_head_training(train_features, labels, test_features, *, config):
    import torch
    import torch.nn.functional as F

    torch.manual_seed(config["seed"])
    torch.use_deterministic_algorithms(True)

    class CellHeads(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.a = torch.nn.Parameter(torch.randn((4, 8, 384)) * 0.01)
            self.b = torch.nn.Parameter(torch.zeros((4, 384, 8)))
            self.gate = torch.nn.Parameter(torch.zeros((4, 384)))
            self.gate_bias = torch.nn.Parameter(torch.zeros((4,)))
            self.out = torch.nn.Parameter(torch.randn((4, 384)) * 0.01)
            self.out_bias = torch.nn.Parameter(torch.zeros((4,)))

        def forward(self, x):
            bottleneck = torch.einsum("bd,crd->bcr", x, self.a)
            residual = torch.einsum("bcr,cdr->bcd", bottleneck, self.b)
            gate = torch.sigmoid(torch.einsum("bd,cd->bc", x, self.gate) + self.gate_bias)
            y = x.unsqueeze(1) + gate.unsqueeze(-1) * residual / 8.0
            return (y * self.out.unsqueeze(0)).sum(-1) + self.out_bias

    heads = CellHeads()
    count = sum(p.numel() for p in heads.parameters())
    need(count == config["cells"] * config["per_cell_parameters"] == 27656, "wrong physical Head size")
    initial = copy.deepcopy(heads.state_dict())
    with torch.inference_mode():
        baseline = torch.softmax(heads(test_features), dim=-1).detach().cpu()
    optimizer = torch.optim.Adam(heads.parameters(), lr=config["learning_rate"])
    label_tensor = torch.tensor(labels, dtype=torch.long)
    train_start = time.perf_counter()
    for _ in range(config["steps"]):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(heads(train_features), label_tensor)
        need(torch.isfinite(loss).item(), "nonfinite training loss")
        loss.backward()
        optimizer.step()
    train_seconds = time.perf_counter() - train_start
    with torch.inference_mode():
        learned = torch.softmax(heads(test_features), dim=-1).detach().cpu()
        prototypes = torch.stack([train_features[label_tensor == c].mean(0) for c in range(4)])
        centroids = torch.softmax(test_features @ F.normalize(prototypes, dim=-1).T, dim=-1).cpu()
    final = heads.state_dict()
    def digest(sd):
        h = hashlib.sha256()
        for key, value in sorted(sd.items()):
            h.update(key.encode("ascii") + b"\x00")
            h.update(value.contiguous().detach().cpu().numpy().tobytes())
        return h.hexdigest()
    before, after = digest(initial), digest(final)
    need(before != after, "no physical Head learning")
    return {"frozen_init": baseline.tolist(), "learned": learned.tolist(),
            "centroid": centroids.tolist(), "initial_head_sha256": before,
            "trained_head_sha256": after, "steps": config["steps"],
            "total_head_parameters": count, "training_wall_seconds": train_seconds}


def run_inference(data, materials, candidate):
    verify_prepared(data)
    need(candidate in MODEL_NAMES and candidate in materials["candidates"], "unregistered candidate")
    spec = materials["candidates"][candidate]
    import torch
    torch.set_num_threads(2)
    t0 = time.perf_counter(); c0 = time.process_time()
    tok, model = _material_model(spec)
    load_wall = time.perf_counter() - t0
    encode_start = time.perf_counter()
    train_feat, train_forward_batches = _encode([r["text"] for r in data["train"]], tok, model)
    test_feat, test_forward_batches = _encode([r["text"] for r in data["heldout"]], tok, model)
    feature_wall = time.perf_counter() - encode_start
    need(train_feat.shape == (64, 384) and test_feat.shape == (32, 384), "unexpected original feature width")
    result = _torch_head_training(train_feat, [r["label"] for r in data["train"]], test_feat,
                                  config=materials["training"])
    outputs = []
    for n, row in enumerate(data["heldout"]):
        outputs.append({"case_id": row["case_id"], "source_sha256": row["source_sha256"],
                        "scores": {k: result[k][n] for k in ("frozen_init", "learned", "centroid")}})
    receipt = {"schema": RUN_SCHEMA, "candidate": candidate, "source_plan_sha256": data["source_plan_sha256"],
               "material_manifest_sha256": sha256(canonical(materials)), "model_repo": spec["repo"],
               "model_revision": spec["revision"], "actual_weight_sha256": spec["weight_sha256"],
               "head_parameters": result["total_head_parameters"], "optimizer_steps": result["steps"],
               "initial_head_sha256": result["initial_head_sha256"],
               "trained_head_sha256": result["trained_head_sha256"], "rows": outputs,
               "cost": {"encoder_forward_batches": train_forward_batches + test_forward_batches,
                        "physical_encoder_sequences": len(data["train"]) + len(data["heldout"]),
                        "elapsed_wall_seconds": time.perf_counter() - t0,
                        "elapsed_cpu_seconds": time.process_time() - c0,
                        "head_train_wall_seconds": result["training_wall_seconds"],
                        "model_download_load_wall_seconds": load_wall,
                        "feature_encode_wall_seconds": feature_wall,
                        "maxrss_bytes": _peak_rss_bytes(), "energy_joules": None, "p99_latency_ms": None},
               "physical_claim_unattested": True, "future_windows_verified": 0,
               "real_4096_cell_training_verified": False, "production_authorized": False,
               "disposition": "HOLD_NO_GO"}
    return receipt


def validate_receipt_shape(receipt, prepared, materials):
    verify_prepared(prepared)
    need(type(receipt) is dict and set(receipt) == {
        "schema", "candidate", "source_plan_sha256", "material_manifest_sha256", "model_repo", "model_revision",
        "actual_weight_sha256", "head_parameters", "optimizer_steps", "initial_head_sha256",
        "trained_head_sha256", "rows", "cost", "physical_claim_unattested", "future_windows_verified",
        "real_4096_cell_training_verified", "production_authorized", "disposition"}, "exact receipt fields")
    need(receipt["schema"] == RUN_SCHEMA and receipt["candidate"] in MODEL_NAMES, "unknown receipt schema/model")
    need(receipt["source_plan_sha256"] == prepared["source_plan_sha256"] and receipt["material_manifest_sha256"] == sha256(canonical(materials)), "unbound source/model manifest")
    spec = materials["candidates"][receipt["candidate"]]
    need((receipt["model_repo"], receipt["model_revision"], receipt["actual_weight_sha256"]) ==
         (spec["repo"], spec["revision"], spec["weight_sha256"]), "material substituted")
    need(receipt["head_parameters"] == 27656 and receipt["optimizer_steps"] == 100, "head budget mismatch")
    need(all(type(receipt[k]) is str and SHA.fullmatch(receipt[k]) for k in ("initial_head_sha256", "trained_head_sha256")) and receipt["initial_head_sha256"] != receipt["trained_head_sha256"], "head checkpoint invalid")
    need(receipt["physical_claim_unattested"] is True and receipt["future_windows_verified"] == 0 and receipt["real_4096_cell_training_verified"] is False and receipt["production_authorized"] is False and receipt["disposition"] == "HOLD_NO_GO", "promoted research source")
    need(type(receipt["rows"]) is list and len(receipt["rows"]) == 32, "invalid heldout universe")
    expected = {r["case_id"]: r["source_sha256"] for r in prepared["heldout"]}
    got = set()
    for row in receipt["rows"]:
        need(type(row) is dict and set(row) == {"case_id", "source_sha256", "scores"}, "unexpected/label-bearing prediction")
        need(row["case_id"] in expected and row["case_id"] not in got and row["source_sha256"] == expected[row["case_id"]], "missing/substituted/duplicate original case")
        got.add(row["case_id"])
        need(type(row["scores"]) is dict and set(row["scores"]) == {"frozen_init", "learned", "centroid"}, "incomplete controls")
        for arm in row["scores"].values():
            need(type(arm) is list and len(arm) == 4 and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in arm) and abs(sum(arm)-1) <= 1e-5, "invalid four-class probability")
    need(got == set(expected), "incomplete case coverage")
    c = receipt["cost"]
    need(type(c) is dict and set(c) == {"encoder_forward_batches", "physical_encoder_sequences", "elapsed_wall_seconds", "elapsed_cpu_seconds", "head_train_wall_seconds", "model_download_load_wall_seconds", "feature_encode_wall_seconds", "maxrss_bytes", "energy_joules", "p99_latency_ms"}, "missing full cost fields")
    need(type(c["encoder_forward_batches"]) is int and c["encoder_forward_batches"] == 6 and type(c["physical_encoder_sequences"]) is int and c["physical_encoder_sequences"] == 96, "not a bounded actual run shape")
    for k in ("elapsed_wall_seconds", "elapsed_cpu_seconds", "head_train_wall_seconds", "model_download_load_wall_seconds", "feature_encode_wall_seconds"):
        need(type(c[k]) in (int, float) and math.isfinite(c[k]) and c[k] >= 0, "invalid physical cost")
    need(type(c["maxrss_bytes"]) is int and c["maxrss_bytes"] > 0 and c["energy_joules"] is None and c["p99_latency_ms"] is None, "unqualified resource claim")


def _write_new(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as f:
        f.write(canonical(value) + b"\n")
        f.flush()
        os.fsync(f.fileno())
    return p


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--train", required=True)
    prepare.add_argument("--test", required=True)
    prepare.add_argument("--output", required=True)
    infer = sub.add_parser("infer")
    infer.add_argument("--source", required=True)
    infer.add_argument("--materials", required=True)
    infer.add_argument("--candidate", choices=MODEL_NAMES, required=True)
    infer.add_argument("--output", required=True)
    args = p.parse_args()
    if args.mode == "prepare":
        raw = {s: Path(getattr(args, s)).read_bytes() for s in ("train", "test")}
        result = prepare_original(raw["train"], raw["test"])
    else:
        result = run_inference(json.loads(Path(args.source).read_text(encoding="utf-8")),
                               load_materials(Path(args.materials)), args.candidate)
    path = _write_new(args.output, result)
    print(json.dumps({"mode": args.mode, "sha256": sha256(path.read_bytes()), "output": str(path),
                      "production_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
