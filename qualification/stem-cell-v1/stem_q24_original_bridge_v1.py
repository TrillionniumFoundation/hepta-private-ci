#!/usr/bin/env python3
"""Original public Encoder -> train-only PCA -> bounded 32D Q24 -> 4-cell research Head.

Research only; DENY_ALL. This file MUST NOT be used as native Neuron V1 evidence.
No generated/source vectors or raw targets may be uploaded as public artifacts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

Q = 1 << 24
D = 32
H = 8 * Q
MODEL_REV = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
DATA_REV = "57ec275d8078af65b7731c2a98be812d844a6d6b"


def need(valid, message):
    if not valid:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(data, f, sort_keys=True, allow_nan=False)
        f.write("\n")


def read(path):
    def unique(pairs):
        d = {}
        for k, v in pairs:
            need(k not in d, "duplicate JSON key")
            d[k] = v
        return d
    def finite(s):
        f = float(s)
        need(math.isfinite(f), "nonfinite JSON numeric field")
        return f
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and p.stat().st_size < 10000000, "unsafe source")
    return json.loads(p.read_bytes(), object_pairs_hook=unique, parse_float=finite,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError("nonfinite constant")))


def fit_only_pca(fit):
    """No labels, HELD features or HELD source may enter this method."""
    x = np.asarray(fit, dtype=np.float64)
    need(x.ndim == 2 and x.shape[0] == 64 and D <= x.shape[1] <= 8192
         and np.isfinite(x).all(), "unbounded or nonfinite train features")
    mean = x.mean(0)
    _, singular, vt = np.linalg.svd(x - mean, full_matrices=False)
    need(singular[D - 1] > 1e-9, "TRAIN-only PCA is rank deficient")
    axes = vt[:D].T.copy()
    for i in range(D):
        largest = np.argmax(np.abs(axes[:, i]))
        if axes[largest, i] < 0:
            axes[:, i] *= -1
    scale = max(1.0, float(np.abs((x - mean) @ axes).max()) / 4.0)
    return mean, axes, scale


def q24(x, mean, axes, scale):
    x = np.asarray(x, dtype=np.float64)
    need(x.ndim == 2 and x.shape[1] == len(mean) and np.isfinite(x).all(),
         "wrong original Encoder width or nonfinite vector")
    raw = np.rint(((x - mean) @ axes) / scale * Q)
    need(raw.shape[1] == D and np.isfinite(raw).all(), "invalid projected Q24")
    return np.clip(raw, -H, H).astype(np.int64), int((raw != np.clip(raw, -H, H)).sum())


def encode(backend, inputs):
    import torch
    from banking77_material import INTENTS
    from public_cell_learning import validate_inputs
    validate_inputs(inputs)
    need(len(inputs["fit"]) == 64 and len(inputs["heldout"]) == 32,
         "must keep all 64 FIT and 32 HELD public source cases")
    need(all(set(r) == {"id", "text"} for r in inputs["heldout"]),
         "HELD labels cannot enter Encoder or Cell training")
    before = backend.calls
    rows, counts = {}, {}
    for split in ("fit", "heldout"):
        features, token_counts = [], []
        for r in inputs[split]:
            vector, tokens = backend.encode({"state": r["text"],
                "question": "Select the customer service intent.", "options": list(INTENTS)})
            need(isinstance(vector, torch.Tensor) and vector.dtype == torch.float32
                 and vector.device.type == "cpu" and not vector.requires_grad
                 and vector.ndim == 1 and torch.isfinite(vector).all().item()
                 and type(tokens) is int and 0 < tokens <= 256,
                 "invalid original pretrained model forward")
            features.append(vector.detach().numpy().copy())
            token_counts.append(tokens)
        rows[split] = np.stack(features)
        counts[split] = token_counts
    need(backend.calls - before == 96, "actual original 96-Encoder-forward census missing")
    backend.reverify()
    return rows, counts


def cells(fit, held, labels, *, steps=64, seed=7347):
    import copy
    import torch
    from safetensors.torch import save_file
    need(type(steps) is int and 1 <= steps <= 128 and type(seed) is int and seed >= 0,
         "unbounded training budget")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    class Head(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.linear_weight = torch.nn.Parameter(torch.randn(4, 32) * .02)
            self.linear_bias = torch.nn.Parameter(torch.zeros(4))
            self.gate_weight = torch.nn.Parameter(torch.zeros(4, 32))
            self.gate_bias = torch.nn.Parameter(torch.zeros(4))
        def forward(self, x):
            return ((x @ self.linear_weight.T + self.linear_bias)
                    * torch.sigmoid(x @ self.gate_weight.T + self.gate_bias))
    x, z = (torch.tensor(v.astype(np.float32) / Q) for v in (fit, held))
    y = torch.tensor(labels, dtype=torch.long)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        initial = Head()
    def tensors(model):
        return {k: v.detach().cpu().contiguous().float()
                for k, v in model.state_dict().items()}
    result = {"initial": (tensors(initial), initial(z).detach().tolist(), 0)}
    for arm, targets in (("learned", y), ("cyclic_wrong_labels", (y + 1) % 4)):
        model = copy.deepcopy(initial)
        opt = torch.optim.AdamW(model.parameters(), lr=.03, weight_decay=0)
        for _ in range(steps):
            loss = torch.nn.functional.cross_entropy(model(x), targets)
            need(torch.isfinite(loss).item(), "nonfinite TRAIN loss")
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
            opt.step()
        t = tensors(model)
        need(sum(v.numel() for v in t.values()) == 264
             and all(torch.isfinite(v).all().item() for v in t.values()),
             "invalid actual independent Cell parameter count")
        result[arm] = (t, model(z).detach().tolist(), steps)
    return result


def produce(inputs, backend, output, *, steps=64, source_class="FIXTURE"):
    from safetensors.numpy import save_file
    from safetensors.torch import save_file as save_torch
    from public_cell_learning import validate_inputs
    validate_inputs(inputs)
    need(source_class in ("FIXTURE", "ORIGINAL_PUBLIC_MODERNBERT"), "unsafe source class")
    if source_class == "ORIGINAL_PUBLIC_MODERNBERT":
        receipt = backend.receipt
        need(receipt["upstream_revision"] == MODEL_REV
             and receipt["complete_checkpoint"]["loading"]["complete"] is True
             and receipt["complete_checkpoint"]["materialization"]["all_state_dict_tensors_accounted"] is True,
             "actual original pretrained tensors have not been admitted")
    root = Path(output)
    root.mkdir(exist_ok=False)
    started = time.process_time()
    raw, tokens = encode(backend, inputs)
    cpu = time.process_time() - started
    mean, axes, scale = fit_only_pca(raw["fit"])
    a, train_clipped = q24(raw["fit"], mean, axes, scale)
    b, held_clipped = q24(raw["heldout"], mean, axes, scale)
    need(a.shape == (64, 32) and b.shape == (32, 32), "wrong source population")
    save_file({"fit": raw["fit"], "heldout": raw["heldout"]}, root / "private-raw.safetensors")
    save_file({"mean": mean, "axes": axes, "scale": np.array([scale])}, root / "private-pca.safetensors")
    private = {"input_id": inputs["input_id"],
               "fit": [{"id": r["id"], "label": r["label"], "feature_q24": v.tolist()}
                       for r, v in zip(inputs["fit"], a, strict=True)],
               "heldout": [{"id": r["id"], "feature_q24": v.tolist()}
                           for r, v in zip(inputs["heldout"], b, strict=True)]}
    write(root / "private-q24.json", private)
    models = cells(a, b, [r["label"] for r in inputs["fit"]], steps=steps)
    pred = {"input_id": inputs["input_id"],
            "heldout_ids": [r["id"] for r in inputs["heldout"]],
            "arms": {k: v[1] for k, v in models.items()}}
    write(root / "private-predictions.json", pred)
    for name, (weights, _, _) in models.items():
        save_torch(weights, root / (name + ".safetensors"))
    names = ("private-raw.safetensors", "private-pca.safetensors", "private-q24.json",
             "private-predictions.json", "initial.safetensors", "learned.safetensors",
             "cyclic_wrong_labels.safetensors")
    report = {"schema": "hepta.stem-original-q24-bridge.v1", "input_id": inputs["input_id"],
              "source_class": source_class, "model_snapshot_sha256": backend.receipt.get("snapshot_sha256"),
              "model_revision": MODEL_REV if source_class == "ORIGINAL_PUBLIC_MODERNBERT" else None,
              "encoder_forward_count": 96, "encoder_cpu_seconds": cpu,
              "hidden_dimension": raw["fit"].shape[1], "feature_dimension": 32,
              "train_only_pca": True, "Q24": Q, "clip_count": [train_clipped, held_clipped],
              "steps": steps, "cell_params_each_arm": 264,
              "original_tokens_sha256": hashlib.sha256(
                  json.dumps(tokens, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "private_files": {name: sha(root / name) for name in names},
              "heldout_targets_used_in_training": False,
              "pretrained_issuer_independently_verified": False,
              "native_q24_cell_executed": False, "future_utility_verified": False,
              "production_authorized": False, "authority": "DENY_ALL"}
    write(root / "PRODUCER.json", report)
    return report


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="mode", required=True)
    a = sp.add_parser("stage")
    a.add_argument("--output", required=True)
    b = sp.add_parser("produce")
    b.add_argument("--inputs", required=True)
    b.add_argument("--public-probe", required=True)
    b.add_argument("--output", required=True)
    args = p.parse_args()
    if args.mode == "stage":
        from banking77_material import acquire, prepare, REVISION
        need(REVISION == DATA_REV, "original dataset revision changed")
        root = Path(args.output)
        root.mkdir(exist_ok=False)
        data = acquire(root / "original-source")
        inputs, observer, selection = prepare(
            (data / "banking_data/train.csv").read_bytes(),
            (data / "banking_data/test.csv").read_bytes())
        write(root / "producer-inputs.json", inputs)
        write(root / "observer-labels.json", observer)
        write(root / "selection.json", selection)
        return
    from matrix_runtime import LocalHFEncoder
    from hf_encoder_kernel import snapshot_digest
    from hf_complete_checkpoint import ENCODER_PROFILE
    from public_encoder_probe import MODEL_ID
    from matrix_materials import file_sha256
    need(MODEL_ID == "answerdotai/ModernBERT-base", "wrong original model")
    public = Path(args.public_probe)
    lock, material = read(public / "source-lock.json"), read(public / "downloaded-material.json")
    need(lock["model_id"] == MODEL_ID and lock["upstream_revision"] == MODEL_REV
         and material["source_lock_sha256"] == file_sha256(public / "source-lock.json"),
         "unpinned public original checkpoint")
    snapshot = public / "snapshot"
    need(snapshot_digest(snapshot) == material["snapshot_sha256"], "drifted material")
    encoder = LocalHFEncoder(snapshot, {
        "snapshot_sha256": material["snapshot_sha256"], "context_tokens": 256,
        "encoder_profile": ENCODER_PROFILE, "upstream_revision": MODEL_REV,
        "material_approval_sha256": None}, {"stem": "smaller_control"})
    produce(read(args.inputs), encoder, args.output, source_class="ORIGINAL_PUBLIC_MODERNBERT")


if __name__ == "__main__":
    main()
