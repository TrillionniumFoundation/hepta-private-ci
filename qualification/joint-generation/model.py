"""Small NumPy tensor model for a bounded text/image generation experiment.

The content encoder and both categorical heads are trained parameters. Pixel
outputs come from a learned decoder, never from the dataset renderer. This is
a finite-vocabulary qualification model, not a general multimodal foundation model.
"""

import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from utility import joint_value_and_grad


def softmax(logits):
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


class JointModel:
    """Shared tanh encoder, two content heads and a trainable pixel decoder."""

    def __init__(self, input_dim, classes, pixels, hidden=32, seed=0):
        dims = (input_dim, classes, pixels, hidden)
        if any(type(v) is not int or v < 1 or v > 65536 for v in dims):
            raise ValueError("invalid model dimensions")
        count = input_dim * hidden + hidden + 2 * hidden * classes + 2 * classes + classes * pixels + pixels
        if classes > 256 or hidden > 512 or count > 4_000_000:
            raise ValueError("model capacity exceeded")
        self.dimensions = dims
        rng = np.random.default_rng(seed)
        self.params = {
            "encoder": rng.normal(0, input_dim ** -0.5, (input_dim, hidden)),
            "bias": np.zeros(hidden),
            "text": rng.normal(0, hidden ** -0.5, (hidden, classes)),
            "text_bias": np.zeros(classes),
            "image": rng.normal(0, hidden ** -0.5, (hidden, classes)),
            "image_bias": np.zeros(classes),
            "decoder": rng.normal(0, 0.02, (classes, pixels)),
            "decoder_bias": np.zeros(pixels),
        }
        self._moments = {}
        self.updates = 0

    def _input(self, x):
        x = np.asarray(x, dtype=np.float64)
        if (x.ndim != 2 or not 1 <= len(x) <= 65536
                or x.shape[1] != self.dimensions[0] or not np.isfinite(x).all()):
            raise ValueError("invalid finite input matrix")
        return x

    def _forward(self, x):
        x = self._input(x)
        h = np.tanh(x @ self.params["encoder"] + self.params["bias"])
        pt = softmax(h @ self.params["text"] + self.params["text_bias"])
        pi = softmax(h @ self.params["image"] + self.params["image_bias"])
        return x, h, pt, pi

    def forward(self, x):
        """Read-only content inference; does not update parameters or optimizer."""
        _, _, pt, pi = self._forward(x)
        return pt, pi

    def gradients(self, x, dtext, dimage):
        x, h, pt, pi = self._forward(x)
        dt, di = np.asarray(dtext), np.asarray(dimage)
        if (dt.shape != pt.shape or di.shape != pi.shape
                or not np.isfinite(dt).all() or not np.isfinite(di).all()):
            raise ValueError("invalid logit gradients")
        dh = (dt @ self.params["text"].T + di @ self.params["image"].T) * (1 - h * h)
        return {
            "encoder": x.T @ dh, "bias": dh.sum(axis=0),
            "text": h.T @ dt, "text_bias": dt.sum(axis=0),
            "image": h.T @ di, "image_bias": di.sum(axis=0),
        }

    def apply_gradients(self, grads, lr):
        if not np.isfinite(lr) or not 0 < lr <= 1 or not grads:
            raise ValueError("invalid optimizer step")
        clean = {}
        for key, grad in grads.items():
            g = np.asarray(grad, dtype=np.float64)
            if key not in self.params or g.shape != self.params[key].shape or not np.isfinite(g).all():
                raise ValueError("invalid parameter gradient")
            clean[key] = g
        norm = np.sqrt(sum(float(np.sum(g * g)) for g in clean.values()))
        scale = min(1.0, 5.0 / max(norm, 1e-300))
        # Per-parameter clocks keep decoder and content training independent.
        for key, g in clean.items():
            m, v, step = self._moments.get(key, (np.zeros_like(g), np.zeros_like(g), 0))
            g = g * scale
            m, v, step = 0.9 * m + 0.1 * g, 0.999 * v + 0.001 * g * g, step + 1
            self.params[key] -= lr * (m / (1 - 0.9 ** step)) / (np.sqrt(v / (1 - 0.999 ** step)) + 1e-8)
            self._moments[key] = (m, v, step)
        self.updates += 1

    def train_step(self, x, dlogits_text, dlogits_image, lr=0.003):
        self.apply_gradients(self.gradients(x, dlogits_text, dlogits_image), lr)

    def supervised_step(self, x, labels, lr=0.003):
        pt, pi = self.forward(x)
        y = np.asarray(labels)
        if (y.shape != (len(pt),) or y.dtype.kind not in "iu"
                or np.any(y < 0) or np.any(y >= self.dimensions[1])):
            raise ValueError("invalid labels")
        rows = np.arange(len(y))
        loss = -np.mean(np.log(np.maximum(pt[rows, y], 1e-300))
                        + np.log(np.maximum(pi[rows, y], 1e-300))) / 2
        dt, di = pt.copy(), pi.copy()
        dt[rows, y] -= 1
        di[rows, y] -= 1
        self.train_step(x, dt / (2 * len(y)), di / (2 * len(y)), lr)
        return float(loss)

    def utility_step(self, x, rewards, rho=1.0, lr=0.003):
        """Maximize a fixed external joint utility; rho=0 is its additive case.

        Returns mean utility before the update. For rho>0 this uses the entropic
        certainty equivalent of the full joint content law, not separate rewards.
        """
        pt, pi = self.forward(x)
        utility, dt, di = joint_value_and_grad(pt, pi, rewards, rho)
        self.train_step(x, dt, di, lr)
        return float(utility.mean())

    def fit_decoder(self, target_pixels, steps=300, lr=0.05):
        target = np.asarray(target_pixels, dtype=np.float64)
        if (target.shape != (self.dimensions[1], self.dimensions[2])
                or not np.isfinite(target).all() or np.any(target < 0) or np.any(target > 1)
                or type(steps) is not int or not 1 <= steps <= 10000):
            raise ValueError("invalid decoder training data")
        for _ in range(steps):
            prediction = self.decode_images(np.arange(self.dimensions[1]))
            grad = (prediction - target) / target.size
            self.apply_gradients({"decoder": grad, "decoder_bias": grad.sum(axis=0)}, lr)
        return float(np.mean((self.decode_images(np.arange(self.dimensions[1])) - target) ** 2))

    def decode_images(self, class_ids):
        ids = np.asarray(class_ids)
        if (ids.ndim != 1 or not 1 <= len(ids) <= 65536 or ids.dtype.kind not in "iu"
                or np.any(ids < 0) or np.any(ids >= self.dimensions[1])):
            raise ValueError("invalid image content ids")
        logits = self.params["decoder"][ids] + self.params["decoder_bias"]
        return 1 / (1 + np.exp(-np.clip(logits, -700, 700)))

    def clone(self):
        out = JointModel(*self.dimensions[:3], hidden=self.dimensions[3])
        out.params = {name: value.copy() for name, value in self.params.items()}
        return out

    def digest(self):
        digest = hashlib.sha256(json.dumps(self.dimensions).encode())
        for key in sorted(self.params):
            digest.update(key.encode())
            digest.update(self.params[key].astype("<f8", copy=False).tobytes(order="C"))
        return digest.hexdigest()

    def save(self, path):
        """Write an inference-only bundle. Optimizer resume is intentionally separate."""
        np.savez_compressed(Path(path), dimensions=np.asarray(self.dimensions), **self.params)

    @classmethod
    def load(cls, path):
        if Path(path).stat().st_size > 32_000_000:
            raise ValueError("model bundle exceeds byte bound")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or sum(info.file_size for info in archive.infolist()) > 64_000_000:
                raise ValueError("invalid or oversized tensor inventory")
            dims = _read_tensor(archive, "dimensions", (4,), "integer")
            model = cls(*(int(v) for v in dims[:3]), hidden=int(dims[3]))
            if set(names) != {name + ".npy" for name in model.params} | {"dimensions.npy"}:
                raise ValueError("invalid tensor inventory")
            for name, template in model.params.items():
                model.params[name] = _read_tensor(archive, name, template.shape, "float64")
        return model


def _read_tensor(archive, name, expected_shape, profile):
    """Validate advertised NPY shape/dtype/bytes before allocating its array."""
    try:
        info = archive.getinfo(name + ".npy")
    except KeyError as error:
        raise ValueError("missing tensor") from error
    if info.file_size > 32_000_000:
        raise ValueError("tensor exceeds byte bound")
    with archive.open(info) as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ValueError("unsupported NPY version")
        valid_dtype = dtype == np.float64 if profile == "float64" else dtype.kind in "iu" and dtype.itemsize <= 8
        if shape != expected_shape or fortran or not valid_dtype:
            raise ValueError("invalid advertised tensor shape or dtype")
        if stream.tell() + int(np.prod(shape)) * dtype.itemsize != info.file_size:
            raise ValueError("invalid advertised tensor bytes")
    with archive.open(info) as stream:
        tensor = np.load(stream, allow_pickle=False)
    if not np.isfinite(tensor).all():
        raise ValueError("nonfinite tensor")
    return tensor
