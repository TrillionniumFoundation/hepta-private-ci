"""Small NumPy Cell heads with actual gradients and portable frozen artifacts.

Only shared features enter these heads. No Encoder weights, source retrieval,
or calibration labels enter training. Artifact hashes bind bytes, not external
source authenticity or production authority.
"""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_learning_metrics import probabilities


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def normalize_features(features):
    x = np.asarray(features, dtype=np.float64)
    if (x.ndim != 2 or not 1 <= len(x) <= 16384 or not 1 <= x.shape[1] <= 4096
            or x.size > 8_388_608 or not np.isfinite(x).all()):
        raise ValueError("bounded finite feature matrix required")
    norm = np.sqrt(np.square(x).sum(axis=1, keepdims=True))
    if not np.isfinite(norm).all():
        raise ValueError("feature magnitude exceeds normalization range")
    return x / np.maximum(norm, 1e-12) * np.sqrt(x.shape[1])


class NumpyCellHead:
    """Linear, feature-gated or gated residual readout with identical output shape."""

    def __init__(self, width, classes, mode="linear", rank=8, seed=7, max_parameters=100000):
        if (type(width) is not int or not 1 <= width <= 4096
                or type(classes) is not int or not 2 <= classes <= 256
                or mode not in ("linear", "gated", "residual")
                or type(rank) is not int or not 1 <= rank <= 32
                or type(seed) is not int or not 0 <= seed < 2**32
                or type(max_parameters) is not int or not 1 <= max_parameters <= 1_000_000):
            raise ValueError("invalid bounded head specification")
        self.width, self.classes, self.mode, self.rank = width, classes, mode, rank
        self.max_parameters = max_parameters
        self.feature_identity = None
        rng = np.random.default_rng(seed)
        self.params = {"W": rng.normal(0, 0.01 / np.sqrt(width), (width, classes)),
                       "b": np.zeros(classes)}
        if mode != "linear":
            self.params.update(a=np.zeros(width), g=np.zeros(width))
        if mode == "residual":
            self.params.update(V=rng.normal(0, 1 / np.sqrt(width), (width, rank)),
                               U=np.zeros((rank, width)))
        if self.parameter_count > max_parameters:
            raise ValueError("head exceeds the declared private parameter budget")
        self.report = {}

    def __getattr__(self, name):
        if name in ("W", "b", "a", "g", "V", "U") and name in self.params:
            return self.params[name]
        raise AttributeError(name)

    @property
    def parameter_count(self):
        return sum(value.size for value in self.params.values())

    @property
    def tensor_bytes(self):
        return sum(value.nbytes for value in self.params.values())

    def digest(self):
        result = hashlib.sha256(canonical([self.width, self.classes, self.mode, self.rank]))
        for name, value in sorted(self.params.items()):
            result.update(canonical([name, list(value.shape), value.dtype.str]))
            result.update(value.tobytes(order="C"))
        return result.hexdigest()

    def _forward(self, x):
        if x.shape[1] != self.width:
            raise ValueError("feature width differs from head")
        if any(not np.isfinite(p).all() for p in self.params.values()):
            raise ValueError("nonfinite head parameter")
        gate = hidden = None
        u = x
        if self.mode != "linear":
            argument = np.clip(x * self.a + self.g, -40, 40)
            gate = 1 / (1 + np.exp(-argument))
            u = x * gate
        if self.mode == "residual":
            hidden = np.tanh(x @ self.V)
            u = u + hidden @ self.U
        return u @ self.W + self.b, (u, gate, hidden)

    def predict_logits(self, features):
        result, _ = self._forward(normalize_features(features))
        if not np.isfinite(result).all():
            raise ValueError("nonfinite prediction")
        return result

    def predict_proba(self, features, temperature=1.0):
        return probabilities(self.predict_logits(features), temperature)

    def loss_gradients(self, x, y, l2=0.001):
        """Compute weighted cross-entropy gradients on already normalized input."""
        logits, (u, gate, hidden) = self._forward(x)
        p = probabilities(logits)
        counts = np.bincount(y, minlength=self.classes)
        weight = 1 / counts[y]
        weight /= weight.sum()
        loss = float(-(weight * np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1))).sum())
        delta = p.copy()
        delta[np.arange(len(y)), y] -= 1
        delta *= weight[:, None]
        gradient = {"W": u.T @ delta, "b": delta.sum(axis=0)}
        du = delta @ self.W.T
        if gate is not None:
            dg = du * x * gate * (1 - gate)
            # The forward sigmoid argument is clipped; saturated parameters
            # have a zero derivative through that clip.
            dg *= np.abs(x * self.a + self.g) < 40
            gradient.update(a=(dg * x).sum(axis=0), g=dg.sum(axis=0))
        if hidden is not None:
            gradient.update(U=hidden.T @ du,
                            V=x.T @ ((du @ self.U.T) * (1 - hidden**2)))
        for name in self.params:
            if name not in ("b", "g"):
                loss += 0.5 * l2 * float(np.square(self.params[name]).sum())
                gradient[name] += l2 * self.params[name]
        return loss, gradient

    def train(self, features, labels, *, steps=200, learning_rate=0.02, l2=0.001):
        if (type(steps) is not int or not 1 <= steps <= 5000
                or type(learning_rate) not in (int, float)
                or not np.isfinite(learning_rate) or not 0 < learning_rate <= 1
                or type(l2) not in (int, float) or not np.isfinite(l2) or not 0 <= l2 <= 1):
            raise ValueError("invalid bounded optimizer configuration")
        x, y = normalize_features(features), np.asarray(labels)
        if (y.shape != (len(x),) or y.dtype.kind not in "iu" or np.any(y < 0)
                or np.any(y >= self.classes) or len(np.unique(y)) != self.classes):
            raise ValueError("training needs valid labels and at least one row per class")
        began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
        before = self.digest()
        m = {k: np.zeros_like(v) for k, v in self.params.items()}
        v = {k: np.zeros_like(p) for k, p in self.params.items()}
        initial_loss = None
        for step in range(1, steps + 1):
            loss, gradient = self.loss_gradients(x, y, l2)
            if initial_loss is None:
                initial_loss = loss
            norm = np.sqrt(sum(float(np.square(g).sum()) for g in gradient.values()))
            if not np.isfinite(loss) or not np.isfinite(norm):
                raise ValueError("nonfinite optimization loss or gradients")
            clip = min(1.0, 5 / max(norm, 1e-12))
            for name in self.params:
                g = gradient[name] * clip
                m[name] = 0.9 * m[name] + 0.1 * g
                v[name] = 0.999 * v[name] + 0.001 * g * g
                corrected_m = m[name] / (1 - 0.9**step)
                corrected_v = v[name] / (1 - 0.999**step)
                self.params[name] -= learning_rate * corrected_m / (np.sqrt(corrected_v) + 1e-8)
        final_loss, _ = self.loss_gradients(x, y, l2)
        if any(not np.isfinite(p).all() for p in self.params.values()):
            raise ValueError("optimizer produced nonfinite parameters")
        self.report = {"initial_loss": initial_loss, "final_loss": final_loss,
                       "optimizer": "adam", "optimizer_steps": steps,
                       "training_rows": len(y), "example_updates": steps * len(y),
                       "learning_rate": learning_rate, "l2": l2,
                       "trainable_parameters": self.parameter_count,
                       "parameter_bytes": self.tensor_bytes, "optimizer_state_bytes": 2 * self.tensor_bytes,
                       "gradient_bytes": self.tensor_bytes,
                       "initial_tensor_sha256": before, "trained_tensor_sha256": self.digest(),
                       "wall_ns": time.perf_counter_ns() - began,
                       "cpu_ns": time.process_time_ns() - cpu_began,
                       "encoder_updates": 0, "class_reweighting": "inverse_training_frequency"}
        return dict(self.report)

    def save(self, directory, feature_identity):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=False)
        with (target / "weights.npz").open("xb") as stream:
            np.savez_compressed(stream, **self.params)
        manifest = {"schema": "hepta.numpy-cell-head.v1", "mode": self.mode,
                    "width": self.width, "classes": self.classes, "rank": self.rank,
                    "max_parameters": self.max_parameters,
                    "feature_identity": feature_identity, "tensor_sha256": self.digest(),
                    "weights_sha256": hashlib.sha256((target / "weights.npz").read_bytes()).hexdigest(),
                    "normalization": "l2_times_sqrt_width", "report": self.report}
        (target / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        self.feature_identity = json.loads(canonical(feature_identity))
        return manifest

    @classmethod
    def load(cls, directory, expected_feature_identity):
        target = Path(directory)
        manifest_path, weights_path = target / "manifest.json", target / "weights.npz"
        if (manifest_path.is_symlink() or weights_path.is_symlink()
                or manifest_path.stat().st_size > 131072 or weights_path.stat().st_size > 16 * 1024**2):
            raise ValueError("unsupported or oversized head artifact")
        manifest = json.loads(manifest_path.read_bytes())
        if (manifest.get("schema") != "hepta.numpy-cell-head.v1"
                or canonical(manifest.get("feature_identity")) != canonical(expected_feature_identity)
                or manifest.get("normalization") != "l2_times_sqrt_width"
                or hashlib.sha256(weights_path.read_bytes()).hexdigest() != manifest.get("weights_sha256")):
            raise ValueError("head identity or artifact hash mismatch")
        head = cls(manifest["width"], manifest["classes"], manifest["mode"], manifest["rank"],
                   max_parameters=manifest["max_parameters"])
        with np.load(weights_path, allow_pickle=False) as arrays:
            if set(arrays.files) != set(head.params):
                raise ValueError("unexpected head tensors")
            for name in head.params:
                value = arrays[name]
                if (value.shape != head.params[name].shape or value.dtype != np.float64
                        or not np.isfinite(value).all()):
                    raise ValueError("head tensor shape, precision or values differ")
                head.params[name] = value.copy()
        if head.digest() != manifest["tensor_sha256"]:
            raise ValueError("head tensor checksum mismatch")
        head.report = manifest["report"]
        head.feature_identity = json.loads(canonical(expected_feature_identity))
        return head
