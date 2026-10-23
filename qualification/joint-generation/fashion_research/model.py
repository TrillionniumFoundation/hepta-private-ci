"""Shared continuous-pixel model and small actor; no dataset access or runner."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

from fashion_research.autodiff import Tensor, concatenate, posterior


MODULES = {
    "C": (784, 64), "T_initial": (64, 32), "I_initial": (82, 16),
    "text_head": (32, 10), "image_head": (16, 16), "qT": (42, 16),
    "qI": (48, 16), "feedback": (96, 32), "T_update": (144, 32),
    "I_update": (130, 16),
}
SEQUENCES = ("", "T", "I", "J", "TT", "TI", "TJ", "IT", "II", "IJ", "JT", "JI", "JJ")
CLASS_WORDS = ("T-shirt/top", "Trouser", "Pullover", "Dress", "Coat", "Sandal",
               "Shirt", "Sneaker", "Bag", "Ankle boot")


def _matrix(value, width, name, image=False):
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or array.dtype.kind == "b":
        raise ValueError(name + " must be numeric")
    array = np.asarray(array, dtype=np.float64)
    if image and array.ndim == 3 and array.shape[1:] == (28, 28):
        array = array.reshape(-1, 784)
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] != width:
        raise ValueError(name + " has invalid shape")
    if not np.isfinite(array).all() or (image and ((array < 0).any() or (array > 1).any())):
        raise ValueError(name + " has invalid values")
    return array


def _sequence(value):
    if not isinstance(value, str) or value not in SEQUENCES:
        raise ValueError("sequence must contain at most two T/I/J actions")
    return value


def categorical_ce(shifted, probabilities, denominator, labels):
    """Stable CE value and logits VJP, including a near-certain true class."""
    p = probabilities.data
    rows = np.arange(len(p))
    py = p[rows, labels]
    other = p.copy()
    other[rows, labels] = 0
    complement = other.sum(axis=-1)
    value = np.log(denominator.data[:, 0]) - shifted.data[rows, labels]
    dominant = py > 0.5
    value[dominant] = np.log1p(complement[dominant] / py[dominant])
    derivative = other
    derivative[rows, labels] = -complement
    return Tensor.operation(value, (shifted, lambda g: derivative * g[:, None]))


def joint_risk(shifted, probabilities, quality, labels, objective="N"):
    """Exact class marginal and fixed-K image risk, with stable separate VJPs."""
    p, q = probabilities.data, quality.data
    rows = np.arange(len(p))
    py = p[rows, labels]
    other = p.copy()
    other[rows, labels] = 0
    complement = other.sum(axis=-1)
    if objective == "N":
        exponent = np.exp(-2 * q)
        benefit = -np.expm1(-2 * q).mean(axis=-1)
        normalization = 1 - py * benefit
        value = -0.5 * np.log1p(-py * benefit)
        factor = py * benefit / (2 * normalization)
        quality_derivative = py[:, None] * exponent / (q.shape[-1] * normalization[:, None])
    elif objective == "A":
        benefit = q.mean(axis=-1)
        value = py * benefit
        factor = py * benefit
        quality_derivative = np.broadcast_to(py[:, None] / q.shape[-1], q.shape)
    else:
        raise ValueError("joint risk objective must be A or N")
    logits_derivative = -factor[:, None] * other
    logits_derivative[rows, labels] = factor * complement
    return Tensor.operation(value, (shifted, lambda g: logits_derivative * g[:, None]),
                            (quality, lambda g: quality_derivative * g[:, None]))


class _Trainable:
    def __init__(self, seed, modules):
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("seed must be a nonnegative signed 64-bit integer")
        self.seed, self.params, self._moments = seed, {}, {}
        rng = np.random.Generator(np.random.PCG64DXSM(seed))
        for name, (din, dout) in modules.items():
            self.params[name + ".W"] = rng.normal(0, 1 / np.sqrt(din), (din, dout))
            self.params[name + ".b"] = np.zeros(dout, dtype=np.float64)

    def _leaves(self, grad):
        return {name: Tensor(value, grad) for name, value in self.params.items()}

    def adam_step(self, grads, lr=0.001):
        if isinstance(lr, (bool, np.bool_)) or not np.isfinite(lr) or lr <= 0:
            raise ValueError("learning rate must be finite and positive")
        if not isinstance(grads, dict) or not set(grads) <= set(self.params):
            raise ValueError("gradient keys do not match this model")
        checked = {}
        for name, value in grads.items():
            g = np.asarray(value)
            if g.dtype != np.float64 or g.shape != self.params[name].shape or not np.isfinite(g).all():
                raise ValueError("invalid gradient: " + name)
            checked[name] = g
        pending = {}
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                for name, g in checked.items():
                    p = self.params[name]
                    m, v, t = self._moments.get(name, (None, None, 0))
                    m = np.zeros_like(p) if m is None else m
                    v = np.zeros_like(p) if v is None else v
                    t += 1
                    m = 0.9 * m + 0.1 * g
                    v = 0.999 * v + 0.001 * (g * g)
                    update = lr * (m / (1 - 0.9**t)) / (np.sqrt(v / (1 - 0.999**t)) + 1e-8)
                    pending[name] = (p - update, m, v, t)
        except FloatingPointError as error:
            raise ValueError("nonfinite Adam update") from error
        for name, (p, m, v, t) in pending.items():
            self.params[name][...] = p
            self._moments[name] = (m, v, t)

    def digest(self):
        digest = hashlib.sha256(json.dumps([self.kind, self.seed], separators=(",", ":")).encode())
        for name, value in self.params.items():
            digest.update(name.encode() + b"\0" + value.astype("<f8", copy=False).tobytes())
        return digest.hexdigest()

    def optimizer_digest(self):
        digest = hashlib.sha256()
        for name in sorted(self._moments):
            m, v, t = self._moments[name]
            digest.update(name.encode() + b"\0" + str(t).encode() + b"\0")
            digest.update(m.astype("<f8", copy=False).tobytes())
            digest.update(v.astype("<f8", copy=False).tobytes())
        return digest.hexdigest()

    def to_arrays(self, include_optimizer=False):
        arrays = {name: value.copy() for name, value in self.params.items()}
        arrays.update(_version=np.array(1, dtype=np.int64), _seed=np.array(self.seed, dtype=np.int64),
                      _kind=np.array(self.kind), _has_optimizer=np.array(bool(include_optimizer)))
        if include_optimizer:
            for name, (m, v, t) in self._moments.items():
                arrays["adam.m." + name], arrays["adam.v." + name] = m.copy(), v.copy()
                arrays["adam.t." + name] = np.array(t, dtype=np.int64)
        return arrays

    @classmethod
    def from_arrays(cls, arrays):
        arrays = dict(arrays)
        for key in ("_version", "_seed", "_kind", "_has_optimizer"):
            if key not in arrays or np.asarray(arrays[key]).shape != ():
                raise ValueError("missing or invalid model metadata")
        if (arrays["_version"].dtype != np.int64 or arrays["_version"].item() != 1
                or arrays["_seed"].dtype != np.int64 or arrays["_kind"].dtype.kind != "U"
                or arrays["_kind"].item() != cls.kind or arrays["_has_optimizer"].dtype != np.bool_):
            raise ValueError("model metadata identity mismatch")
        model = cls(arrays["_seed"].item())
        expected = set(model.params) | {"_version", "_seed", "_kind", "_has_optimizer"}
        for name, target in model.params.items():
            value = arrays.get(name)
            if (not isinstance(value, np.ndarray) or value.dtype != np.float64
                    or value.shape != target.shape or not np.isfinite(value).all()):
                raise ValueError("invalid saved parameter: " + name)
            target[...] = value
            moment_keys = {"adam." + part + "." + name for part in ("m", "v", "t")}
            present = moment_keys & set(arrays)
            if present:
                if present != moment_keys or not arrays["_has_optimizer"].item():
                    raise ValueError("incomplete optimizer state")
                m, v, t = (arrays["adam." + part + "." + name] for part in ("m", "v", "t"))
                if (m.dtype != np.float64 or v.dtype != np.float64 or m.shape != target.shape
                        or v.shape != target.shape or not np.isfinite(m).all() or not np.isfinite(v).all()
                        or (v < 0).any() or t.shape != () or t.dtype != np.int64 or t.item() <= 0):
                    raise ValueError("invalid saved optimizer state")
                model._moments[name] = (m.copy(), v.copy(), t.item())
                expected.update(moment_keys)
        if set(arrays) != expected:
            raise ValueError("unexpected saved model fields")
        return model

    def export(self, path, include_optimizer=False):
        with Path(path).open("xb") as handle:
            np.savez(handle, **self.to_arrays(include_optimizer))

    @classmethod
    def load(cls, path):
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if (len(entries) > 100 or len({e.filename for e in entries}) != len(entries)
                    or sum(e.file_size for e in entries) > 8 * 1024**2
                    or any(not e.filename.endswith(".npy") for e in entries)):
                raise ValueError("saved model exceeds bounded NPZ format")
        with np.load(path, allow_pickle=False) as arrays:
            return cls.from_arrays({name: arrays[name] for name in arrays.files})


@dataclass(frozen=True)
class Prediction:
    p: np.ndarray
    mu: np.ndarray
    image: np.ndarray
    classes: np.ndarray


@dataclass
class _State:
    text: Tensor
    image: Tensor
    p: Tensor
    shifted: Tensor
    denominator: Tensor
    mu: Tensor


class ContentModel(_Trainable):
    kind = "fashion-shared-content-v1"
    sigma_input, sigma_terminal, terminal_k, rho = 0.20, 0.05, 4, 2.0

    def __init__(self, seed):
        super().__init__(seed, MODULES)

    @staticmethod
    def _affine(value, name, ctx):
        return value @ ctx["params"][name + ".W"] + ctx["params"][name + ".b"]

    def _context(self, z, grad):
        z = Tensor(_matrix(z, 784, "noisy input", image=True))
        n = z.data.shape[0]
        patches = z.reshape(n, 7, 4, 7, 4).transpose(0, 1, 3, 2, 4).reshape(n, 49, 16)
        positions = np.array([(r / 3 - 1, c / 3 - 1) for r in range(7) for c in range(7)])
        ctx = {"params": self._leaves(grad), "z": z, "patches": patches,
               "positions": Tensor(np.broadcast_to(positions, (n, 49, 2))),
               "text_heads": {}, "image_heads": {}, "qT": {}, "qI": {}, "feedback": {}}
        ctx["c"] = self._affine(z, "C", ctx).tanh()
        text = self._affine(ctx["c"], "T_initial", ctx).tanh()
        image = self._affine(concatenate((self._patch_global(ctx["c"]), patches, ctx["positions"])),
                             "I_initial", ctx).tanh()
        return ctx, self._state(text, image, ctx)

    @staticmethod
    def _patch_global(value):
        return value.reshape(value.data.shape[0], 1, value.data.shape[-1]).broadcast_to(
            (value.data.shape[0], 49, value.data.shape[-1]))

    def _state(self, text, image, ctx):
        if text not in ctx["text_heads"]:
            ctx["text_heads"][text] = posterior(self._affine(text, "text_head", ctx))
        if image not in ctx["image_heads"]:
            patches = (ctx["patches"] + self._affine(image, "image_head", ctx)).clip(0, 1)
            n = patches.data.shape[0]
            ctx["image_heads"][image] = patches.reshape(n, 7, 7, 4, 4).transpose(
                0, 1, 3, 2, 4).reshape(n, 784)
        p, shifted, denominator = ctx["text_heads"][text]
        return _State(text, image, p, shifted, denominator, ctx["image_heads"][image])

    def _observe(self, state, ctx):
        if state.text not in ctx["qT"]:
            ctx["qT"][state.text] = self._affine(concatenate((state.text, state.p)), "qT", ctx).tanh()
        if state.image not in ctx["qI"]:
            n = state.mu.data.shape[0]
            pixels = state.mu.reshape(n, 7, 4, 7, 4).transpose(0, 1, 3, 2, 4).reshape(n, 49, 16)
            ctx["qI"][state.image] = self._affine(
                concatenate((state.image, pixels, ctx["patches"])), "qI", ctx).tanh()
        qt, qi = ctx["qT"][state.text], ctx["qI"][state.image]
        key = (state.text, state.image)
        if key not in ctx["feedback"]:
            ctx["feedback"][key] = self._affine(concatenate((ctx["c"], qt, qi.mean(axis=1))),
                                               "feedback", ctx).tanh()
        return qt, qi, ctx["feedback"][key]

    def _updates(self, state, action, ctx):
        qt, qi, feedback = self._observe(state, ctx)
        text, image = state.text, state.image
        if action in ("T", "J"):
            text = text + self._affine(concatenate((text, ctx["c"], feedback, qt)), "T_update", ctx).tanh()
        if action in ("I", "J"):
            image = image + self._affine(concatenate((image, self._patch_global(ctx["c"]),
                                                    self._patch_global(feedback), qi, ctx["positions"])),
                                         "I_update", ctx).tanh()
        return text, image

    def _advance(self, state, action, ctx):
        return self._state(*self._updates(state, action, ctx), ctx)

    def _branches(self, state, ctx):
        text, image = self._updates(state, "J", ctx)
        return {"T": self._state(text, state.image, ctx), "I": self._state(state.text, image, ctx),
                "J": self._state(text, image, ctx)}

    @staticmethod
    def _prediction(state):
        p, mu = state.p.data.view(), state.mu.data.view()
        p.setflags(write=False)
        mu.setflags(write=False)
        return Prediction(p, mu, mu.astype(np.float32).reshape(-1, 28, 28), p.argmax(axis=-1))

    def infer(self, z, sequence):
        sequence = _sequence(sequence)
        ctx, state = self._context(z, False)
        for action in sequence:
            state = self._advance(state, action, ctx)
        return self._prediction(state)

    def all_sequences(self, z, *, return_features=False):
        ctx, initial = self._context(z, False)
        first = self._branches(initial, ctx)
        states = {"": initial, **first}
        for prefix, state in first.items():
            states.update({prefix + action: child for action, child in self._branches(state, ctx).items()})
        predictions = {sequence: self._prediction(states[sequence]) for sequence in SEQUENCES}
        if return_features:
            return predictions, self._observe(first["J"], ctx)[2].data.copy()
        return predictions

    def j_candidates(self, z):
        ctx, state = self._context(z, False)
        state = self._advance(state, "J", ctx)
        candidates = self._branches(state, ctx)
        features = self._observe(state, ctx)[2].data.copy()
        return features, {"J" + action: self._prediction(child) for action, child in candidates.items()}

    def _loss(self, z, clean, labels, sequence, rng, terminal_noise, objective, grad):
        sequence = _sequence(sequence)
        z, clean = _matrix(z, 784, "noisy input", True), _matrix(clean, 784, "reference", True)
        labels = np.asarray(labels)
        if clean.shape != z.shape or labels.shape != (len(z),) or labels.dtype.kind not in "iu":
            raise ValueError("reference/label shapes do not match noisy inputs")
        if (labels < 0).any() or (labels >= 10).any() or objective not in ("N", "A", "anchor"):
            raise ValueError("invalid labels or objective")
        noise = None
        if objective != "anchor":
            if terminal_noise is None:
                if not isinstance(rng, np.random.Generator):
                    raise ValueError("terminal sampling requires a NumPy Generator")
                noise = rng.standard_normal((len(z), 4, 784))
            else:
                noise = np.asarray(terminal_noise, dtype=np.float64)
                if noise.shape != (len(z), 4, 784) or not np.isfinite(noise).all():
                    raise ValueError("invalid terminal noise")
        ctx, state = self._context(z, grad)
        for action in sequence:
            state = self._advance(state, action, ctx)
        difference = state.mu - clean
        mse = (difference * difference).mean(axis=-1)
        ce = categorical_ce(state.shifted, state.p, state.denominator, labels)
        anchor = ce + mse / 0.04
        risk = Tensor(np.zeros(len(z)))
        if objective != "anchor":
            samples = (state.mu.reshape(len(z), 1, 784) + 0.05 * noise).clip(0, 1)
            error = samples - clean[:, None, :]
            q = ((error * error).mean(axis=-1) / -0.04).exp()
            risk = joint_risk(state.shifted, state.p, q, labels, objective)
        loss = (anchor - 0.1 * risk).mean()
        metrics = {"ce": float(ce.data.mean()), "mse": float(mse.data.mean()),
                   "anchor": float(anchor.data.mean()), "risk": float(risk.data.mean()),
                   "n": len(z), "sequence": sequence, "objective": objective}
        return loss, ctx, metrics

    def loss_value(self, z, clean, labels, sequence, rng, *, terminal_noise=None, objective="N"):
        return float(self._loss(z, clean, labels, sequence, rng, terminal_noise, objective, False)[0].data)

    def loss_grad(self, z, clean, labels, sequence, rng, *, terminal_noise=None, objective="N"):
        loss, ctx, metrics = self._loss(z, clean, labels, sequence, rng, terminal_noise, objective, True)
        loss.backward()
        grads = {name: value.grad for name, value in ctx["params"].items() if value.grad is not None}
        return float(loss.data), grads, metrics


class Actor(_Trainable):
    kind = "fashion-final-action-values-v1"

    def __init__(self, seed):
        super().__init__(seed, {"hidden": (32, 8), "values": (8, 3)})

    def _forward(self, features, grad):
        features, params = Tensor(_matrix(features, 32, "actor features")), self._leaves(grad)
        hidden = (features @ params["hidden.W"] + params["hidden.b"]).tanh()
        return hidden @ params["values.W"] + params["values.b"], params

    def predict(self, features):
        return self._forward(features, False)[0].data.copy()

    def loss_grad(self, features, targets):
        features, targets = _matrix(features, 32, "actor features"), _matrix(targets, 3, "actor targets")
        if len(features) != len(targets):
            raise ValueError("actor feature/target row mismatch")
        output, params = self._forward(features, True)
        residual = output - targets
        loss = (residual * residual).mean()
        loss.backward()
        return float(loss.data), {name: value.grad for name, value in params.items()}, {"n": len(features)}


def construct(seed):
    return ContentModel(seed)
