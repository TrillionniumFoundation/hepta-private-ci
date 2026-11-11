"""Trainable residual low-rank adapter on frozen embeddings, not LLM LoRA.

The reference uses float64 parameters/Adam for numerical checking. Inputs can be
float32 pretrained embeddings. Checkpoints contain every causal training state;
wall-clock measurements are returned separately and are not model state.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import numpy as np


class Adapter:
    def __init__(self, input_dim=384, num_classes=2, rank=8, seed=0, encoder_hash="", source_version=""):
        if min(input_dim, num_classes, rank) < 1:
            raise ValueError("Adapter dimensions must be positive")
        self.config = dict(input_dim=input_dim, num_classes=num_classes, rank=rank, seed=seed)
        self.encoder_hash, self.source_version = encoder_hash, source_version
        self.rng = np.random.default_rng(seed)
        self.params = {
            "A": self.rng.normal(0, 0.03, (input_dim, rank)),
            "B": self.rng.normal(0, 0.01, (rank, input_dim)),
            "W": self.rng.normal(0, 0.03, (input_dim, num_classes)),
            "b": np.zeros(num_classes, dtype=np.float64),
        }
        self.m = {key: np.zeros_like(value) for key, value in self.params.items()}
        self.v = {key: np.zeros_like(value) for key, value in self.params.items()}
        self.step = 0
        self.sampler = dict(order=np.empty(0, dtype=np.int64), cursor=0, epoch=0, n=0, data_id="", fingerprint="")
        self.optimizer = dict(lr=0.01, batch_size=32, beta1=0.9, beta2=0.999, epsilon=1e-8)

    def _inputs(self, X):
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or X.shape[1] != self.config["input_dim"] or not np.isfinite(X).all():
            raise ValueError("Invalid adapter feature matrix")
        return X

    def features(self, X):
        X = self._inputs(X)
        return X + np.tanh(X @ self.params["A"]) @ self.params["B"]

    def predict_proba(self, X):
        logits = self.features(X) @ self.params["W"] + self.params["b"]
        logits -= logits.max(axis=1, keepdims=True)
        probability = np.exp(logits)
        return probability / probability.sum(axis=1, keepdims=True)

    def predict(self, X):
        return self.predict_proba(X).argmax(axis=1)

    def loss_and_grads(self, X, y):
        """Explicit cross-entropy reverse pass, exposed for independent FD checks."""
        X = self._inputs(X)
        y = np.asarray(y)
        if len(y) != len(X) or len(y) == 0 or y.ndim != 1 or not np.issubdtype(y.dtype, np.integer) or y.min() < 0 or y.max() >= self.config["num_classes"]:
            raise ValueError("Invalid class labels")
        Z = np.tanh(X @ self.params["A"])
        H = X + Z @ self.params["B"]
        logits = H @ self.params["W"] + self.params["b"]
        logits -= logits.max(axis=1, keepdims=True)
        exponentials = np.exp(logits)
        normalizer = exponentials.sum(axis=1, keepdims=True)
        loss = np.mean(np.log(normalizer[:, 0]) - logits[np.arange(len(y)), y])
        delta = exponentials / normalizer
        delta[np.arange(len(y)), y] -= 1
        delta /= len(y)
        hidden_grad = delta @ self.params["W"].T
        return float(loss), {
            "A": X.T @ ((hidden_grad @ self.params["B"].T) * (1 - Z * Z)),
            "B": Z.T @ hidden_grad,
            "W": H.T @ delta,
            "b": delta.sum(axis=0),
        }

    def train(self, X, y, *, steps=100, batch_size=None, lr=None, data_id, source_version, encoder_hash=None, allow_data_change=False):
        started = time.perf_counter()
        batch_size = self.optimizer["batch_size"] if batch_size is None else batch_size
        lr = self.optimizer["lr"] if lr is None else lr
        X = self._inputs(X)
        y = np.asarray(y)
        if steps < 0 or batch_size < 1 or lr <= 0 or not np.isfinite(lr) or not data_id or not source_version:
            raise ValueError("Invalid training schedule or source identity")
        if y.ndim != 1 or len(y) != len(X) or len(y) == 0 or not np.issubdtype(y.dtype, np.integer) or y.min() < 0 or y.max() >= self.config["num_classes"]:
            raise ValueError("Invalid training labels")
        if encoder_hash is not None and encoder_hash != self.encoder_hash:
            raise ValueError("Training encoder identity mismatch")
        digest = hashlib.sha256()
        digest.update(json.dumps([X.shape, y.shape], separators=(",", ":")).encode())
        digest.update(np.ascontiguousarray(X, dtype="<f8").tobytes())
        digest.update(np.ascontiguousarray(y, dtype="<i8").tobytes())
        fingerprint = digest.hexdigest()
        changed = (self.sampler["fingerprint"] != fingerprint or self.sampler["data_id"] != data_id or self.source_version != source_version)
        if changed:
            established = self.sampler["n"] > 0 or (self.source_version and self.source_version != source_version)
            if established and not allow_data_change:
                raise ValueError("Dataset/source changed: explicit allow_data_change required")
            self.sampler = dict(order=self.rng.permutation(len(X)), cursor=0, epoch=0, n=len(X), data_id=data_id, fingerprint=fingerprint)
            self.source_version = source_version
        self.optimizer.update(lr=lr, batch_size=batch_size)
        losses = []
        examples = 0
        for _ in range(steps):
            if self.sampler["cursor"] == len(X):
                self.sampler["order"] = self.rng.permutation(len(X))
                self.sampler["cursor"] = 0
                self.sampler["epoch"] += 1
            begin = self.sampler["cursor"]
            ids = self.sampler["order"][begin:begin + batch_size]
            loss, gradients = self.loss_and_grads(X[ids], y[ids])
            t = self.step + 1
            updates, moments, variances = {}, {}, {}
            for name, gradient in gradients.items():
                moments[name] = 0.9 * self.m[name] + 0.1 * gradient
                variances[name] = 0.999 * self.v[name] + 0.001 * gradient * gradient
                updates[name] = self.params[name] - lr * (moments[name] / (1 - 0.9**t)) / (np.sqrt(variances[name] / (1 - 0.999**t)) + 1e-8)
                if not np.isfinite(updates[name]).all():
                    raise FloatingPointError("Non-finite Adam update; no weights published")
            self.params, self.m, self.v, self.step = updates, moments, variances, t
            self.sampler["cursor"] += len(ids)
            examples += len(ids)
            losses.append(loss)
        return dict(updates=steps, examples=examples, seconds=time.perf_counter() - started, first_loss=losses[0] if losses else None, last_loss=losses[-1] if losses else None, mean_loss=float(np.mean(losses)) if losses else None, step=self.step)

    def state_dict(self):
        return copy.deepcopy(dict(schema="hepta-residual-tanh-adam-v1", config=self.config, encoder_hash=self.encoder_hash, source_version=self.source_version, params=self.params, m=self.m, v=self.v, step=self.step, rng_state=self.rng.bit_generator.state, sampler=self.sampler, optimizer=self.optimizer))

    def clone(self):
        return copy.deepcopy(self)

    def _serialized(self):
        metadata = self.state_dict()
        arrays = {}
        for group in ("params", "m", "v"):
            for key, value in metadata.pop(group).items():
                arrays[f"{group}_{key}"] = value
        arrays["sampler_order"] = metadata["sampler"].pop("order")
        arrays["metadata"] = np.frombuffer(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode(), dtype=np.uint8)
        return arrays

    def state_hash(self):
        digest = hashlib.sha256()
        for name, value in sorted(self._serialized().items()):
            digest.update(name.encode() + b"\0" + str(value.dtype).encode() + b"\0")
            digest.update(json.dumps(value.shape).encode() + np.ascontiguousarray(value).tobytes())
        return digest.hexdigest()

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as stream:
            temporary = stream.name
            np.savez_compressed(stream, **self._serialized())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    @classmethod
    def load(cls, path, *, expected_encoder_hash=None, expected_source_version=None, expected_data_id=None):
        with np.load(path, allow_pickle=False) as saved:
            metadata = json.loads(saved["metadata"].tobytes())
            if metadata.get("schema") != "hepta-residual-tanh-adam-v1":
                raise ValueError("Unsupported adapter checkpoint schema")
            for key, expected in (("encoder_hash", expected_encoder_hash), ("source_version", expected_source_version)):
                if expected is not None and metadata[key] != expected:
                    raise ValueError(f"Checkpoint {key} mismatch")
            if expected_data_id is not None and metadata["sampler"]["data_id"] != expected_data_id:
                raise ValueError("Checkpoint data_id mismatch")
            result = cls(**metadata["config"], encoder_hash=metadata["encoder_hash"], source_version=metadata["source_version"])
            for group in ("params", "m", "v"):
                loaded = {}
                for name, template in getattr(result, group).items():
                    value = saved[f"{group}_{name}"].copy()
                    if value.dtype != np.float64 or value.shape != template.shape or not np.isfinite(value).all() or (group == "v" and (value < 0).any()):
                        raise ValueError("Invalid checkpoint parameter/optimizer array")
                    loaded[name] = value
                setattr(result, group, loaded)
            result.step, result.optimizer = metadata["step"], metadata["optimizer"]
            result.rng.bit_generator.state = metadata["rng_state"]
            result.sampler = metadata["sampler"]
            result.sampler["order"] = saved["sampler_order"].copy()
        sampler = result.sampler
        if result.step < 0 or sampler["order"].dtype != np.int64 or not 0 <= sampler["cursor"] <= sampler["n"] or not np.array_equal(np.sort(sampler["order"]), np.arange(sampler["n"])):
            raise ValueError("Invalid checkpoint sampler/step")
        if any(result.optimizer[key] != value for key, value in (("beta1", 0.9), ("beta2", 0.999), ("epsilon", 1e-8))):
            raise ValueError("Unsupported checkpoint optimizer semantics")
        if result.optimizer["batch_size"] < 1 or result.optimizer["lr"] <= 0 or not np.isfinite(result.optimizer["lr"]):
            raise ValueError("Invalid checkpoint optimizer schedule")
        return result
