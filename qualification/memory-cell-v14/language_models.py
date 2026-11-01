"""Actual pretrained attention LoRA and strong source/feature baselines."""

import hashlib
import math
import re
import time
from collections import Counter
from collections.abc import Mapping

import numpy as np

from language_data import parse_key


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


class Baseline:
    def __init__(self, kind):
        self.kind = kind
        self.state = {}

    def fit(self, rows, sources, features, seed):
        start = time.perf_counter()
        self.labels = np.array([row["label"] for row in rows], dtype=np.int64)
        self.queries = [row["query"] for row in rows]
        if self.kind == "exact_kv":
            self.labels = np.empty(0, dtype=np.int64)
            self.queries = []
            self.state = {}
            for source in sources:
                label = re.search(r"\bvalue ([0-7])\b", source["text"])
                key = parse_key(source["text"])
                if label is None or key is None:
                    raise ValueError("Malformed source; no metadata fallback is permitted")
                self.state[key] = int(label.group(1))
        elif self.kind == "bm25":
            self.docs = [Counter(tokens(query)) for query in self.queries]
            self.lengths = np.array([sum(doc.values()) for doc in self.docs])
            self.average = float(self.lengths.mean())
            df = Counter(word for doc in self.docs for word in doc)
            self.idf = {word: math.log(1 + (len(self.docs) - count + .5) / (count + .5)) for word, count in df.items()}
        elif self.kind == "lexical_ridge":
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import RidgeClassifier
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))
            self.regressor = RidgeClassifier(alpha=1., solver="lsqr")
            self.regressor.fit(self.vectorizer.fit_transform(self.queries), self.labels)
        else:
            x = self.transform(features)
            targets = np.eye(8, dtype=np.float64)[self.labels]
            if self.kind == "feature_nearest":
                self.state = {"features": x}
            elif self.kind == "feature_ridge":
                regularizer = np.eye(x.shape[1]) * .01
                self.state = {"weights": np.linalg.solve(x.T @ x + regularizer, x.T @ targets)}
            elif self.kind == "fast_weights":
                weights = np.zeros((x.shape[1], 8), dtype=np.float64)
                rng = np.random.default_rng(seed)
                for _ in range(12):
                    for i in rng.permutation(len(x)):
                        error = targets[i] - x[i] @ weights
                        weights += .4 * np.outer(x[i], error) / max(float(x[i] @ x[i]), 1e-12)
                self.state = {"weights": weights}
            else:
                raise ValueError(self.kind)
        self.fit_seconds = time.perf_counter() - start
        return self

    @staticmethod
    def transform(features):
        x = np.asarray(features, dtype=np.float64)
        x = x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
        return np.concatenate((x, np.ones((len(x), 1))), axis=1)

    def predict(self, texts, features=None):
        if self.kind == "exact_kv":
            return np.array([self.state.get(parse_key(text), -1) for text in texts], dtype=np.int64)
        if self.kind == "lexical_ridge":
            return self.regressor.predict(self.vectorizer.transform(texts)).astype(np.int64)
        if self.kind == "bm25":
            output = []
            for text in texts:
                scores = np.zeros(len(self.docs))
                for word in set(tokens(text)):
                    count = np.array([doc[word] for doc in self.docs])
                    scores += self.idf.get(word, 0.) * count * 2.5 / (count + 1.5 * (.25 + .75 * self.lengths / self.average))
                output.append(int(self.labels[int(np.argmax(scores))]))
            return np.array(output, dtype=np.int64)
        x = self.transform(features)
        if self.kind == "feature_nearest":
            return self.labels[np.argmax(x @ self.state["features"].T, axis=1)]
        return np.argmax(x @ self.state["weights"], axis=1)


def tensor_hash(tensors):
    hasher = hashlib.sha256()
    for name, tensor in sorted(tensors.items()):
        hasher.update(name.encode())
        hasher.update(str(tuple(tensor.shape)).encode())
        hasher.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return hasher.hexdigest()


def frozen_hash(model):
    return tensor_hash({name.replace(".base.", "."): value for name, value in model.named_parameters() if not value.requires_grad})


def make_network(backbone, kind, seed):
    """Import torch only on an actual execution host; never substitute a fake LM."""
    import copy
    import torch
    from torch import nn
    torch.manual_seed(seed)

    class LoRALinear(nn.Module):
        def __init__(self, base):
            super().__init__()
            self.base = base
            self.a = nn.Parameter(torch.empty(4, base.in_features))
            self.b = nn.Parameter(torch.zeros(base.out_features, 4))
            nn.init.kaiming_uniform_(self.a, a=math.sqrt(5))
            self.enabled = True

        def forward(self, x):
            result = self.base(x)
            return result + (x @ self.a.T @ self.b.T) * 2. if self.enabled else result

    class Classifier(nn.Module):
        def __init__(self):
            super().__init__()
            self.kind = kind
            self.backbone = copy.deepcopy(backbone) if kind == "attention_lora" else None
            self.loras = []
            if self.backbone is not None:
                for layer in self.backbone.encoder.layer:
                    for name in ("query", "value"):
                        module = LoRALinear(getattr(layer.attention.self, name))
                        setattr(layer.attention.self, name, module)
                        self.loras.append(module)
            width = backbone.config.hidden_size
            # Keep the linear reader initialization identical across LoRA and
            # its frozen-feature control; LoRA initialization consumes RNG too.
            torch.manual_seed(seed)
            self.head = nn.Sequential(nn.Linear(width, 32), nn.GELU(), nn.Linear(32, 8)) if kind == "feature_mlp" else nn.Linear(width, 8)

        def forward(self, batch):
            if self.backbone is not None:
                # Frozen dropout rules are identical in training and evaluation.
                self.backbone.eval()
                features = self.backbone(**batch).last_hidden_state[:, 0]
            else:
                features = batch
            return self.head(features)

    network = Classifier()
    return network


def batch_inputs(inputs, index):
    """Accept tokenizer BatchEncoding and other mappings, as well as tensors."""
    return {key: value[index] for key, value in inputs.items()} if isinstance(inputs, Mapping) else inputs[index]


def train_network(network, optimizer, inputs, labels, steps, seed, batch_size=32):
    import torch
    generator = torch.Generator().manual_seed(seed)
    network.train()
    losses = []
    start = time.perf_counter()
    for step in range(steps):
        index = torch.randint(len(labels), (min(batch_size, len(labels)),), generator=generator)
        batch = batch_inputs(inputs, index)
        loss = torch.nn.functional.cross_entropy(network(batch), labels[index])
        if not torch.isfinite(loss):
            raise FloatingPointError("Non-finite training loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_([p for p in network.parameters() if p.requires_grad], 1.)
        optimizer.step()
        if step % 20 == 0 or step + 1 == steps:
            losses.append({"step": step + 1, "cross_entropy": float(loss.detach())})
    return {"training_seconds": time.perf_counter() - start, "optimizer_steps": steps, "losses": losses}


def predict_network(network, inputs, batch_size=64):
    import torch
    network.eval()
    n = len(next(iter(inputs.values()))) if isinstance(inputs, Mapping) else len(inputs)
    outputs = []
    with torch.inference_mode():
        for start in range(0, n, batch_size):
            batch = batch_inputs(inputs, slice(start, start + batch_size))
            outputs.append(network(batch).softmax(-1).cpu().numpy())
    probabilities = np.concatenate(outputs)
    return np.argmax(probabilities, axis=1), probabilities
