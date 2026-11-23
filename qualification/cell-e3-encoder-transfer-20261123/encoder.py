"""Shared third-party encoder and student score functions. No teacher code is imported."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer


def file_sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def normalized(x):
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-8)


class Encoder:
    def __init__(self, folder):
        self.info = json.loads((folder / "identity.json").read_bytes())
        for name, expect in self.info["files"].items():
            if file_sha(folder / name) != expect:
                raise ValueError(f"Changed encoder file {name}")
        self.tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True)
        self.model = AutoModel.from_pretrained(folder, local_files_only=True).eval()
        self.batches = 0
        self.presentations = 0
        self.input_tokens = 0
        self.parameter_count = sum(p.numel() for p in self.model.parameters())

    def embed(self, batch, pairs=False):
        result = []
        with torch.inference_mode():
            for i in range(0, len(batch), 32):
                part = batch[i:i + 32]
                args = list(zip(*part)) if pairs else [part]
                x = self.tokenizer(*args, padding=True, return_tensors="pt", truncation=False)
                mask = x["attention_mask"]
                if mask.shape[1] > 160:
                    raise ValueError("Encoder input bound exceeded")
                y = self.model(**x).last_hidden_state
                pooled = (y * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True)
                result.append(pooled.numpy())
                self.batches += 1
                self.presentations += len(part)
                self.input_tokens += int(mask.sum())
        return normalized(np.concatenate(result))

    def features(self, rows):
        qs = [r["query"] for r in rows]
        answers = [a for r in rows for a in r["candidates"]]
        q = self.embed(qs)
        a = self.embed(answers).reshape(len(rows), 2, -1)
        pairs = [(r["query"], a) for r in rows for a in r["candidates"]]
        joint = self.embed(pairs, pairs=True).reshape(len(rows), 2, -1)
        diff = a[:, 1, :] - a[:, 0, :]
        interactions = q * diff
        cosine_margin = interactions.sum(axis=1)
        x = normalized(np.concatenate((joint[:, 1] - joint[:, 0], diff,
                                      normalized(interactions)), axis=1))
        g = np.concatenate((q, np.ones((len(q), 1), dtype=np.float32)), axis=1)
        return x.astype(np.float64), g.astype(np.float64), cosine_margin.astype(np.float64)


def ridge(x, y):
    kernel = x @ x.T
    kernel.flat[::len(kernel) + 1] += 0.2
    return x.T @ np.linalg.solve(kernel, y)


def score(heads, policy, arm, rows, x, gate_features, cosine):
    def expert(name, indexes):
        out = cosine[indexes] + x[indexes] @ heads["parent"]
        if name != "parent":
            out += x[indexes] @ heads[name]
        return out

    if arm == "sparse":
        choice = np.where((gate_features @ heads["gate"]) > 0, "smol", "t5")
    elif arm == "fixed":
        choice = np.array([policy["fixed"].get(r["domain"], policy["best"]) for r in rows])
    else:
        actual = {"best_single": policy["best"], "without_t5": "smol",
                  "without_smol": "t5"}.get(arm, arm)
        choice = np.array([actual] * len(rows))
    margins = np.empty(len(rows))
    for name in np.unique(choice):
        ix = np.where(choice == name)[0]
        margins[ix] = expert(name, ix)
    return [{"id": r["id"], "answer": int(m > 0), "expert": str(n), "margin": float(m)}
            for r, m, n in zip(rows, margins, choice, strict=True)]
