"""Small trainable memory operators with portable, fully counted parameters.

The text encoder is a fixed lexical hash map, not a pretrained language model.
Hidden and output weights are both trained. Serving exports contain no labels.
"""

import hashlib
import json
import time

import numpy as np


ARRAY_NAMES = ("head.bias", "head.weight", "hidden.bias", "hidden.weight")
ENCODER_PROFILE = "hepta.memory.lexical-hash-word-char.v12"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def features(texts, dimension=256):
    """Encode only the supplied text; no corpus identities or labels are read."""
    import re
    if not 1 <= dimension <= 384:
        raise ValueError("feature dimension outside native bound")
    result = np.zeros((len(texts), dimension), dtype=np.float32)
    for row, text in enumerate(texts):
        words = re.findall(r"[a-z0-9]+", text.lower())
        for word in words:
            tokens = [("w:" + word, 1.0)]
            padded = "^" + word + "$"
            tokens += [("c:" + padded[i:i + 3], 0.25)
                       for i in range(max(0, len(padded) - 2))]
            for token, weight in tokens:
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "little") % dimension
                result[row, index] += weight if digest[4] & 1 else -weight
        norm = float(np.linalg.norm(result[row]))
        if norm:
            result[row] /= norm
    return result


def parameter_digest(arrays):
    digest = hashlib.sha256()
    for name in ARRAY_NAMES:
        value = np.asarray(arrays[name], dtype="<f4", order="C")
        digest.update(canonical([name, list(value.shape), "float32"]))
        digest.update(value.tobytes())
    return digest.hexdigest()


class MLP:
    """A two-layer ReLU operator; optimizer state is separate from serving."""

    def __init__(self, arrays, receipt=None, optimizer=None):
        self.arrays = {name: np.array(arrays[name], dtype=np.float32, copy=True)
                       for name in ARRAY_NAMES}
        self.receipt = dict(receipt or {})
        self.optimizer = optimizer

    def predict(self, X):
        X = np.asarray(X, dtype=np.float32)
        a = self.arrays
        hidden = np.maximum(X @ a["hidden.weight"].T + a["hidden.bias"], 0)
        return hidden @ a["head.weight"].T + a["head.bias"]

    def export(self, include_optimizer=False):
        a = self.arrays
        result = dict(schema="hepta.memory.numpy-mlp.v12", activation="relu",
                      dimension=int(a["hidden.weight"].shape[1]),
                      hidden=int(a["hidden.weight"].shape[0]),
                      output=int(a["head.weight"].shape[0]),
                      arrays={name: dict(shape=list(value.shape),
                                         f32le_hex=value.astype("<f4").tobytes().hex())
                              for name, value in a.items()},
                      parameter_sha256=parameter_digest(a), receipt=self.receipt)
        if include_optimizer and self.optimizer is not None:
            result["optimizer"] = {
                "step": self.optimizer["step"],
                "moments": {name: {key: value.astype("<f4").tobytes().hex()
                                    for key, value in item.items()}
                            for name, item in self.optimizer["moments"].items()}}
        return result

    @classmethod
    def from_export(cls, payload):
        if payload.get("schema") != "hepta.memory.numpy-mlp.v12" or payload.get("activation") != "relu":
            raise ValueError("unsupported model schema or activation")
        d, h, o = (payload[k] for k in ("dimension", "hidden", "output"))
        if not (1 <= d <= 384 and 1 <= h <= 256 and 1 <= o <= 4096):
            raise ValueError("model shape bound")
        shapes = {"hidden.weight": [h, d], "hidden.bias": [h],
                  "head.weight": [o, h], "head.bias": [o]}
        if set(payload["arrays"]) != set(ARRAY_NAMES):
            raise ValueError("unexpected tensor inventory")
        arrays = {}
        for name, shape in shapes.items():
            item = payload["arrays"][name]
            if item["shape"] != shape:
                raise ValueError("tensor shape mismatch")
            value = np.frombuffer(bytes.fromhex(item["f32le_hex"]), dtype="<f4")
            if value.size != int(np.prod(shape)) or not np.isfinite(value).all():
                raise ValueError("invalid tensor bytes")
            arrays[name] = value.reshape(shape).copy()
        if parameter_digest(arrays) != payload["parameter_sha256"]:
            raise ValueError("parameter identity mismatch")
        optimizer = None
        if "optimizer" in payload:
            saved = payload["optimizer"]
            step = saved["step"]
            if type(step) is not int or not 0 <= step <= 100000000:
                raise ValueError("invalid optimizer step")
            if set(saved["moments"]) != set(ARRAY_NAMES):
                raise ValueError("invalid optimizer inventory")
            optimizer = {"step": step, "moments": {}}
            for name, shape in shapes.items():
                optimizer["moments"][name] = {}
                for key in ("m", "v"):
                    value = np.frombuffer(bytes.fromhex(saved["moments"][name][key]), dtype="<f4")
                    if value.size != int(np.prod(shape)) or not np.isfinite(value).all() or (key == "v" and (value < 0).any()):
                        raise ValueError("invalid optimizer bytes")
                    optimizer["moments"][name][key] = value.reshape(shape).copy()
        return cls(arrays, payload.get("receipt"), optimizer)


def train_mlp(X, Y, hidden=64, steps=600, seed=1, learning_rate=0.01,
              batch_size=32, initial=None):
    """Train actual hidden/head parameters; continuation retains Adam moments."""
    X, Y = np.asarray(X, dtype=np.float32), np.asarray(Y, dtype=np.float32)
    if X.ndim != 2 or Y.ndim != 2 or len(X) != len(Y) or not len(X):
        raise ValueError("nonempty aligned matrices required")
    if not np.isfinite(X).all() or not np.isfinite(Y).all() or (Y < 0).any() or (Y > 1).any():
        raise ValueError("finite features and probability targets required")
    if not (1 <= hidden <= 256 and 0 < steps <= 100000 and 0 < batch_size <= 4096):
        raise ValueError("training budget bound")
    rng = np.random.default_rng(seed)
    if initial is None:
        arrays = {"hidden.weight": (rng.standard_normal((hidden, X.shape[1])) * (2 / X.shape[1])**.5).astype(np.float32),
                  "hidden.bias": np.zeros(hidden, np.float32),
                  "head.weight": (rng.standard_normal((Y.shape[1], hidden)) / hidden**.5).astype(np.float32),
                  "head.bias": np.zeros(Y.shape[1], np.float32)}
        model = MLP(arrays)
    else:
        model = MLP.from_export(initial.export(include_optimizer=True))
        if model.arrays["hidden.weight"].shape != (hidden, X.shape[1]) or model.arrays["head.weight"].shape[0] != Y.shape[1]:
            raise ValueError("continuation shape mismatch")
    before = {name: value.copy() for name, value in model.arrays.items()}
    if model.optimizer is None:
        model.optimizer = {"step": 0, "moments": {name: {"m": np.zeros_like(value), "v": np.zeros_like(value)}
                                                  for name, value in model.arrays.items()}}
    start_step = model.optimizer["step"]
    wall, cpu = time.perf_counter(), time.process_time()
    schedule_hash = hashlib.sha256()
    gradient_max = {name: 0.0 for name in ARRAY_NAMES}
    trace = []
    a = model.arrays
    for step in range(steps):
        idx = rng.integers(0, len(X), size=batch_size)
        schedule_hash.update(idx.astype("<i8").tobytes())
        x, y = X[idx], Y[idx]
        pre = x @ a["hidden.weight"].T + a["hidden.bias"]
        h = np.maximum(pre, 0)
        logits = h @ a["head.weight"].T + a["head.bias"]
        probabilities = 1 / (1 + np.exp(-np.clip(logits, -60, 60)))
        delta = (probabilities - y) / y.size
        dh = (delta @ a["head.weight"]) * (pre > 0)
        gradients = {"head.weight": delta.T @ h, "head.bias": delta.sum(axis=0),
                     "hidden.weight": dh.T @ x, "hidden.bias": dh.sum(axis=0)}
        model.optimizer["step"] += 1
        t = model.optimizer["step"]
        for name, grad in gradients.items():
            if not np.isfinite(grad).all():
                raise FloatingPointError("nonfinite gradient")
            gradient_max[name] = max(gradient_max[name], float(np.linalg.norm(grad)))
            moment = model.optimizer["moments"][name]
            moment["m"] *= .9
            moment["m"] += .1 * grad
            moment["v"] *= .999
            moment["v"] += .001 * grad * grad
            a[name] -= learning_rate * (moment["m"] / (1 - .9**t)) / (np.sqrt(moment["v"] / (1 - .999**t)) + 1e-8)
        if step == 0 or (step + 1) % 100 == 0 or step + 1 == steps:
            loss = np.maximum(logits, 0) - logits * y + np.log1p(np.exp(-np.abs(logits)))
            trace.append(dict(step=step + 1, loss=float(loss.mean())))
    model.receipt = dict(seed=seed, steps=steps, initial_optimizer_step=start_step,
                         optimizer_step=model.optimizer["step"], batch_size=batch_size,
                         sample_presentations=steps * batch_size, observations=len(X),
                         schedule_sha256=schedule_hash.hexdigest(), learning_rate=learning_rate,
                         trainable_parameters=sum(x.size for x in a.values()),
                         parameter_bytes=sum(x.nbytes for x in a.values()),
                         optimizer_bytes=sum(v.nbytes for item in model.optimizer["moments"].values() for v in item.values()),
                         initial_parameter_sha256=parameter_digest(before),
                         final_parameter_sha256=parameter_digest(a),
                         max_gradient_norm=gradient_max,
                         parameter_change_norm={n: float(np.linalg.norm(a[n] - before[n])) for n in a},
                         trace=trace, fit_wall_seconds=time.perf_counter() - wall,
                         fit_cpu_seconds=time.process_time() - cpu)
    return model


def predict_export(payload, X):
    """Independent f64, left-to-right evaluator matching the native profile."""
    model = MLP.from_export(payload)
    a = {name: value.astype(np.float64) for name, value in model.arrays.items()}
    X = np.asarray(X, dtype=np.float64)
    h = np.broadcast_to(a["hidden.bias"], (len(X), payload["hidden"])).copy()
    for i in range(payload["dimension"]):
        h += X[:, i:i + 1] * a["hidden.weight"][:, i]
    np.maximum(h, 0, out=h)
    result = np.broadcast_to(a["head.bias"], (len(X), payload["output"])).copy()
    for i in range(payload["hidden"]):
        result += h[:, i:i + 1] * a["head.weight"][:, i]
    return result
